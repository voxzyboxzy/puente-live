import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_matches_committed_eval():
    data = json.loads((ROOT / "eval" / "results" / "latest.json").read_text(encoding="utf-8"))
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert f"{data['task_resolution']['passed']}/{data['task_resolution']['total']}" in readme
    assert str(data["latency_ms"]["mean"]) in readme
    assert str(data["latency_ms"]["p50"]) in readme
    assert str(data["latency_ms"]["p95"]) in readme
    assert str(data["latency_ms"]["max"]) in readme
    assert f"{data['unsafe_advice']['unsafe']}/{data['unsafe_advice']['total']}" in readme
    assert (
        f"{data['error_code_preservation_detail']['passed']}/{data['error_code_preservation_detail']['total']}"
        in readme
    )
    assert (
        f"{data['negation_preservation_detail']['passed']}/{data['negation_preservation_detail']['total']}"
        in readme
    )
    assert data["transcription_error"]["status"] == "N/A"
    assert data["transcription_error"]["wer"] is None
    assert "N/A" in readme
    for name in (
        "01-intake.png",
        "02-diagnose-en.png",
        "03-switch-es.png",
        "04-verified-ticket.png",
    ):
        path = ROOT / "docs" / "screenshots" / name
        assert path.stat().st_size > 10_000
        assert name in readme
