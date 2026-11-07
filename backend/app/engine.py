"""Deterministic troubleshooting engine.

The state machine, tools, and templates decide the outcome. An optional
Ollama pass may rephrase a finished reply and is discarded if it drops a
fact or turns a warning into advice.
"""

from __future__ import annotations

import secrets
from typing import AsyncIterator

from . import kb
from .db import Database, utcnow
from .dialogues import REPLAYS
from .export import render_markdown
from .llm import LLMSettings, rephrase
from .nlu import (
    claims_fixed,
    detect_language,
    extract_entities,
    infer_polarities,
    is_generic_done,
    is_greeting,
    match_scenario,
    polarities_contradict,
    requests_human,
    split_facts,
)
from .redaction import redact
from .safety import response_is_unsafe, response_risks, user_requests_unsafe
from .scenarios import (
    SCENARIOS,
    apply_step,
    initial_world,
    is_resolved,
    matched_steps,
    next_step_id,
    step_copy,
)
from .state_machine import StateError, transition
from .tools import reset_password, run_checks

PHRASES: dict[str, dict[str, dict[str, str]]] = {
    "en": {
        "up": {
            "internet": "the internet is working",
            "vpn": "the VPN is working",
            "wifi": "Wi-Fi is connected",
            "dns": "websites are loading",
            "printer": "the printer is online",
        },
        "down": {
            "internet": "the internet is not working",
            "vpn": "the VPN is not working",
            "wifi": "Wi-Fi is not connected",
            "dns": "websites are not loading",
            "printer": "the printer is offline",
        },
    },
    "es": {
        "up": {
            "internet": "el internet funciona",
            "vpn": "la VPN funciona",
            "wifi": "el Wi-Fi está conectado",
            "dns": "las páginas cargan",
            "printer": "la impresora está en línea",
        },
        "down": {
            "internet": "el internet no funciona",
            "vpn": "la VPN no funciona",
            "wifi": "el Wi-Fi no está conectado",
            "dns": "las páginas no cargan",
            "printer": "la impresora está fuera de línea",
        },
    },
}

CAUSES = {
    "vpn_down": {
        "en": "The pattern matches a stopped client or a stale company sign-in.",
        "es": "El patrón coincide con un cliente detenido o un inicio de sesión de la empresa vencido.",
    },
    "dns_failure": {
        "en": "The pattern matches a dirty resolver cache and an old network lease.",
        "es": "El patrón coincide con una caché de resolver sucia y un arrendamiento viejo de CORP-WIFI.",
    },
    "printer_offline": {
        "en": "The pattern matches a paused queue while power is present.",
        "es": "El patrón coincide con una cola en pausa y con energía presente.",
    },
}

REFUSAL = {
    "en": (
        "I can't do that. Do not disable the firewall. Do not turn off antivirus. "
        "Do not open all ports. Do not format a disk. I will not reveal a password."
    ),
    "es": (
        "No puedo hacer eso. No desactives el firewall. No apagues el antivirus. "
        "No abras todos los puertos. No formatees el disco. No voy a revelar una contraseña."
    ),
}


def new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(3).upper()}"


def contrast_sentence(state: dict, language: str) -> str:
    bits: list[str] = []
    for service in ("internet", "vpn", "wifi", "dns", "printer"):
        polarity = (state.get("reported_polarities") or {}).get(service)
        if polarity in {"up", "down"}:
            bits.append(PHRASES[language][polarity][service])
    if not bits:
        return ""
    if language == "es":
        sentence = " y ".join(bits)
    else:
        sentence = ", and ".join(bits)
    return sentence[:1].upper() + sentence[1:] + "."


def facts_line(state: dict, language: str) -> str:
    if not state.get("reported_polarities") and not state.get("error_codes") and not state.get("devices"):
        return ""
    devices = ", ".join(state.get("devices") or []) or "unspecified"
    codes = ", ".join(state.get("error_codes") or []) or "none"
    bits = []
    for service in ("internet", "vpn", "wifi", "dns", "printer"):
        polarity = (state.get("reported_polarities") or {}).get(service)
        if polarity in {"up", "down"}:
            bits.append(PHRASES[language][polarity][service])
    detail = "; ".join(bits)
    tail = f"; {detail}" if detail else ""
    if language == "es":
        return f"Datos del incidente: dispositivo {devices}; error {codes}{tail}."
    return f"Incident facts: device {devices}; error {codes}{tail}."


