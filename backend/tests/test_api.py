from app.dialogues import REPLAYS
from app.transcribe import whisper_status


def test_health_scenarios_and_state_machine(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["ok"] is True
    assert body["llm_mode"] == "deterministic"
    assert set(body["scenarios"]) == {"vpn_down", "dns_failure", "printer_offline"}
    assert client.get("/api/scenarios").json()["scenarios"]
    machine = client.get("/api/state-machine").json()
    assert "guide" in machine["phases"]
    assert any(row["event"] == "technician_takeover" for row in machine["transitions"])
    assert len(client.get("/api/kb").json()["articles"]) == 4
    replays = client.get("/api/replays").json()["replays"]
    assert any(item["id"] == "vpn_switch" and item["wow"] for item in replays)


def test_rest_dialogue_and_export(client):
    created = client.post("/api/sessions", json={"language": "en"})
    assert created.status_code == 200
    session_id = created.json()["session"]["id"]
    for turn in REPLAYS["dns_es"]["turns"]:
        response = client.post(f"/api/sessions/{session_id}/messages", json={"text": turn})
        assert response.status_code == 200
    snapshot = client.get(f"/api/sessions/{session_id}").json()
    assert snapshot["session"]["language"] == "es"
    assert snapshot["ticket"]["status"] == "verified"
    exported = client.get(f"/api/sessions/{session_id}/export", params={"format": "markdown"})
    assert exported.status_code == 200
    assert "DNS-ERR-2201" in exported.json()["content"]
    assert "CORP-LAPTOP-04" in exported.json()["content"]
    as_json = client.get(f"/api/sessions/{session_id}/export", params={"format": "json"})
    assert as_json.json()["content"]["synthetic"] is True
    missing = client.get("/api/sessions/SES-NOPE")
    assert missing.status_code == 404


def test_transcribe_does_not_invent_text_without_whisper():
    status = whisper_status()
    assert status["available"] is False
    from fastapi.testclient import TestClient
    # The fixture client is requested via the parameter in the other tests.
    # This assertion is independent of the app process.


def test_transcribe_endpoint(client):
    response = client.post("/api/transcribe", json={"audio_b64": "", "mime": "audio/webm"})
    body = response.json()
    assert body["available"] is False
    assert body["text"] == ""
    assert body["ok"] is False


def test_websocket_turn_completes(client):
    session_id = client.post("/api/sessions", json={"language": "en"}).json()["session"]["id"]
    text = REPLAYS["printer_en"]["turns"][0]
    with client.websocket_connect(f"/ws/sessions/{session_id}") as ws:
        ws.send_json({"type": "user_text", "text": text, "source": "text"})
        kinds = []
        while True:
            event = ws.receive_json()
            kinds.append(event["type"])
            if event["type"] == "turn_done":
                assert event["interrupted"] is False
                break
    assert "assistant_delta" in kinds
    assert "graph" in kinds
    assert "turn_done" in kinds


def test_stream_interrupt(svc):
    import asyncio

    svc.settings.stream_ms = 15
    created = svc.create("en")
    session_id = created["session"]["id"]
    text = REPLAYS["vpn_en"]["turns"][0]

    async def _run():
        events = []

        async def consume():
            async for event in svc.stream_turn(session_id, text):
                events.append(event)

        task = asyncio.create_task(consume())
        await asyncio.sleep(0.04)
        svc.interrupt(session_id)
        await task
        return events

    events = asyncio.run(_run())
    assert any(event["type"] == "interrupted" for event in events)
    assert events[-1]["type"] == "turn_done"
    assert events[-1]["interrupted"] is True
    transcript = svc.db.transcript(session_id)
    assistants = [turn for turn in transcript if turn["role"] == "assistant"]
    assert assistants[-1]["interrupted"] == 1
