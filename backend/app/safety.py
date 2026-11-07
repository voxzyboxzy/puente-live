"""Unsafe-request detection and unsafe-advice scanning.

Negated warnings ("Do not disable the firewall") are safe.
The deterministic engine is written to refuse unsafe requests and to
keep the warning form negated so this scanner stays at a zero rate.
"""

from __future__ import annotations

import re

_UNSAFE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "disable_firewall",
        re.compile(r"(?i)\b(disable|turn off|apag\w*|desactiv\w*)\b.{0,40}\bfirewall\b"),
    ),
    (
        "disable_antivirus",
        re.compile(r"(?i)\b(disable|turn off|apag\w*|desactiv\w*)\b.{0,40}\b(antivirus|defender)\b"),
    ),
    (
        "open_ports",
        re.compile(r"(?i)\b(open|abr\w*)\b.{0,40}\b(all ports|todos los puertos)\b"),
    ),
    (
        "disable_mfa",
        re.compile(r"(?i)\b(disable|turn off|apag\w*|desactiv\w*)\b.{0,30}\bmfa\b"),
    ),
    (
        "format_disk",
        re.compile(r"(?i)\b(format\w*|formate\w*)\b.{0,30}\b(disk|disco|drive)\b"),
    ),
    (
        "reveal_password",
        re.compile(
            r"(?i)\b(the password is|admin password is|la contraseña es|"
            r"la contrasena es|contraseña de administrador es)\s+\S+"
        ),
    ),
]

_ASK: list[tuple[str, re.Pattern[str]]] = [
    (
        "disable_firewall",
        re.compile(r"(?i)\b(disable|turn off|apag\w*|desactiv\w*)\b.{0,50}\bfirewall\b"),
    ),
    (
        "disable_antivirus",
        re.compile(r"(?i)\b(disable|turn off|apag\w*|desactiv\w*)\b.{0,50}\b(antivirus|defender)\b"),
    ),
    (
        "open_ports",
        re.compile(r"(?i)\b(open|abr\w*)\b.{0,40}\b(all ports|todos los puertos)\b"),
    ),
    (
        "disable_mfa",
        re.compile(r"(?i)\b(disable|turn off|apag\w*|desactiv\w*)\b.{0,30}\bmfa\b"),
    ),
    (
        "format_disk",
        re.compile(r"(?i)\b(format\w*|formate\w*)\b.{0,30}\b(disk|disco|drive)\b"),
    ),
    (
        "reveal_password",
        re.compile(
            r"(?i)\b(tell me|give me|what is|what's|dame|dime|cu[aá]l es|necesito)\b"
            r".{0,50}\b(password|contraseña|contrasena|clave de administrador|admin password)\b"
        ),
    ),
]


def _same_sentence_prefix(text: str, start: int) -> str:
    window = text[max(0, start - 48) : start]
    parts = re.split(r"[.!?]", window)
    return parts[-1]


def _is_negated(prefix: str) -> bool:
    tokens = re.findall(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ']+", prefix.lower())
    tail = tokens[-4:]
    joined = " ".join(tail)
    if re.search(r"\b(do not|don't|dont|never|nunca)\b", joined):
        return True
    if tail and tail[-1] in {"no", "not"}:
        return True
    return False


def response_risks(text: str) -> list[str]:
    """Return risk codes for advice that recommends an unsafe action."""
    found: list[str] = []
    for code, pattern in _UNSAFE_PATTERNS:
        for match in pattern.finditer(text or ""):
            if _is_negated(_same_sentence_prefix(text, match.start())):
                continue
            if code not in found:
                found.append(code)
    return found


def response_is_unsafe(text: str) -> bool:
    return bool(response_risks(text))


def user_requests_unsafe(text: str) -> str | None:
    for code, pattern in _ASK:
        match = pattern.search(text or "")
        if not match:
            continue
        if _is_negated(_same_sentence_prefix(text, match.start())):
            continue
        return code
    return None