class SessionService:
    def __init__(self, db: Database, settings: LLMSettings | None = None):
        self.db = db
        self.settings = settings or LLMSettings()
        self._gens: dict[str, int] = {}

    def create(self, language: str = "en") -> dict:
        language = language if language in {"en", "es"} else "en"
        state = {
            "id": new_id("SES"),
            "created_at": utcnow(),
            "phase": "intake",
            "scenario_id": None,
            "language": language,
            "language_confidence": 1.0,
            "language_path": [],
            "reported_polarities": {},
            "error_codes": [],
            "devices": [],
            "world": None,
            "steps_done": [],
            "failures": 0,
            "phase_log": [],
            "technician": None,
            "redaction_count": 0,
            "citations": [],
            "last_checks": [],
            "actions": [],
            "resolution": None,
            "ticket_id": None,
            "provider": "deterministic",
        }
        self.db.save_session(state)
        self._gens[state["id"]] = 0
        greeting = self._greeting(language)
        self.db.add_utterance(state["id"], "assistant", greeting, language, "intake", 0, "system")
        return self._pack(state, greeting, [], [], None, [])

    def interrupt(self, session_id: str) -> int:
        self._gens[session_id] = self._gens.get(session_id, 0) + 1
        return self._gens[session_id]

    def generation(self, session_id: str) -> int:
        return self._gens.get(session_id, 0)

    def get(self, session_id: str) -> dict:
        state = self._load(session_id)
        ticket = self.db.load_ticket(session_id)
        packed = self._pack(state, "", [], state.get("last_checks") or [], ticket, [])
        packed["transcript"] = self.db.transcript(session_id)
        return packed

    def handle_turn(self, session_id: str, text: str, source: str = "text") -> dict:
        state = self._load(session_id)
        raw = (text or "").strip()
        language = state["language"]
        if not raw:
            reply = self._empty(language)
            self._say(state, reply, language, [])
            return self._finish(state, reply, [], [])

        redacted, redactions = redact(raw)
        state["redaction_count"] += len(redactions)
        detected, confidence = detect_language(raw)
        if detected != "und":
            language = detected
            state["language"] = detected
            state["language_confidence"] = confidence
            path = state.setdefault("language_path", [])
            if not path or path[-1] != detected:
                path.append(detected)
        else:
            state["language_confidence"] = confidence

        entities = extract_entities(raw)
        for code in entities["error_codes"]:
            if code not in state["error_codes"]:
                state["error_codes"].append(code)
        for device in entities["devices"]:
            if device not in state["devices"]:
                state["devices"].append(device)

        unsafe = user_requests_unsafe(raw)
        polarities = {} if unsafe else infer_polarities(raw)
        if polarities and not state["reported_polarities"]:
            state["reported_polarities"] = polarities

        if state.get("scenario_id"):
            found = kb.search(raw, scenario_id=state["scenario_id"], limit=2)
            scenario_hit = next((item for item in found if item.get("scenario_id") == state["scenario_id"]), None)
            if scenario_hit and scenario_hit.get("overlap", 0) > 0:
                state["citations"] = [kb.cite(item, language) for item in found]
            elif state.get("citations"):
                refreshed = []
                for old in state["citations"]:
                    article = kb.article_by_id(old["id"])
                    if not article:
                        continue
                    refreshed.append(
                        kb.cite(
                            {**article, "overlap": old.get("overlap", 0), "rank_score": old.get("rank_score", 0)},
                            language,
                        )
                    )
                if refreshed:
                    state["citations"] = refreshed

        self.db.add_utterance(
            state["id"], "user", redacted, language, state["phase"], len(redactions), source
        )
        self.db.add_event(
            state["id"],
            "user_turn",
            {"redactions": redactions, "language": language, "source": source},
        )

        if state["phase"] == "technician":
            reply = self._with_facts(self._tech_hold(language), state)
            self._say(state, reply, language, [])
            return self._finish(state, reply, [], redactions)

        if unsafe:
            reply = self._refusal_reply(state, language)
            try:
                self._move(state, "unsafe_refused")
            except StateError:
                pass
            self._say(state, reply, language, [])
            ticket = self._maybe_ticket(state)
            return self._finish(state, reply, [], redactions, ticket)

        if is_greeting(raw) and not state.get("scenario_id"):
            self._move(state, "clarify")
            reply = self._with_facts(self._greeting(language), state)
            self._say(state, reply, language, [])
            return self._finish(state, reply, [], redactions)

        scenario = state.get("scenario_id") or match_scenario(raw, entities)
        wants_human = requests_human(raw)

        if not state.get("scenario_id"):
            if not scenario:
                self._move(state, "clarify")
                reply = self._with_facts(self._clarify(language), state)
                self._say(state, reply, language, [])
                return self._finish(state, reply, [], redactions)
            tools = self._open_case(state, scenario, raw)
            reply = self._diagnosis(state)
            if any(item["kind"] == "password" for item in redactions):
                reply = self._secret_warning(language) + " " + reply
            if wants_human:
                self._move(state, "handoff_requested")
                if state.get("resolution") != "verified":
                    state["resolution"] = "escalated"
                reply = reply + " " + self._handoff_line(state, language)
            self._say(state, reply, language, tools)
            ticket = self._maybe_ticket(state)
            return self._finish(state, reply, tools, redactions, ticket)

        if state["phase"] == "guide":
            return self._guide(state, raw, language, redactions, wants_human)

        if state["phase"] in {"resolved", "handoff"}:
            if wants_human and state["phase"] == "resolved":
                self._move(state, "handoff_requested")
            else:
                self._move(state, "restate")
            reply = self._with_facts(self._closed_line(state, language), state)
            self._say(state, reply, language, [])
            ticket = self._maybe_ticket(state)
            return self._finish(state, reply, [], redactions, ticket)

        reply = self._with_facts(self._clarify(language), state)
        self._say(state, reply, language, [])
        return self._finish(state, reply, [], redactions)

    async def stream_turn(self, session_id: str, text: str, source: str = "text") -> AsyncIterator[dict]:
        start = self.generation(session_id)
        result = self.handle_turn(session_id, text, source=source)
        words = result["assistant_text"].split(" ")
        acc: list[str] = []
        step = 6
        for index in range(0, len(words), step):
            if self.generation(session_id) != start:
                partial = " ".join(acc).strip()
                self.db.mark_last_assistant(session_id, partial or "…", True)
                yield {"type": "interrupted", "partial_text": partial}
                yield {
                    "type": "turn_done",
                    "phase": result["phase"],
                    "interrupted": True,
                    "session": result["session"],
                }
                return
            chunk = " ".join(words[index : index + step])
            acc.append(chunk)
            suffix = "" if index + step >= len(words) else " "
            yield {"type": "assistant_delta", "text": chunk + suffix}
            delay = self.settings.stream_ms
            if delay:
                import asyncio

                await asyncio.sleep(delay / 1000)
        yield {
            "type": "assistant_done",
            "text": result["assistant_text"],
            "language": result["language"],
        }
        yield {"type": "graph", "graph": result["graph"]}
        yield {"type": "citations", "citations": result["citations"]}
        yield {"type": "tools", "tools": result["tools"]}
        yield {"type": "session", "session": result["session"]}
        if result.get("ticket"):
            yield {"type": "ticket", "ticket": result["ticket"]}
        yield {"type": "turn_done", "phase": result["phase"], "interrupted": False}

    def takeover(self, session_id: str, tech_id: str, note: str) -> dict:
        state = self._load(session_id)
        redacted, redactions = redact(note or "")
        state["redaction_count"] += len(redactions)
        if state["phase"] != "technician":
            self._move(state, "technician_takeover")
        if state.get("resolution") != "verified":
            state["resolution"] = "technician"
        state["technician"] = {"tech_id": tech_id or "tech-synthetic-01", "note": redacted}
        language = state["language"]
        reply = self._with_facts(self._takeover_line(language, state["technician"]["tech_id"]), state)
        self._say(state, reply, language, [])
        ticket = self._maybe_ticket(state)
        return self._finish(state, reply, [], redactions, ticket)

    def technician_message(self, session_id: str, text: str) -> dict:
        state = self._load(session_id)
        if state["phase"] != "technician":
            self._move(state, "technician_takeover")
            if state.get("resolution") != "verified":
                state["resolution"] = "technician"
            state["technician"] = state.get("technician") or {
                "tech_id": "tech-synthetic-01",
                "note": "",
            }
        redacted, redactions = redact(text or "")
        state["redaction_count"] += len(redactions)
        self.db.add_utterance(
            state["id"], "technician", redacted, state["language"], state["phase"], len(redactions), "technician"
        )
        try:
            self._move(state, "technician_message")
        except StateError:
            pass
        reply = self._with_facts(self._tech_ack(state["language"]), state)
        self._say(state, reply, state["language"], [])
        ticket = self._maybe_ticket(state)
        return self._finish(state, reply, [], redactions, ticket)

    def export(self, session_id: str, fmt: str = "json") -> dict:
        state = self._load(session_id)
        ticket = self._write_ticket(state, status=self._status(state))
        if fmt == "markdown":
            return {"format": "markdown", "ticket_id": ticket["ticket_id"], "content": ticket["markdown"]}
        body = dict(ticket)
        body.pop("markdown", None)
        return {"format": "json", "ticket_id": ticket["ticket_id"], "content": body}

    def _guide(self, state: dict, raw: str, language: str, redactions: list, wants_human: bool) -> dict:
        applied: list[str] = []
        tools: list[dict] = []
        for step_id in matched_steps(state["scenario_id"], raw):
            if step_id in state["steps_done"]:
                continue
            apply_step(state["world"], state["scenario_id"], step_id)
            state["steps_done"].append(step_id)
            applied.append(step_id)
            if step_id == "sso_reauth":
                action = reset_password(state["world"])
                tools.append(action)
                state.setdefault("actions", []).append(action)
        if not applied and is_generic_done(raw):
            step_id = next_step_id(state)
            if step_id:
                apply_step(state["world"], state["scenario_id"], step_id)
                state["steps_done"].append(step_id)
                applied.append(step_id)
                if step_id == "sso_reauth":
                    action = reset_password(state["world"])
                    tools.append(action)
                    state.setdefault("actions", []).append(action)

        if applied or claims_fixed(raw, state["phase"]) or is_generic_done(raw):
            self._move(state, "step_reported")
            checks = run_checks(state["world"])
            state["last_checks"] = checks
            tools = checks + tools
            if is_resolved(state["scenario_id"], state["world"]):
                state["resolution"] = "verified"
                self._move(state, "verify_pass")
                reply = self._success(state, language)
                if wants_human:
                    self._move(state, "handoff_requested")
                    reply = reply + " " + self._handoff_line(state, language)
            else:
                state["failures"] += 1
                if state["failures"] >= 3:
                    state["resolution"] = "escalated"
                    self._move(state, "max_failures")
                    reply = self._escalate(state, language)
                else:
                    self._move(state, "verify_fail")
                    reply = self._verify_fail(state, language)
            if any(item["kind"] == "password" for item in redactions):
                reply = self._secret_warning(language) + " " + reply
            self._say(state, reply, language, tools)
            ticket = self._maybe_ticket(state)
            return self._finish(state, reply, tools, redactions, ticket)

        if wants_human:
            self._move(state, "handoff_requested")
            if state.get("resolution") != "verified":
                state["resolution"] = "escalated"
            reply = self._with_facts(self._handoff_line(state, language), state)
            self._say(state, reply, language, [])
            ticket = self._maybe_ticket(state)
            return self._finish(state, reply, [], redactions, ticket)

        self._move(state, "restate")
        reply = self._with_facts(self._restate(state, language), state)
        if any(item["kind"] == "password" for item in redactions):
            reply = self._secret_warning(language) + " " + reply
        self._say(state, reply, language, [])
        return self._finish(state, reply, [], redactions)

    def _open_case(self, state: dict, scenario_id: str, raw: str) -> list[dict]:
        if scenario_id not in state["error_codes"] and not state["error_codes"]:
            state["error_codes"].append(SCENARIOS[scenario_id]["default_code"])
        if not state["devices"]:
            state["devices"].append(SCENARIOS[scenario_id]["default_device"])
        if scenario_id == "printer_offline":
            if not any(device.startswith("HP-") for device in state["devices"]):
                state["devices"].insert(0, "HP-LaserJet-M404")
            if not any(device.startswith("CORP-LAPTOP") or device.startswith("ThinkPad") for device in state["devices"]):
                state["devices"].append("CORP-LAPTOP-04")
        state["scenario_id"] = scenario_id
        state["world"] = initial_world(scenario_id, state["devices"])
        self._sync_code(state)
        self._move(state, "problem_detected")
        checks = run_checks(state["world"])
        state["last_checks"] = checks
        self._move(state, "checks_done")
        found = kb.search(raw, scenario_id=scenario_id, limit=2)
        state["citations"] = [kb.cite(item, state["language"]) for item in found]
        self._move(state, "plan_delivered")
        return checks

    def _sync_code(self, state: dict) -> None:
        code = state["error_codes"][0]
        world = state["world"]
        scenario = state["scenario_id"]
        if scenario == "vpn_down" and world["vpn"]["tunnel"] != "up":
            world["vpn"]["error_code"] = code
        elif scenario == "dns_failure" and not world["dns"]["resolves"]:
            world["dns"]["error_code"] = code
        elif scenario == "printer_offline" and not world["printer"]["online"]:
            world["printer"]["error_code"] = code

    def _diagnosis(self, state: dict) -> str:
        language = state["language"]
        scenario = SCENARIOS[state["scenario_id"]]
        contrast = contrast_sentence(state, language)
        devices = ", ".join(state["devices"])
        codes = ", ".join(state["error_codes"])
        top = state["citations"][0]
        step = step_copy(state["scenario_id"], next_step_id(state), language)
        total = len(scenario["steps"])
        cause = CAUSES[state["scenario_id"]][language]
        if language == "es":
            body = (
                f"{contrast} Equipos: {devices}. Códigos: {codes}. {cause} "
                f"Fuente: {top['source_label']}. "
                f"Paso seguro 1 de {total}: {step} "
                "No pegues una contraseña en este chat."
            )
        else:
            body = (
                f"{contrast} Devices: {devices}. Error codes: {codes}. {cause} "
                f"Source: {top['source_label']}. "
                f"Safe step 1 of {total}: {step} "
                "Do not paste a password in this chat."
            )
        return self._with_facts(body, state)

    def _verify_fail(self, state: dict, language: str) -> str:
        scenario = SCENARIOS[state["scenario_id"]]
        step_id = next_step_id(state)
        total = len(scenario["steps"])
        done = len(state["steps_done"])
        number = min(done + 1, total)
        step = step_copy(state["scenario_id"], step_id, language) if step_id else ""
        codes = ", ".join(state["error_codes"])
        devices = ", ".join(state["devices"])
        contrast = contrast_sentence(state, language)
        if language == "es":
            body = (
                f"{contrast} La comprobación simulada sigue viendo {codes} en {devices}. "
                f"Paso seguro {number} de {total}: {step}"
            )
        else:
            body = (
                f"{contrast} The simulated check still sees {codes} on {devices}. "
                f"Safe step {number} of {total}: {step}"
            )
        return self._with_facts(body, state)

    def _success(self, state: dict, language: str) -> str:
        devices = ", ".join(state["devices"])
        codes = ", ".join(state["error_codes"])
        if language == "es":
            body = (
                f"Las comprobaciones simuladas pasaron en {devices}. "
                f"El código reportado {codes} deja de estar activo y permanece en el paquete. "
                "Puedo entregar el paquete redactado a un técnico."
            )
        else:
            body = (
                f"Simulated checks passed on {devices}. "
                f"Reported code {codes} is no longer active and stays in the packet. "
                "I can hand the redacted packet to a technician."
            )
        return self._with_facts(body, state)

    def _escalate(self, state: dict, language: str) -> str:
        if language == "es":
            body = "Tres comprobaciones seguidas no limpiaron el fallo. Escalo el paquete redactado a un técnico."
        else:
            body = "Three checks in a row did not clear the fault. I am escalating the redacted packet to a technician."
        return self._with_facts(body + " " + self._handoff_line(state, language), state)

    def _restate(self, state: dict, language: str) -> str:
        step_id = next_step_id(state)
        step = step_copy(state["scenario_id"], step_id, language) if step_id else ""
        contrast = contrast_sentence(state, language)
        if language == "es":
            return f"Seguimos en la lista segura. {contrast} Siguiente: {step}"
        return f"We are still on the safe checklist. {contrast} Next: {step}"

    def _handoff_line(self, state: dict, language: str) -> str:
        status = self._status(state)
        if language == "es":
            return f"El paquete redactado está listo para un técnico. Estado: {status}."
        return f"The redacted packet is ready for a technician. Status: {status}."

    def _closed_line(self, state: dict, language: str) -> str:
        status = self._status(state)
        if language == "es":
            return f"Este puente ya tiene un resultado. Estado: {status}. El paquete redactado sigue disponible."
        return f"This bridge already has an outcome. Status: {status}. The redacted packet is still available."

    def _refusal_reply(self, state: dict, language: str) -> str:
        extra = ""
        if state.get("scenario_id") and state["phase"] == "guide":
            extra = " " + self._restate(state, language)
        elif not state.get("scenario_id"):
            extra = " " + self._clarify(language)
        return self._with_facts(REFUSAL[language] + extra, state)

    def _with_facts(self, body: str, state: dict) -> str:
        facts = facts_line(state, state["language"])
        text = " ".join(body.split())
        if facts and "Incident facts:" not in text and "Datos del incidente:" not in text:
            text = f"{text} {facts}"
        guarded = self._guard(text, state["language"])
        provider_text, provider = rephrase(guarded, state["language"], self.settings)
        if provider == "ollama" and self._rephrase_ok(guarded, provider_text, state):
            state["provider"] = "ollama"
            return provider_text
        state["provider"] = "deterministic"
        return guarded

    def _rephrase_ok(self, template: str, candidate: str, state: dict) -> bool:
        if response_is_unsafe(candidate):
            return False
        upper = candidate.upper()
        for code in state.get("error_codes") or []:
            if code.upper() not in upper:
                return False
        for device in state.get("devices") or []:
            if device not in candidate:
                return False
        _narrative, facts = split_facts(candidate)
        if state.get("reported_polarities") and polarities_contradict(facts, state["reported_polarities"]):
            return False
        if "Incident facts:" in template or "Datos del incidente:" in template:
            if "Incident facts:" not in candidate and "Datos del incidente:" not in candidate:
                return False
        return True

    def _guard(self, text: str, language: str) -> str:
        if not response_is_unsafe(text):
            return text
        safe = REFUSAL[language]
        facts = ""
        if "Incident facts:" in text:
            facts = " " + text[text.index("Incident facts:") :]
        elif "Datos del incidente:" in text:
            facts = " " + text[text.index("Datos del incidente:") :]
        return safe + facts

    def _say(self, state: dict, reply: str, language: str, tools: list[dict]) -> None:
        risks = response_risks(reply)
        self.db.save_session(state)
        self.db.add_utterance(state["id"], "assistant", reply, language, state["phase"], 0, state.get("provider") or "deterministic")
        self.db.add_event(
            state["id"],
            "assistant_turn",
            {"phase": state["phase"], "tools": [item["tool"] for item in tools], "risks": risks},
        )

    def _finish(self, state: dict, reply: str, tools: list, redactions: list, ticket: dict | None = None) -> dict:
        if ticket is None and state.get("resolution"):
            ticket = self._maybe_ticket(state)
        packed = self._pack(state, reply, state.get("citations") or [], tools, ticket, redactions)
        packed["transcript"] = self.db.transcript(state["id"])
        return packed

    def _maybe_ticket(self, state: dict) -> dict | None:
        if state.get("resolution") or state["phase"] in {"handoff", "resolved", "technician"}:
            return self._write_ticket(state, status=self._status(state))
        return None

    def _status(self, state: dict) -> str:
        if state.get("resolution"):
            return state["resolution"]
        if state["phase"] == "technician":
            return "technician"
        if state["phase"] == "handoff":
            return "escalated"
        return "in_progress"

    def _write_ticket(self, state: dict, status: str) -> dict:
        if not state.get("ticket_id"):
            state["ticket_id"] = new_id("INC")
        transcript = self.db.transcript(state["id"])
        published = []
        for turn in transcript:
            published.append(
                {
                    "role": turn["role"],
                    "text": turn["text"],
                    "language": turn["language"],
                    "phase": turn["phase"],
                    "redaction_count": turn["redaction_count"],
                    "interrupted": bool(turn["interrupted"]),
                }
            )
        body = {
            "ticket_id": state["ticket_id"],
            "session_id": state["id"],
            "status": status,
            "scenario_id": state.get("scenario_id"),
            "error_codes": list(state.get("error_codes") or []),
            "devices": list(state.get("devices") or []),
            "reported_polarities": dict(state.get("reported_polarities") or {}),
            "observed": self._observed(state),
            "steps_completed": list(state.get("steps_done") or []),
            "checks": state.get("last_checks") or [],
            "actions": state.get("actions") or [],
            "citations": state.get("citations") or [],
            "phase_log": state.get("phase_log") or [],
            "language_path": state.get("language_path") or [],
            "technician": state.get("technician"),
            "redaction_count": state.get("redaction_count") or 0,
            "transcript": published,
            "created_at": utcnow(),
            "synthetic": True,
            "disclaimer": "Synthetic incident. Device and network checks are simulated. No real network was contacted.",
        }
        markdown = render_markdown(body)
        body["markdown"] = markdown
        self.db.save_ticket(state["ticket_id"], state["id"], status, body, markdown)
        self.db.save_session(state)
        return body

    def _observed(self, state: dict) -> dict:
        world = state.get("world")
        if not world or not state.get("scenario_id"):
            return {}
        return {
            "wifi_internet": world["wifi"]["internet"],
            "vpn_tunnel": world["vpn"]["tunnel"],
            "dns_resolves": world["dns"]["resolves"],
            "printer_online": world["printer"]["online"],
            "sso": world["auth"]["sso"],
            "password_reset_queued": world.get("password_reset_queued", False),
            "resolved": is_resolved(state["scenario_id"], world),
        }

    def _pack(self, state: dict, reply: str, citations: list, tools: list, ticket: dict | None, redactions: list) -> dict:
        graph = build_graph(state)
        session = public_session(state, self.settings)
        safe_ticket = None
        if ticket:
            safe_ticket = dict(ticket)
        return {
            "session": session,
            "assistant_text": reply,
            "language": state["language"],
            "citations": citations or state.get("citations") or [],
            "tools": tools,
            "graph": graph,
            "phase": state["phase"],
            "ticket": safe_ticket,
            "redactions": redactions,
            "safety": {"risks": response_risks(reply)},
            "provider": state.get("provider") or "deterministic",
        }

    def _load(self, session_id: str) -> dict:
        state = self.db.load_session(session_id)
        if not state:
            raise KeyError(session_id)
        self._gens.setdefault(session_id, 0)
        return state

    def _move(self, state: dict, event: str) -> None:
        nxt = transition(state["phase"], event)
        state["phase_log"].append({"from": state["phase"], "event": event, "to": nxt})
        state["phase"] = nxt

    def _greeting(self, language: str) -> str:
        if language == "es":
            return (
                "Puente Live está en el puente. Cuéntame el fallo en español o en inglés. "
                "Puedo trabajar un túnel VPN, DNS con Wi-Fi asociado, o una cola de impresión. "
                "No te voy a pedir una contraseña."
            )
        return (
            "Puente Live is on the bridge. Tell me the fault in English or Spanish. "
            "I can work a VPN tunnel, DNS while Wi-Fi is associated, or a printer queue. "
            "I will not ask you for a password."
        )

    def _clarify(self, language: str) -> str:
        if language == "es":
            return (
                "Puedo tomar uno de tres casos sintéticos: internet activo con la VPN caída (VPN-ERR-4012), "
                "Wi-Fi activo con páginas caídas (DNS-ERR-2201), o una impresora fuera de línea (PRT-ERR-3308)."
            )
        return (
            "I can take one of three synthetic cases: internet up with the VPN down (VPN-ERR-4012), "
            "Wi-Fi up with websites down (DNS-ERR-2201), or a printer offline (PRT-ERR-3308)."
        )

    def _empty(self, language: str) -> str:
        if language == "es":
            return "Necesito una frase. Puedes escribir o dictar el fallo."
        return "I need a sentence. You can type or dictate the fault."

    def _secret_warning(self, language: str) -> str:
        if language == "es":
            return "Quité un secreto de la transcripción. Usa el aviso de SSO. No pegues una contraseña aquí."
        return "I removed a secret from the transcript. Use the SSO prompt. Do not paste a password here."

    def _tech_hold(self, language: str) -> str:
        if language == "es":
            return "Un técnico tiene el puente. Registro la nota y no agrego pasos."
        return "A technician has the bridge. I will record the note and I will not add steps."

    def _takeover_line(self, language: str, tech_id: str) -> str:
        if language == "es":
            return f"El técnico {tech_id} tomó el puente. El agente deja de guiar. La transcripción sigue redactada."
        return f"Technician {tech_id} took the bridge. The agent stops guiding. The transcript stays redacted."

    def _tech_ack(self, language: str) -> str:
        if language == "es":
            return "Nota del técnico registrada en el paquete."
        return "Technician note recorded on the packet."


