"""Pluggable phrasing. The state machine does not depend on a model.

deterministic: templates only.
ollama: optional rephrase. If the process is down, the reply drops a fact,
or the reply becomes unsafe, the template is kept.
"""

from __future__ import annotations

import os

import httpx

from .safety import response_is_unsafe


class LLMSettings:
    def __init__(self) -> None:
        self.mode = os.getenv("PUENTE_LLM", "deterministic").strip().lower()
        self.ollama_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2")
        self.ollama_timeout = float(os.getenv("OLLAMA_TIMEOUT", "4"))
        self.stream_ms = int(os.getenv("PUENTE_STREAM_MS", "0"))


def rephrase(text: str, language: str, settings: LLMSettings) -> tuple[str, str]:
    """Return (text, provider_used)."""
    if settings.mode != "ollama":
        return text, "deterministic"
    language_name = "Spanish" if language == "es" else "English"
    prompt = (
        f"Rephrase the troubleshooting message in {language_name}. "
        "Do not add steps. Do not remove error codes, device names, citations, "
        "or the Incident facts / Datos del incidente line. "
        "Do not recommend disabling security controls. Return only the message.\n\n"
        f"{text}"
    )
    try:
        response = httpx.post(
            f"{settings.ollama_url}/api/chat",
            json={
                "model": settings.ollama_model,
                "stream": False,
                "messages": [
                    {"role": "system", "content": "You edit wording only."},
                    {"role": "user", "content": prompt},
                ],
            },
            timeout=settings.ollama_timeout,
        )
        response.raise_for_status()
        content = response.json().get("message", {}).get("content", "").strip()
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return text, "deterministic"
    if not content or response_is_unsafe(content):
        return text, "deterministic"
    if "Incident facts:" not in content and "Datos del incidente:" not in content:
        return text, "deterministic"
    return content, "ollama"
