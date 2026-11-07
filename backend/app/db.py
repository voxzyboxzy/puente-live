"""SQLite persistence for sessions, transcripts, events, and tickets."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def migrate(self) -> None:
        with self._lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    scenario_id TEXT,
                    language TEXT,
                    state_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS utterances (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    language TEXT,
                    phase TEXT,
                    redaction_count INTEGER DEFAULT 0,
                    source TEXT,
                    interrupted INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tickets (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    body_json TEXT NOT NULL,
                    body_md TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self.conn.commit()

    def save_session(self, state: dict) -> None:
        payload = json.dumps(state, ensure_ascii=False)
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO sessions (id, created_at, phase, scenario_id, language, state_json)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    phase=excluded.phase,
                    scenario_id=excluded.scenario_id,
                    language=excluded.language,
                    state_json=excluded.state_json
                """,
                (
                    state["id"],
                    state["created_at"],
                    state["phase"],
                    state.get("scenario_id"),
                    state.get("language"),
                    payload,
                ),
            )
            self.conn.commit()

    def load_session(self, session_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT state_json FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        if not row:
            return None
        return json.loads(row["state_json"])

    def add_utterance(
        self,
        session_id: str,
        role: str,
        text: str,
        language: str,
        phase: str,
        redaction_count: int = 0,
        source: str = "text",
        interrupted: bool = False,
    ) -> int:
        with self._lock:
            cursor = self.conn.execute(
                """
                INSERT INTO utterances (
                    session_id, role, text, language, phase, redaction_count, source, interrupted, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    text,
                    language,
                    phase,
                    redaction_count,
                    source,
                    1 if interrupted else 0,
                    utcnow(),
                ),
            )
            self.conn.commit()
            return int(cursor.lastrowid)

    def mark_last_assistant(self, session_id: str, text: str, interrupted: bool) -> None:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT id FROM utterances
                WHERE session_id = ? AND role = 'assistant'
                ORDER BY id DESC LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if not row:
                return
            self.conn.execute(
                "UPDATE utterances SET text = ?, interrupted = ? WHERE id = ?",
                (text, 1 if interrupted else 0, row["id"]),
            )
            self.conn.commit()

    def transcript(self, session_id: str) -> list[dict]:
        with self._lock:
            rows = self.conn.execute(
                """
                SELECT id, role, text, language, phase, redaction_count, source, interrupted, created_at
                FROM utterances WHERE session_id = ? ORDER BY id ASC
                """,
                (session_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_event(self, session_id: str, kind: str, payload: dict) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT INTO events (session_id, kind, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (session_id, kind, json.dumps(payload, ensure_ascii=False), utcnow()),
            )
            self.conn.commit()

    def save_ticket(self, ticket_id: str, session_id: str, status: str, body: dict, markdown: str) -> None:
        with self._lock:
            self.conn.execute(
                """
                INSERT INTO tickets (id, session_id, status, body_json, body_md, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    body_json=excluded.body_json,
                    body_md=excluded.body_md
                """,
                (
                    ticket_id,
                    session_id,
                    status,
                    json.dumps(body, ensure_ascii=False),
                    markdown,
                    body.get("created_at") or utcnow(),
                ),
            )
            self.conn.commit()

    def load_ticket(self, session_id: str) -> dict | None:
        with self._lock:
            row = self.conn.execute(
                """
                SELECT id, status, body_json, body_md, created_at
                FROM tickets WHERE session_id = ? ORDER BY created_at DESC LIMIT 1
                """,
                (session_id,),
            ).fetchone()
        if not row:
            return None
        body = json.loads(row["body_json"])
        body["markdown"] = row["body_md"]
        return body
