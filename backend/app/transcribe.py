"""Optional faster-whisper transcription.

When the package is not installed, this module reports that plainly and
does not invent a transcript. Browser speech recognition and text input
cover the demo without a model download.
"""

from __future__ import annotations

import base64
import os
import tempfile


def whisper_status() -> dict:
    forced = os.getenv("PUENTE_WHISPER", "auto").strip().lower()
    if forced in {"0", "off", "false"}:
        return {"available": False, "reason": "PUENTE_WHISPER is off"}
    try:
        import faster_whisper  # type: ignore
    except ImportError:
        return {
            "available": False,
            "reason": "faster-whisper is not installed",
            "install": "pip install -r backend/requirements-optional.txt",
        }
    return {"available": True, "module": getattr(faster_whisper, "__name__", "faster_whisper")}


def transcribe_bytes(payload: bytes, suffix: str = ".webm") -> dict:
    status = whisper_status()
    if not status.get("available"):
        return {"ok": False, "text": "", **status}
    if not payload:
        return {"ok": False, "text": "", "available": True, "reason": "empty audio"}
    model_name = os.getenv("PUENTE_WHISPER_MODEL", "base")
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return {"ok": False, "text": "", "available": False, "reason": "faster-whisper is not installed"}
    try:
        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=True) as handle:
            handle.write(payload)
            handle.flush()
            segments, _info = model.transcribe(handle.name, vad_filter=True)
            text = " ".join(segment.text.strip() for segment in segments).strip()
    except Exception as exc:  # model download or decode failure
        return {"ok": False, "text": "", "available": True, "reason": str(exc)}
    return {"ok": bool(text), "text": text, "available": True, "reason": None if text else "no speech detected"}


def transcribe_base64(audio_b64: str, mime: str = "audio/webm") -> dict:
    try:
        payload = base64.b64decode(audio_b64 or "", validate=False)
    except Exception:
        return {"ok": False, "text": "", "available": whisper_status()["available"], "reason": "invalid base64"}
    suffix = ".wav" if "wav" in (mime or "") else ".webm"
    return transcribe_bytes(payload, suffix=suffix)
