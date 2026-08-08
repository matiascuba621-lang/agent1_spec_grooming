"""
Jira write-back client — this is where Agent 1's output actually lands
for a human to see it on the story itself.

Writes three things back to the Jira issue once grooming completes:
  1. A comment with the score, per-dimension breakdown, and gap list
     (always — whether the story passed the gate or not).
  2. A custom field update carrying the numeric testability score, so
     it's queryable/reportable in Jira itself (dashboards, JQL filters).
  3. If the gate passed: the generated Gherkin, either as a comment
     block or as an attachment, plus a label marking the story
     DoR-ready-pending-approval.

Uses Jira Cloud REST API v3. If you're on Jira Server/Data Center or
Azure DevOps instead, the HTTP calls in _post_comment /
_update_custom_field / _add_label need to change to match that API —
the calling code in pipeline.py doesn't need to change, only this file.

Set JIRA_DRY_RUN=1 to log what would be written without making real
API calls — useful for testing the integration wiring before you have
real Jira credentials.
"""
from __future__ import annotations

import logging
import os

import requests

from models import GherkinSpec, TestabilityScore

logger = logging.getLogger("agent1.jira_client")

JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "")  # e.g. https://yourorg.atlassian.net
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_API_TOKEN = os.environ.get("JIRA_API_TOKEN", "")
JIRA_TESTABILITY_SCORE_FIELD = os.environ.get("JIRA_TESTABILITY_SCORE_FIELD", "customfield_10050")
DRY_RUN = os.environ.get("JIRA_DRY_RUN", "0") == "1"


class JiraWriteBackError(Exception):
    pass


def _auth():
    if not (JIRA_EMAIL and JIRA_API_TOKEN):
        raise JiraWriteBackError(
            "JIRA_EMAIL / JIRA_API_TOKEN not set. Set JIRA_DRY_RUN=1 to test without real credentials."
        )
    return (JIRA_EMAIL, JIRA_API_TOKEN)


def _format_score_comment(score: TestabilityScore) -> dict:
    """Jira Cloud comments use Atlassian Document Format (ADF), not plain markdown."""
    lines = [f"Testability score: {score.overall_score} / 10 (gate = {score.gate_threshold})"]
    lines.append("PASSED gate" if score.passes_gate else "BELOW gate — returned for rework")
    lines.append("")
    lines.append("Per-dimension:")
    for dim, val in score.per_dimension.items():
        lines.append(f"  \u2022 {dim}: {val:.1f}")
    if score.all_gaps:
        lines.append("")
        lines.append("Gaps identified:")
        for gap in score.all_gaps:
            lines.append(f"  \u2022 {gap}")

    text = "\n".join(lines)
    return {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "codeBlock", "attrs": {"language": "text"}, "content": [{"type": "text", "text": text}]}
            ],
        }
    }


def _post_comment(story_id: str, comment_payload: dict) -> None:
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{story_id}/comment"
    if DRY_RUN:
        logger.info("[DRY RUN] would POST comment to %s: %s", url, comment_payload)
        return
    resp = requests.post(url, json=comment_payload, auth=_auth(), timeout=10)
    if resp.status_code >= 300:
        raise JiraWriteBackError(f"story {story_id}: comment POST failed [{resp.status_code}]: {resp.text}")


def _update_custom_field(story_id: str, field_id: str, value) -> None:
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{story_id}"
    payload = {"fields": {field_id: value}}
    if DRY_RUN:
        logger.info("[DRY RUN] would PUT field update to %s: %s", url, payload)
        return
    resp = requests.put(url, json=payload, auth=_auth(), timeout=10)
    if resp.status_code >= 300:
        raise JiraWriteBackError(f"story {story_id}: field update PUT failed [{resp.status_code}]: {resp.text}")


def _add_label(story_id: str, label: str) -> None:
    url = f"{JIRA_BASE_URL}/rest/api/3/issue/{story_id}"
    payload = {"update": {"labels": [{"add": label}]}}
    if DRY_RUN:
        logger.info("[DRY RUN] would PUT label add to %s: %s", url, payload)
        return
    resp = requests.put(url, json=payload, auth=_auth(), timeout=10)
    if resp.status_code >= 300:
        raise JiraWriteBackError(f"story {story_id}: label add PUT failed [{resp.status_code}]: {resp.text}")


def write_score_and_gaps(story_id: str, score: TestabilityScore) -> None:
    """Always called, regardless of gate outcome — Section 2's 'where it
    writes back to' item 1."""
    _post_comment(story_id, _format_score_comment(score))
    _update_custom_field(story_id, JIRA_TESTABILITY_SCORE_FIELD, score.overall_score)
    logger.info("story %s: score and gaps written back to Jira", story_id)


def write_gherkin_and_mark_pending(story_id: str, gherkin: GherkinSpec) -> None:
    """Only called when the gate passed and Gherkin was generated."""
    comment_payload = {
        "body": {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": f"Generated Gherkin ({gherkin.scenario_count} scenarios) — pending UAT Lead approval:"}]},
                {"type": "codeBlock", "attrs": {"language": "gherkin"}, "content": [{"type": "text", "text": gherkin.feature_text}]},
            ],
        }
    }
    _post_comment(story_id, comment_payload)
    _add_label(story_id, "grooming-pending-approval")
    logger.info("story %s: Gherkin written back to Jira, marked pending approval", story_id)
