"""Pattern-based PII redaction for transcripts and tickets.

Error codes, device names, and negations are not PII and must pass through.
This is a deterministic filter, not a full DLP product.
"""

from __future__ import annotations

import re

EMAIL = re.compile(r"\b[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}\b", re.I)
PHONE = re.compile(
    r"(?<!\w)(?:\+?1[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\w)"
)
SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CARD = re.compile(r"\b(?:\d{4}[\s-]?){3}\d{4}\b")
PASSWORD = re.compile(
    r"(?i)\b(password|passcode|contraseña|contrasena|clave)\b\s*(is|es|:)\s*(\S{4,})"
)
NAME = re.compile(
    r"(?i)\b(my name is|i am|i'm|me llamo|mi nombre es|soy)\s+"
    r"([A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+(?:\s+[A-ZÁÉÍÓÚÜÑ][a-záéíóúüñ]+){0,2})"
)


def redact(text: str) -> tuple[str, list[dict]]:
    """Return redacted text and a list of {kind, placeholder} findings."""
    if not text:
        return "", []
    findings: list[dict] = []

    def swap(pattern: re.Pattern[str], placeholder: str, kind: str, source: str) -> str:
        def _repl(_match: re.Match[str]) -> str:
            findings.append({"kind": kind, "placeholder": placeholder})
            return placeholder

        return pattern.sub(_repl, source)

    cleaned = swap(EMAIL, "[EMAIL]", "email", text)
    cleaned = swap(SSN, "[SSN]", "ssn", cleaned)
    cleaned = swap(PHONE, "[PHONE]", "phone", cleaned)
    cleaned = swap(CARD, "[CARD]", "card", cleaned)

    def _password(match: re.Match[str]) -> str:
        findings.append({"kind": "password", "placeholder": "[SECRET]"})
        return f"{match.group(1)} {match.group(2)} [SECRET]"

    cleaned = PASSWORD.sub(_password, cleaned)

    def _name(match: re.Match[str]) -> str:
        findings.append({"kind": "name", "placeholder": "[NAME]"})
        return f"{match.group(1)} [NAME]"

    cleaned = NAME.sub(_name, cleaned)
    return cleaned, findings


def leaked_tokens(original: str, published: str) -> list[str]:
    """Return raw secrets from original text that still appear in published text."""
    leaks: list[str] = []
    for match in EMAIL.finditer(original):
        if match.group(0) in published:
            leaks.append(match.group(0))
    for match in PHONE.finditer(original):
        if match.group(0) in published:
            leaks.append(match.group(0))
    for match in SSN.finditer(original):
        if match.group(0) in published:
            leaks.append(match.group(0))
    for match in CARD.finditer(original):
        if match.group(0) in published:
            leaks.append(match.group(0))
    for match in PASSWORD.finditer(original):
        secret = match.group(3)
        if secret and secret in published:
            leaks.append(secret)
    for match in NAME.finditer(original):
        person = match.group(2)
        if person and person in published:
            leaks.append(person)
    return leaks
