"""JSON and Markdown incident packets. Transcripts are already redacted."""

from __future__ import annotations

from .scenarios import SCENARIOS


def render_markdown(body: dict) -> str:
    scenario = body.get("scenario_id") or "unclassified"
    meta = SCENARIOS.get(scenario, {})
    title = meta.get("title_en") or "Unclassified synthetic incident"
    lines = [
        f"# {body['ticket_id']} · {title}",
        "",
        f"- Status: `{body['status']}`",
        f"- Session: `{body['session_id']}`",
        f"- Scenario: `{scenario}`",
        f"- Languages: {', '.join(body.get('language_path') or []) or 'n/a'}",
        f"- Error codes: {', '.join(body.get('error_codes') or []) or 'none'}",
        f"- Devices: {', '.join(body.get('devices') or []) or 'none'}",
        f"- Reported polarities: `{body.get('reported_polarities') or {}}`",
        f"- Steps completed: {', '.join(body.get('steps_completed') or []) or 'none'}",
        f"- Redactions: {body.get('redaction_count', 0)}",
        f"- Synthetic: yes",
        "",
        body.get("disclaimer", ""),
        "",
        "## Checks",
        "",
    ]
    for check in body.get("checks") or []:
        flag = "pass" if check.get("ok") else "fail"
        lines.append(f"- `{check.get('tool')}` **{flag}** — {check.get('summary_en')}")
    lines.extend(["", "## Citations", ""])
    citations = body.get("citations") or []
    if not citations:
        lines.append("- none")
    for cite in citations:
        lines.append(
            f"- **{cite.get('id')}** {cite.get('title')} (overlap {cite.get('overlap')})"
        )
    technician = body.get("technician")
    lines.extend(["", "## Technician", ""])
    if technician:
        lines.append(f"- Id: `{technician.get('tech_id')}`")
        lines.append(f"- Note: {technician.get('note') or ''}")
    else:
        lines.append("- No takeover recorded.")
    lines.extend(["", "## Redacted transcript", ""])
    for turn in body.get("transcript") or []:
        role = turn.get("role", "unknown")
        text = turn.get("text", "")
        lang = turn.get("language") or ""
        lines.append(f"**{role}** ({lang})")
        lines.append("")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
