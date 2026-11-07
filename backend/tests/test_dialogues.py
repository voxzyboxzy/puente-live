import pytest

from app.dialogues import ADVERSARIAL, RESOLUTION_IDS, REPLAYS
from app.nlu import polarities_contradict, split_facts
from app.redaction import leaked_tokens
from app.safety import response_is_unsafe


def _run(svc, replay_id: str):
    created = svc.create("en")
    session_id = created["session"]["id"]
    last = created
    for turn in REPLAYS[replay_id]["turns"]:
        last = svc.handle_turn(session_id, turn)
    snapshot = svc.get(session_id)
    return last, snapshot


def _diagnosis(transcript: list[dict]) -> str:
    for turn in transcript:
        if turn["role"] == "assistant" and ("Source:" in turn["text"] or "Fuente:" in turn["text"]):
            return turn["text"]
    raise AssertionError("diagnosis reply missing")


@pytest.mark.parametrize("replay_id", RESOLUTION_IDS)
def test_scripted_resolution_preserves_facts(svc, replay_id):
    last, snapshot = _run(svc, replay_id)
    session = snapshot["session"]
    ticket = snapshot["ticket"]
    assert ticket["status"] == "verified"
    assert ticket["observed"]["resolved"] is True
    assert session["scenario_id"] == REPLAYS[replay_id]["scenario_id"]
    assert session["phase"] in {"resolved", "handoff"}
    diagnosis = _diagnosis(snapshot["transcript"])
    narrative, _facts = split_facts(diagnosis)
    assert polarities_contradict(narrative, session["reported_polarities"]) is None
    for turn in snapshot["transcript"]:
        if turn["role"] != "assistant":
            continue
        if "Incident facts:" not in turn["text"] and "Datos del incidente:" not in turn["text"]:
            continue
        _narrative, facts = split_facts(turn["text"])
        assert polarities_contradict(facts, session["reported_polarities"]) is None
        for code in session["error_codes"]:
            assert code in turn["text"]
        for device in session["devices"]:
            assert device in turn["text"]
        assert response_is_unsafe(turn["text"]) is False
    assert any(item["id"] == {
        "vpn_down": "NET-VPN-014",
        "dns_failure": "NET-DNS-008",
        "printer_offline": "END-PRT-021",
    }[session["scenario_id"]] for item in snapshot["citations"])
    assert snapshot["citations"][0]["overlap"] > 0
    assert last["graph"]["nodes"]


def test_vpn_switch_changes_language_and_clears_tunnel(svc):
    _last, snapshot = _run(svc, "vpn_switch")
    assert snapshot["session"]["language"] == "es"
    assert snapshot["session"]["language_path"] == ["en", "es"]
    nodes = {node["id"]: node for node in snapshot["graph"]["nodes"]}
    assert nodes["check_vpn"]["status"] == "ok"
    assert nodes["check_wifi"]["status"] == "ok"
    assert nodes["reset_password"]["status"] == "ok"
    assert "NET-VPN-014" in snapshot["citations"][0]["source_label"] or any(
        item["id"] == "NET-VPN-014" for item in snapshot["citations"]
    )


def test_vpn_check_fails_before_the_second_step(svc):
    created = svc.create("en")
    session_id = created["session"]["id"]
    first = svc.handle_turn(session_id, REPLAYS["vpn_en"]["turns"][0])
    nodes = {node["id"]: node for node in first["graph"]["nodes"]}
    assert nodes["check_vpn"]["status"] == "fail"
    assert nodes["check_wifi"]["status"] == "ok"
    second = svc.handle_turn(session_id, REPLAYS["vpn_en"]["turns"][1])
    nodes = {node["id"]: node for node in second["graph"]["nodes"]}
    assert nodes["check_vpn"]["status"] == "fail"
    assert second["session"]["phase"] == "guide"
    assert second["session"]["failures"] == 1


def test_pii_dialogue_exports_without_secrets(svc):
    raw = REPLAYS["vpn_pii"]["turns"][0]
    _last, snapshot = _run(svc, "vpn_pii")
    published = snapshot["ticket"]["markdown"] + "\n" + "\n".join(
        turn["text"] for turn in snapshot["transcript"]
    )
    assert leaked_tokens(raw, published) == []
    assert "VPN-ERR-4012" in published
    assert "ThinkPad-T14" in published
    assert snapshot["session"]["redaction_count"] >= 4


def test_adversarial_requests_get_safe_refusals(svc):
    created = svc.create("en")
    session_id = created["session"]["id"]
    for item in ADVERSARIAL:
        result = svc.handle_turn(session_id, item["text"])
        assert result["safety"]["risks"] == []
        assert response_is_unsafe(result["assistant_text"]) is False
        assert result["session"]["scenario_id"] is None


def test_technician_takeover_stops_guidance(svc):
    created = svc.create("en")
    session_id = created["session"]["id"]
    svc.handle_turn(session_id, REPLAYS["vpn_en"]["turns"][0])
    taken = svc.takeover(session_id, "tech-synthetic-01", "My name is Sam Ortega. Looking now.")
    assert taken["session"]["phase"] == "technician"
    assert "Sam Ortega" not in taken["assistant_text"]
    follow = svc.handle_turn(session_id, "Can you disable the firewall now?")
    assert follow["session"]["phase"] == "technician"
    assert "disable the firewall" not in follow["assistant_text"].lower() or "will not add steps" in follow["assistant_text"].lower()
    note = svc.technician_message(session_id, "Queue checked. Email me at tech.synthetic@example.com later.")
    published = note["ticket"]["markdown"]
    assert "tech.synthetic@example.com" not in published
    assert "[EMAIL]" in published


def test_three_unverified_claims_escalate(svc):
    created = svc.create("en")
    session_id = created["session"]["id"]
    svc.handle_turn(session_id, REPLAYS["vpn_en"]["turns"][0])
    last = None
    for _ in range(3):
        last = svc.handle_turn(session_id, "It works now.")
    assert last["session"]["resolution"] == "escalated"
    assert last["session"]["phase"] == "handoff"
    assert last["ticket"]["status"] == "escalated"


def test_ollama_down_falls_back_to_template(tmp_path):
    from app.db import Database
    from app.engine import SessionService
    from app.llm import LLMSettings

    settings = LLMSettings()
    settings.mode = "ollama"
    settings.ollama_url = "http://127.0.0.1:9"
    settings.ollama_timeout = 0.3
    database = Database(str(tmp_path / "ollama.db"))
    database.migrate()
    local = SessionService(database, settings)
    created = local.create("en")
    result = local.handle_turn(created["session"]["id"], REPLAYS["vpn_en"]["turns"][0])
    assert result["provider"] == "deterministic"
    assert "VPN-ERR-4012" in result["assistant_text"]
    assert "ThinkPad-T14" in result["assistant_text"]
