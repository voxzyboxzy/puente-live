"""HTTP and WebSocket API for Puente Live."""

from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import __version__
from .db import Database
from .dialogues import REPLAYS
from .engine import SessionService, replay_catalog
from .kb import ARTICLES
from .llm import LLMSettings
from .scenarios import SCENARIOS
from .state_machine import describe
from .transcribe import transcribe_base64, whisper_status

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


class SessionIn(BaseModel):
    language: str = "en"


class MessageIn(BaseModel):
    text: str
    source: str = "text"


class TakeoverIn(BaseModel):
    tech_id: str = "tech-synthetic-01"
    note: str = ""


class TechMessageIn(BaseModel):
    text: str = Field(min_length=1)


class AudioIn(BaseModel):
    audio_b64: str = ""
    mime: str = "audio/webm"


def create_app(db_path: str | None = None) -> FastAPI:
    settings = LLMSettings()
    path = db_path or os.getenv("PUENTE_DB", os.path.join(ROOT, "backend", "data", "puente.db"))
    database = Database(path)
    database.migrate()
    service = SessionService(database, settings)
    app = FastAPI(title="Puente Live", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.svc = service
    app.state.settings = settings

    @app.get("/api/health")
    def health() -> dict:
        return {
            "ok": True,
            "service": "puente-live",
            "version": __version__,
            "llm_mode": settings.mode,
            "whisper": whisper_status(),
            "scenarios": list(SCENARIOS),
        }

    @app.get("/api/state-machine")
    def state_machine() -> dict:
        return describe()

    @app.get("/api/scenarios")
    def scenarios() -> dict:
        items = []
        for scenario in SCENARIOS.values():
            items.append(
                {
                    "id": scenario["id"],
                    "title_en": scenario["title_en"],
                    "title_es": scenario["title_es"],
                    "prompt_en": scenario["prompt_en"],
                    "prompt_es": scenario["prompt_es"],
                    "kb_id": scenario["kb_id"],
                    "steps": len(scenario["steps"]),
                }
            )
        return {"scenarios": items}

    @app.get("/api/kb")
    def knowledge() -> dict:
        return {
            "articles": [
                {
                    "id": article["id"],
                    "scenario_id": article["scenario_id"],
                    "title_en": article["title_en"],
                    "title_es": article["title_es"],
                    "source_label": article["source_label"],
                }
                for article in ARTICLES
            ]
        }

    @app.get("/api/replays")
    def replays() -> dict:
        return {"replays": replay_catalog()}

    @app.get("/api/replays/{replay_id}")
    def replay(replay_id: str) -> dict:
        item = REPLAYS.get(replay_id)
        if not item:
            raise HTTPException(status_code=404, detail="replay not found")
        return item

    @app.post("/api/sessions")
    def create_session(body: SessionIn | None = None) -> dict:
        language = body.language if body else "en"
        return service.create(language)

    @app.get("/api/sessions/{session_id}")
    def read_session(session_id: str) -> dict:
        try:
            return service.get(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    @app.post("/api/sessions/{session_id}/messages")
    def post_message(session_id: str, body: MessageIn) -> dict:
        try:
            return service.handle_turn(session_id, body.text, source=body.source)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    @app.post("/api/sessions/{session_id}/takeover")
    def takeover(session_id: str, body: TakeoverIn) -> dict:
        try:
            return service.takeover(session_id, body.tech_id, body.note)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    @app.post("/api/sessions/{session_id}/technician")
    def technician(session_id: str, body: TechMessageIn) -> dict:
        try:
            return service.technician_message(session_id, body.text)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    @app.get("/api/sessions/{session_id}/export")
    def export(session_id: str, format: str = "json") -> dict:
        if format not in {"json", "markdown"}:
            raise HTTPException(status_code=400, detail="format must be json or markdown")
        try:
            return service.export(session_id, format)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="session not found") from exc

    @app.post("/api/transcribe")
    def transcribe(body: AudioIn) -> dict:
        return transcribe_base64(body.audio_b64, body.mime)

    @app.websocket("/ws/sessions/{session_id}")
    async def ws_session(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        if service.db.load_session(session_id) is None:
            await websocket.send_json({"type": "error", "message": "unknown session"})
            await websocket.close()
            return
        incoming: asyncio.Queue = asyncio.Queue()

        async def reader() -> None:
            try:
                while True:
                    incoming.put_nowait(await websocket.receive_json())
            except Exception:
                await incoming.put({"type": "_closed"})

        reader_task = asyncio.create_task(reader())
        try:
            while True:
                message = await incoming.get()
                if message.get("type") == "_closed":
                    break
                await _handle_ws(websocket, service, session_id, message, incoming)
        finally:
            reader_task.cancel()

    return app


async def _handle_ws(websocket: WebSocket, service: SessionService, session_id: str, message: dict, incoming: asyncio.Queue) -> None:
    kind = message.get("type")
    if kind == "interrupt":
        service.interrupt(session_id)
        await websocket.send_json({"type": "interrupted"})
        return
    if kind == "technician_takeover":
        result = service.takeover(session_id, message.get("tech_id") or "tech-synthetic-01", message.get("note") or "")
        await _emit_result(websocket, result)
        return
    if kind == "technician_message":
        result = service.technician_message(session_id, message.get("text") or "")
        await _emit_result(websocket, result)
        return
    if kind == "user_audio":
        transcribed = transcribe_base64(message.get("audio_b64") or "", message.get("mime") or "audio/webm")
        await websocket.send_json({"type": "transcription", "result": transcribed})
        if not transcribed.get("ok"):
            return
        message = {"type": "user_text", "text": transcribed.get("text") or "", "source": "whisper"}
        kind = "user_text"
    if kind == "user_text":
        pending: list[dict] = []
        async for event in service.stream_turn(session_id, message.get("text") or "", source=message.get("source") or "text"):
            drained: list[dict] = []
            while not incoming.empty():
                drained.append(incoming.get_nowait())
            for nxt in drained:
                if nxt.get("type") in {"interrupt", "user_text", "user_audio"}:
                    service.interrupt(session_id)
                if nxt.get("type") != "interrupt":
                    pending.append(nxt)
            await websocket.send_json(event)
        for item in pending:
            await incoming.put(item)
        return
    await websocket.send_json({"type": "error", "message": "unknown message"})


async def _emit_result(websocket: WebSocket, result: dict) -> None:
    await websocket.send_json({"type": "assistant_done", "text": result["assistant_text"], "language": result["language"]})
    await websocket.send_json({"type": "graph", "graph": result["graph"]})
    await websocket.send_json({"type": "session", "session": result["session"]})
    if result.get("ticket"):
        await websocket.send_json({"type": "ticket", "ticket": result["ticket"]})
    await websocket.send_json({"type": "turn_done", "phase": result["phase"], "interrupted": False})


app = create_app()
