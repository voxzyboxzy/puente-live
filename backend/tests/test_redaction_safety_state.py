import pytest

from app.redaction import leaked_tokens, redact
from app.safety import response_is_unsafe, user_requests_unsafe
from app.state_machine import StateError, transition


def test_redaction_keeps_error_code_and_device():
    raw = (
        "My name is Alex Rivera. Email alex.rivera@example.com phone 555-013-2048. "
        "SSN 123-45-6789 card 4111 1111 1111 1111. The password is Summer2024! "
        "VPN-ERR-4012 on ThinkPad-T14."
    )
    cleaned, findings = redact(raw)
    kinds = {item["kind"] for item in findings}
    assert {"email", "phone", "ssn", "card", "password", "name"} <= kinds
    assert "VPN-ERR-4012" in cleaned
    assert "ThinkPad-T14" in cleaned
    assert leaked_tokens(raw, cleaned) == []
    assert "password reset" in redact("Please start a password reset for the VPN.")[0]


def test_negated_warning_is_safe_and_bare_advice_is_not():
    warning = (
        "Do not disable the firewall. Do not turn off antivirus. "
        "Do not open all ports. Do not format a disk."
    )
    assert response_is_unsafe(warning) is False
    assert response_is_unsafe("Turn off the firewall so the VPN works.") is True
    assert response_is_unsafe("Desactiva el firewall ahora.") is True
    assert user_requests_unsafe("Just disable the firewall so the VPN works.") == "disable_firewall"
    assert user_requests_unsafe("Dame la contraseña de administrador.") == "reveal_password"
    assert user_requests_unsafe("Do not disable the firewall.") is None


def test_state_machine_paths_and_illegal_edge():
    phase = "intake"
    for event in ("problem_detected", "checks_done", "plan_delivered", "step_reported", "verify_pass"):
        phase = transition(phase, event)
    assert phase == "resolved"
    phase = transition(phase, "handoff_requested")
    assert phase == "handoff"
    phase = transition(phase, "technician_takeover")
    assert phase == "technician"
    with pytest.raises(StateError):
        transition("intake", "verify_pass")
