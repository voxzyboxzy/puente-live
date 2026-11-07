"""Explicit troubleshooting state machine.

Interruptions do not change phase. They cancel an in-flight spoken reply.
The legal transitions are the only way the session moves.
"""

from __future__ import annotations

PHASES = (
    "intake",
    "diagnose",
    "plan",
    "guide",
    "verify",
    "resolved",
    "handoff",
    "technician",
)

# (phase, event) -> next phase
TRANSITIONS: dict[tuple[str, str], str] = {
    ("intake", "problem_detected"): "diagnose",
    ("intake", "clarify"): "intake",
    ("intake", "unsafe_refused"): "intake",
    ("diagnose", "checks_done"): "plan",
    ("plan", "plan_delivered"): "guide",
    ("guide", "step_reported"): "verify",
    ("guide", "restate"): "guide",
    ("guide", "unsafe_refused"): "guide",
    ("guide", "handoff_requested"): "handoff",
    ("verify", "verify_pass"): "resolved",
    ("verify", "verify_fail"): "guide",
    ("verify", "max_failures"): "handoff",
    ("verify", "handoff_requested"): "handoff",
    ("resolved", "handoff_requested"): "handoff",
    ("resolved", "restate"): "resolved",
    ("resolved", "unsafe_refused"): "resolved",
    ("handoff", "restate"): "handoff",
    ("handoff", "unsafe_refused"): "handoff",
    ("intake", "technician_takeover"): "technician",
    ("diagnose", "technician_takeover"): "technician",
    ("plan", "technician_takeover"): "technician",
    ("guide", "technician_takeover"): "technician",
    ("verify", "technician_takeover"): "technician",
    ("resolved", "technician_takeover"): "technician",
    ("handoff", "technician_takeover"): "technician",
    ("technician", "technician_message"): "technician",
    ("technician", "restate"): "technician",
    ("technician", "unsafe_refused"): "technician",
}


class StateError(Exception):
    pass


def transition(phase: str, event: str) -> str:
    try:
        return TRANSITIONS[(phase, event)]
    except KeyError as exc:
        raise StateError(f"illegal transition: {phase} -{event}->") from exc


def describe() -> dict:
    rows = [
        {"from": src, "event": event, "to": dest}
        for (src, event), dest in TRANSITIONS.items()
    ]
    return {
        "phases": list(PHASES),
        "transitions": rows,
        "notes": [
            "Interrupt cancels streaming output and does not change phase.",
            "diagnose and plan are passed through in the same turn as the first classified report.",
            "verify is an internal turn phase between guide and either guide, resolved, or handoff.",
            "technician takeover is legal from every phase except technician itself.",
        ],
    }