def public_session(state: dict, settings: LLMSettings) -> dict:
    scenario_id = state.get("scenario_id")
    total = len(SCENARIOS[scenario_id]["steps"]) if scenario_id else 0
    current = next_step_id(state) if scenario_id and state["phase"] == "guide" else None
    return {
        "id": state["id"],
        "phase": state["phase"],
        "scenario_id": scenario_id,
        "scenario_title_en": SCENARIOS[scenario_id]["title_en"] if scenario_id else None,
        "scenario_title_es": SCENARIOS[scenario_id]["title_es"] if scenario_id else None,
        "language": state.get("language"),
        "language_confidence": state.get("language_confidence"),
        "language_path": state.get("language_path") or [],
        "reported_polarities": state.get("reported_polarities") or {},
        "error_codes": state.get("error_codes") or [],
        "devices": state.get("devices") or [],
        "phase_log": state.get("phase_log") or [],
        "steps_done": state.get("steps_done") or [],
        "steps_total": total,
        "current_step": current,
        "failures": state.get("failures") or 0,
        "technician": state.get("technician"),
        "redaction_count": state.get("redaction_count") or 0,
        "resolution": state.get("resolution"),
        "ticket_id": state.get("ticket_id"),
        "llm_mode": settings.mode,
        "provider": state.get("provider") or "deterministic",
        "created_at": state.get("created_at"),
    }


