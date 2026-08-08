"""
Tests for the three new pieces: report.py, jira_client.py (dry-run mode,
no real API calls), and audit.py's pending-list derivation.

Run with:  pytest tests/test_output_and_review.py -v
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Must be set before jira_client is imported, since DRY_RUN is read at import time.
os.environ["JIRA_DRY_RUN"] = "1"

import pytest

import audit
import jira_client
import report
from gate import GroomingOutcome, approve_story, evaluate_gate
from models import GherkinSpec, TestabilityScore


def _make_outcome(story_id: str, passes: bool) -> GroomingOutcome:
    score = TestabilityScore(
        story_id=story_id,
        overall_score=9.0 if passes else 5.0,
        per_dimension={"independently_testable": 9.0 if passes else 5.0},
        gate_threshold=8.0,
        passes_gate=passes,
        all_gaps=[] if passes else ["AC #1 is not independently testable"],
    )
    gherkin = None
    if passes:
        gherkin = GherkinSpec(
            story_id=story_id,
            feature_text="@story-" + story_id + " @component-auth\nFeature: Test\n\n  Scenario: A\n    Given x\n    When y\n    Then z\n",
            scenario_count=1,
            tags=["@story-" + story_id, "@component-auth"],
            model_used="test-model",
        )
    return evaluate_gate(score, gherkin)


# --- report.py ------------------------------------------------------------

def test_report_below_gate_has_no_gherkin_section_content():
    outcome = _make_outcome("RPT-1", passes=False)
    text = report.render_report(outcome)
    assert "RPT-1" in text
    assert "below_gate" in text
    assert "Not generated" in text
    assert "AC #1 is not independently testable" in text


def test_report_pending_approval_includes_gherkin_and_next_action():
    outcome = _make_outcome("RPT-2", passes=True)
    text = report.render_report(outcome)
    assert "pending_approval" in text
    assert "Scenario: A" in text
    assert "Action required" in text


def test_save_report_writes_file():
    outcome = _make_outcome("RPT-3", passes=True)
    path = report.save_report(outcome)
    assert path.exists()
    assert path.name == "RPT-3.md"
    assert "RPT-3" in path.read_text(encoding="utf-8")


# --- jira_client.py (dry run) -----------------------------------------------

def test_jira_write_score_dry_run_does_not_raise(caplog):
    score = TestabilityScore(
        story_id="JIRA-1", overall_score=5.0, per_dimension={"independently_testable": 5.0},
        gate_threshold=8.0, passes_gate=False, all_gaps=["some gap"],
    )
    # Should not raise even with no real credentials set, because DRY_RUN=1.
    jira_client.write_score_and_gaps("JIRA-1", score)


def test_jira_write_gherkin_dry_run_does_not_raise():
    gherkin = GherkinSpec(
        story_id="JIRA-2", feature_text="Feature: X\n", scenario_count=1,
        tags=["@story-JIRA-2"], model_used="test-model",
    )
    jira_client.write_gherkin_and_mark_pending("JIRA-2", gherkin)


def test_jira_client_raises_without_credentials_when_not_dry_run(monkeypatch):
    monkeypatch.setattr(jira_client, "DRY_RUN", False)
    monkeypatch.setattr(jira_client, "JIRA_EMAIL", "")
    monkeypatch.setattr(jira_client, "JIRA_API_TOKEN", "")
    with pytest.raises(jira_client.JiraWriteBackError):
        jira_client._auth()


# --- audit.py pending-list derivation ---------------------------------------

def test_list_pending_includes_gherkin_generated_without_later_decision():
    _make_outcome("PEND-1", passes=True)  # writes 'scored' + 'gherkin_generated'
    pending = audit.list_pending_story_ids()
    assert "PEND-1" in pending


def test_list_pending_excludes_approved_story():
    outcome = _make_outcome("PEND-2", passes=True)
    approve_story("PEND-2", score=outcome.score.overall_score, approver_id="jdoe")
    pending = audit.list_pending_story_ids()
    assert "PEND-2" not in pending


def test_list_pending_excludes_below_gate_story():
    _make_outcome("PEND-3", passes=False)  # only 'scored' event, no gherkin_generated
    pending = audit.list_pending_story_ids()
    assert "PEND-3" not in pending


def test_get_latest_score_returns_most_recent():
    _make_outcome("PEND-4", passes=True)
    score = audit.get_latest_score("PEND-4")
    assert score == 9.0
