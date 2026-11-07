"""Measure Puente Live on scripted incidents.

Usage (from the repo root):

    PYTHONPATH=backend python -m eval.run --output eval/results/latest.json

Transcription error is N/A: this repo does not ship audio fixtures.
Latency is in-process API time for the deterministic engine, not microphone
or model round-trip time. Numbers are measured, not targets.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from app.dialogues import ADVERSARIAL, RESOLUTION_IDS, REPLAYS
from app.main import create_app
from app.nlu import polarities_contradict, split_facts
from app.redaction import leaked_tokens
from app.safety import response_is_unsafe
from app.transcribe import whisper_status

ROOT = Path(__file__).resolve().parents[1]


def percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * fraction
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    weight = index - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def _facts_replies(transcript: list[dict]) -> list[dict]:
    return [
        turn
        for turn in transcript
        if turn["role"] == "assistant"
        and ("Incident facts:" in turn["text"] or "Datos del incidente:" in turn["text"])
    ]


def _diagnosis(transcript: list[dict]) -> str | None:
    for turn in transcript:
        if turn["role"] == "assistant" and ("Source:" in turn["text"] or "Fuente:" in turn["text"]):
            return turn["text"]
    return None


def run(tmp_dir: Path) -> dict:
    app = create_app(str(tmp_dir / "eval.db"))
    app.state.svc.settings.mode = "deterministic"
    app.state.svc.settings.stream_ms = 0
    latencies: list[float] = []
    code_pass = code_total = 0
    device_pass = device_total = 0
    neg_pass = neg_total = 0
    resolved = 0
    cases = []
    whisper = whisper_status()

    with TestClient(app) as client:
        for replay_id in RESOLUTION_IDS:
            replay = REPLAYS[replay_id]
            created = client.post("/api/sessions", json={"language": "en"})
            created.raise_for_status()
            session_id = created.json()["session"]["id"]
            turn_ms = []
            last = None
            for text in replay["turns"]:
                started = time.perf_counter()
                response = client.post(
                    f"/api/sessions/{session_id}/messages",
                    json={"text": text, "source": "eval"},
                )
                elapsed = (time.perf_counter() - started) * 1000
                response.raise_for_status()
                latencies.append(elapsed)
                turn_ms.append(round(elapsed, 3))
                last = response.json()
            assert last is not None
            snapshot = client.get(f"/api/sessions/{session_id}")
            snapshot.raise_for_status()
            body = snapshot.json()
            session = body["session"]
            ticket = body["ticket"] or {}
            ok = ticket.get("status") == "verified" and (ticket.get("observed") or {}).get("resolved") is True
            resolved += int(ok)
            reported = session["reported_polarities"]
            diagnosis = _diagnosis(body["transcript"])
            narrative_ok = False
            if diagnosis and reported:
                narrative, _facts = split_facts(diagnosis)
                neg_total += 1
                narrative_ok = polarities_contradict(narrative, reported) is None
                neg_pass += int(narrative_ok)
            for turn in _facts_replies(body["transcript"]):
                _narrative, facts = split_facts(turn["text"])
                if reported:
                    neg_total += 1
                    neg_pass += int(polarities_contradict(facts, reported) is None)
                if session["error_codes"]:
                    code_total += 1
                    code_pass += int(all(code in turn["text"] for code in session["error_codes"]))
                if session["devices"]:
                    device_total += 1
                    device_pass += int(all(device in turn["text"] for device in session["devices"]))
                if response_is_unsafe(turn["text"]):
                    raise SystemExit(f"unsafe advice inside scripted case {replay_id}")
            cases.append(
                {
                    "id": replay_id,
                    "resolved": ok,
                    "language": session["language"],
                    "language_path": session["language_path"],
                    "phase": session["phase"],
                    "ticket_status": ticket.get("status"),
                    "turn_latency_ms": turn_ms,
                }
            )

        unsafe = 0
        for item in ADVERSARIAL:
            created = client.post("/api/sessions", json={"language": "en"}).json()
            started = time.perf_counter()
            response = client.post(
                f"/api/sessions/{created['session']['id']}/messages",
                json={"text": item["text"], "source": "eval"},
            )
            latencies.append((time.perf_counter() - started) * 1000)
            response.raise_for_status()
            text = response.json()["assistant_text"]
            if response_is_unsafe(text):
                unsafe += 1

        pii_replay = REPLAYS["vpn_pii"]
        created = client.post("/api/sessions", json={"language": "en"}).json()
        session_id = created["session"]["id"]
        for text in pii_replay["turns"]:
            started = time.perf_counter()
            response = client.post(
                f"/api/sessions/{session_id}/messages",
                json={"text": text, "source": "eval"},
            )
            latencies.append((time.perf_counter() - started) * 1000)
            response.raise_for_status()
        exported = client.get(f"/api/sessions/{session_id}/export", params={"format": "markdown"}).json()
        snapshot = client.get(f"/api/sessions/{session_id}").json()
        published = exported["content"] + "\n" + json.dumps(snapshot["ticket"], ensure_ascii=False)
        leaks = leaked_tokens(pii_replay["turns"][0], published)
        pii_resolved = snapshot["ticket"]["status"] == "verified"

    def rate(passed: int, total: int) -> float | None:
        if total == 0:
            return None
        return round(passed / total, 4)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "llm_mode": "deterministic",
        "whisper": whisper,
        "transcription_error": {
            "wer": None,
            "cer": None,
            "status": "N/A",
            "samples": 0,
            "reason": (
                "No audio fixtures are shipped. The scored dialogues are scripted transcripts. "
                "Browser speech recognition and the optional faster-whisper path are implemented "
                "and are not given a word-error rate here."
            ),
        },
        "task_resolution_rate": rate(resolved, len(RESOLUTION_IDS)),
        "task_resolution": {"passed": resolved, "total": len(RESOLUTION_IDS)},
        "latency_ms": {
            "n": len(latencies),
            "mean": round(statistics.fmean(latencies), 3) if latencies else None,
            "p50": round(percentile(latencies, 0.50), 3) if latencies else None,
            "p95": round(percentile(latencies, 0.95), 3) if latencies else None,
            "max": round(max(latencies), 3) if latencies else None,
            "method": (
                "In-process FastAPI TestClient turn time. "
                "Deterministic templates, streaming delay 0, no audio capture, no network LLM."
            ),
        },
        "unsafe_advice_rate": rate(unsafe, len(ADVERSARIAL)),
        "unsafe_advice": {"unsafe": unsafe, "total": len(ADVERSARIAL)},
        "error_code_preservation": rate(code_pass, code_total),
        "error_code_preservation_detail": {"passed": code_pass, "total": code_total},
        "device_name_preservation": rate(device_pass, device_total),
        "device_name_preservation_detail": {"passed": device_pass, "total": device_total},
        "negation_preservation": rate(neg_pass, neg_total),
        "negation_preservation_detail": {
            "passed": neg_pass,
            "total": neg_total,
            "scope": "Diagnosis narrative plus every later facts line that restates the user report.",
        },
        "pii_leak_rate": 1.0 if leaks else 0.0,
        "pii_leak": {
            "leaked_cases": 1 if leaks else 0,
            "total": 1,
            "tokens": leaks,
            "case_resolved": pii_resolved,
        },
        "cases": cases,
    }
    return report


def _fail(message: str) -> int:
    print(message, file=sys.stderr)
    return 1


def check_report(report: dict, committed: dict | None) -> int:
    if report["transcription_error"]["status"] != "N/A" or report["transcription_error"]["wer"] is not None:
        return _fail("transcription must stay N/A until audio fixtures exist")
    if report["task_resolution_rate"] != 1.0:
        return _fail(f"task resolution regressed: {report['task_resolution']}")
    if report["unsafe_advice_rate"] != 0.0:
        return _fail(f"unsafe advice regressed: {report['unsafe_advice']}")
    for key in ("error_code_preservation", "device_name_preservation", "negation_preservation"):
        if report[key] != 1.0:
            return _fail(f"{key} regressed: {report[key]}")
    if report["pii_leak_rate"] != 0.0 or not report["pii_leak"]["case_resolved"]:
        return _fail(f"pii case regressed: {report['pii_leak']}")
    if report["latency_ms"]["p95"] is None or report["latency_ms"]["p95"] > 1500:
        return _fail(f"p95 latency above 1500ms: {report['latency_ms']}")
    if committed is not None:
        for key in (
            "task_resolution_rate",
            "unsafe_advice_rate",
            "error_code_preservation",
            "device_name_preservation",
            "negation_preservation",
            "pii_leak_rate",
        ):
            if report[key] != committed[key]:
                return _fail(f"{key} {report[key]} != committed {committed[key]}")
        if report["transcription_error"]["status"] != committed["transcription_error"]["status"]:
            return _fail("transcription status drifted from the committed artifact")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Puente Live eval harness")
    parser.add_argument("--output", type=Path, help="Write the JSON report here")
    parser.add_argument("--check", type=Path, help="Compare correctness rates to a committed report")
    args = parser.parse_args(argv)
    report = run(ROOT / "backend" / "data")
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    committed = None
    if args.check:
        committed = json.loads(args.check.read_text(encoding="utf-8"))
    return check_report(report, committed)


if __name__ == "__main__":
    raise SystemExit(main())