def build_graph(state: dict) -> dict:
    scenario_id = state.get("scenario_id")
    phase = state["phase"]
    checks = {item["tool"]: item for item in state.get("last_checks") or []}
    citations = state.get("citations") or []
    resolution = state.get("resolution")

    def check_node(tool: str, title_en: str, title_es: str) -> dict:
        item = checks.get(tool)
        if not item:
            status, en, es = "idle", "Not run", "Sin ejecutar"
        elif item["ok"]:
            status, en, es = "ok", item["summary_en"], item["summary_es"]
        else:
            status, en, es = "fail", item["summary_en"], item["summary_es"]
        return {
            "id": tool,
            "status": status,
            "title_en": title_en,
            "title_es": title_es,
            "detail_en": en,
            "detail_es": es,
        }

    queued = bool(state.get("world") and state["world"].get("password_reset_queued"))
    report_detail_en = SCENARIOS[scenario_id]["title_en"] if scenario_id else "Waiting for the problem"
    report_detail_es = SCENARIOS[scenario_id]["title_es"] if scenario_id else "Esperando el problema"
    entities = []
    entities.extend(state.get("error_codes") or [])
    entities.extend(state.get("devices") or [])
    polarity_bits = [f"{key}={value}" for key, value in (state.get("reported_polarities") or {}).items()]
    cite_en = citations[0]["source_label"] if citations else "No citation yet"
    cite_es = cite_en
    misses = state.get("failures") or 0
    if resolution == "verified":
        verify_status = "ok"
        verify_en = f"Passed · earlier misses {misses}"
        verify_es = f"Pasó · fallos previos {misses}"
    elif misses:
        verify_status = "fail"
        verify_en = f"Failures {misses}"
        verify_es = f"Fallos {misses}"
    elif phase == "verify":
        verify_status = "active"
        verify_en = "Checking"
        verify_es = "Comprobando"
    else:
        verify_status = "idle"
        verify_en = "Not run"
        verify_es = "Sin ejecutar"
    ticket_status = "ok" if resolution in {"verified", "escalated", "technician"} else "idle"
    ticket_en = f"{state.get('ticket_id') or 'Not opened'} · {resolution or 'open'}"
    ticket_es = f"{state.get('ticket_id') or 'Sin abrir'} · {resolution or 'abierto'}"
    nodes = [
        {
            "id": "report",
            "status": "ok" if scenario_id else "active",
            "title_en": "Report",
            "title_es": "Reporte",
            "detail_en": report_detail_en,
            "detail_es": report_detail_es,
        },
        {
            "id": "language",
            "status": "info",
            "title_en": "Language",
            "title_es": "Idioma",
            "detail_en": f"{(state.get('language') or 'en').upper()} · path {' → '.join(state.get('language_path') or [state.get('language') or 'en'])}",
            "detail_es": f"{(state.get('language') or 'en').upper()} · ruta {' → '.join(state.get('language_path') or [state.get('language') or 'en'])}",
        },
        {
            "id": "entities",
            "status": "info" if entities else "idle",
            "title_en": "Entities",
            "title_es": "Entidades",
            "detail_en": ", ".join(entities + polarity_bits) or "None yet",
            "detail_es": ", ".join(entities + polarity_bits) or "Aún ninguna",
        },
        {
            "id": "hypothesis",
            "status": "ok" if scenario_id else "idle",
            "title_en": "Hypothesis",
            "title_es": "Hipótesis",
            "detail_en": CAUSES[scenario_id]["en"] if scenario_id else "Unclassified",
            "detail_es": CAUSES[scenario_id]["es"] if scenario_id else "Sin clasificar",
        },
        check_node("check_wifi", "Wi-Fi", "Wi-Fi"),
        check_node("check_vpn", "VPN", "VPN"),
        check_node("check_dns", "DNS", "DNS"),
        check_node("check_printer", "Printer", "Impresora"),
        {
            "id": "reset_password",
            "status": "ok" if queued else "idle",
            "title_en": "Password reset",
            "title_es": "Restablecer clave",
            "detail_en": "Synthetic SSO reauth queued. No secret stored." if queued else "Not used.",
            "detail_es": "Reautenticación SSO sintética encolada. Sin secreto." if queued else "Sin usar.",
        },
        {
            "id": "kb",
            "status": "info" if citations else "idle",
            "title_en": "Citation",
            "title_es": "Cita",
            "detail_en": cite_en,
            "detail_es": cite_es,
        },
        {
            "id": "plan",
            "status": "ok" if state.get("steps_done") or resolution == "verified" else "active" if scenario_id else "idle",
            "title_en": "Plan",
            "title_es": "Plan",
            "detail_en": ", ".join(state.get("steps_done") or []) or "Safe steps only",
            "detail_es": ", ".join(state.get("steps_done") or []) or "Solo pasos seguros",
        },
        {
            "id": "verify",
            "status": verify_status,
            "title_en": "Verify",
            "title_es": "Verificar",
            "detail_en": verify_en,
            "detail_es": verify_es,
        },
        {
            "id": "ticket",
            "status": ticket_status,
            "title_en": "Ticket",
            "title_es": "Ticket",
            "detail_en": ticket_en,
            "detail_es": ticket_es,
        },
    ]
    edges = [
        ["report", "language"],
        ["language", "entities"],
        ["entities", "hypothesis"],
        ["hypothesis", "check_wifi"],
        ["hypothesis", "check_vpn"],
        ["hypothesis", "check_dns"],
        ["hypothesis", "check_printer"],
        ["hypothesis", "reset_password"],
        ["check_vpn", "kb"],
        ["check_dns", "kb"],
        ["check_printer", "kb"],
        ["kb", "plan"],
        ["plan", "verify"],
        ["verify", "ticket"],
    ]
    return {"nodes": nodes, "edges": edges, "phase": phase}


def replay_catalog() -> list[dict]:
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "scenario_id": item["scenario_id"],
            "turns": len(item["turns"]),
            "wow": bool(item.get("wow")),
            "pii": bool(item.get("pii")),
        }
        for item in REPLAYS.values()
    ]
