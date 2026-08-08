"""
Verification report — the artifact a human (you, or the UAT Lead) reads
to decide whether to trust a given grooming outcome, rather than reading
raw JSON or trusting the score number alone.

This is deliberately NOT the same thing as the audit log (audit.py) or
the Jira write-back (jira_client.py). The audit log is the immutable
system-of-record; the Jira comment is what lives on the ticket; this
report is a standalone, shareable artifact — save it, attach it to a
review request, paste it in Slack, whatever your team's review workflow
actually is.
"""
from __future__ import annotations

from pathlib import Path

from gate import GroomingOutcome
from models import GateDecision

REPORTS_DIR = Path(__file__).parent / "reports"


def _dimension_bar(score: float, width: int = 20) -> str:
    filled = round((score / 10) * width)
    return "\u2588" * filled + "\u2591" * (width - filled)


def render_report(outcome: GroomingOutcome) -> str:
    score = outcome.score
    lines: list[str] = []

    lines.append(f"# Grooming Report — {score.story_id}")
    lines.append("")
    lines.append(f"**Decision:** `{outcome.decision.value}`")
    lines.append(f"**Score:** {score.overall_score} / 10  (gate = {score.gate_threshold})")
    lines.append("")

    lines.append("## Per-dimension breakdown")
    lines.append("")
    lines.append("| Dimension | Score | |")
    lines.append("|---|---|---|")
    for dim, val in score.per_dimension.items():
        lines.append(f"| {dim} | {val:.1f} | `{_dimension_bar(val)}` |")
    lines.append("")

    if score.all_gaps:
        lines.append("## Gaps identified")
        lines.append("")
        for gap in score.all_gaps:
            lines.append(f"- {gap}")
        lines.append("")
    else:
        lines.append("## Gaps identified")
        lines.append("")
        lines.append("_None — every dimension met._")
        lines.append("")

    if outcome.gherkin:
        lines.append(f"## Generated Gherkin ({outcome.gherkin.scenario_count} scenarios)")
        lines.append("")
        lines.append("```gherkin")
        lines.append(outcome.gherkin.feature_text.rstrip())
        lines.append("```")
        lines.append("")
        lines.append(f"**Tags:** {', '.join(outcome.gherkin.tags)}")
        lines.append("")
    else:
        lines.append("## Generated Gherkin")
        lines.append("")
        lines.append("_Not generated — story is below the gate._")
        lines.append("")

    lines.append("## Next action")
    lines.append("")
    if outcome.decision == GateDecision.BELOW_GATE:
        lines.append(
            "This story is **below the 8.0 gate** and was returned to the product owner/BA. "
            "No human review is needed at this stage — address the gaps above and re-submit for grooming."
        )
    elif outcome.decision == GateDecision.PENDING_APPROVAL:
        lines.append(
            "This story **passed the gate** and Gherkin has been generated. "
            "**Action required:** the named UAT Lead must review the Gherkin above against the original "
            "acceptance criteria and either approve or reject it — call `gate.approve_story()` / "
            "`gate.reject_story()` with a real `approver_id`, or use `python cli.py review` to do this "
            "interactively."
        )

    return "\n".join(lines)


def save_report(outcome: GroomingOutcome) -> Path:
    REPORTS_DIR.mkdir(exist_ok=True)
    path = REPORTS_DIR / f"{outcome.story_id}.md"
    path.write_text(render_report(outcome), encoding="utf-8")
    return path
