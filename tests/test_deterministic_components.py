"""
Unit tests covering everything that doesn't require an API key:
ingestion (Component A), scoring (Component C), Gherkin validation
(part of Component D), and the gate state machine.

Run with:  pytest tests/ -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from gate import ApprovalRequiresNamedHuman, approve_story, evaluate_gate, reject_story
from gherkin_gen import GherkinValidationError, validate_gherkin
from ingestion import normalize_story, split_acceptance_criteria
from models import (
    RUBRIC_DIMENSIONS,
    DimensionFinding,
    GateDecision,
    GherkinSpec,
    InterrogationResult,
    RawStory,
)
from scoring import compute_testability_score

# --- Ingestion (Component A) -------------------------------------------------

def test_normalize_story_splits_numbered_ac():
    raw = RawStory(
        story_id="ABC-1",
        title="Login with MFA",
        description="User logs in with a second factor.",
        acceptance_criteria_raw="1. User enters valid credentials\n2. User is prompted for OTP\n3. Invalid OTP shows an error",
        epic_id="EPIC-1",
        epic_summary="Account security",
    )
    story = normalize_story(raw)
    assert len(story.acceptance_criteria) == 3
    assert "OTP" in story.acceptance_criteria[1]


def test_normalize_story_rejects_missing_title():
    raw = RawStory(story_id="ABC-2", title="", description="", acceptance_criteria_raw="1. Something", epic_id=None, epic_summary=None)
    with pytest.raises(ValueError):
        normalize_story(raw)


def test_normalize_story_rejects_empty_ac():
    raw = RawStory(story_id="ABC-3", title="Some story", description="", acceptance_criteria_raw="   ", epic_id=None, epic_summary=None)
    with pytest.raises(ValueError):
        normalize_story(raw)


def test_split_ac_falls_back_to_single_item_when_no_delimiter():
    items = split_acceptance_criteria("Just one unstructured requirement with no list markers at all.")
    assert len(items) == 1


# --- Scoring (Component C) ---------------------------------------------------

def _fake_interrogation(scores: dict[str, float]) -> InterrogationResult:
    findings = [
        DimensionFinding(dimension=dim, score=scores[dim], rationale="test", gaps=[] if scores[dim] >= 8 else ["gap"])
        for dim in RUBRIC_DIMENSIONS
    ]
    return InterrogationResult(story_id="ABC-1", findings=findings, model_used="test-model")


def test_scoring_all_tens_passes_gate():
    result = _fake_interrogation({dim: 10.0 for dim in RUBRIC_DIMENSIONS})
    score = compute_testability_score(result)
    assert score.overall_score == 10.0
    assert score.passes_gate is True
    assert score.all_gaps == []


def test_scoring_all_fives_fails_gate():
    result = _fake_interrogation({dim: 5.0 for dim in RUBRIC_DIMENSIONS})
    score = compute_testability_score(result)
    assert score.overall_score == 5.0
    assert score.passes_gate is False
    assert len(score.all_gaps) == len(RUBRIC_DIMENSIONS)


def test_scoring_is_reproducible_from_stored_dimensions():
    """An auditor should be able to recompute the score without re-running the LLM."""
    result = _fake_interrogation({
        "independently_testable": 9.0, "observable_outcome": 7.0, "edge_cases_covered": 6.0,
        "measurable_pass_fail": 8.0, "epic_alignment": 10.0, "data_precondition_clarity": 7.5,
    })
    score = compute_testability_score(result)
    recomputed = sum(score.per_dimension[d] * w for d, w in
                      __import__("models").RUBRIC_WEIGHTS.items())
    assert abs(score.overall_score - round(recomputed, 2)) < 1e-9


def test_scoring_raises_on_missing_dimension():
    findings = [DimensionFinding(dimension="independently_testable", score=9.0, rationale="x", gaps=[])]
    result = InterrogationResult(story_id="ABC-1", findings=findings, model_used="test-model")
    with pytest.raises(ValueError):
        compute_testability_score(result)


# --- Gherkin validation (Component D) ----------------------------------------

VALID_FEATURE = """@story-ABC-1 @component-login
Feature: Login with MFA

  Scenario: Valid credentials and valid OTP
    Given a user with valid credentials
    When the user enters a valid OTP
    Then the user is logged in

  Scenario: Invalid OTP shows an error
    Given a user with valid credentials
    When the user enters an invalid OTP
    Then an error message is displayed
"""


def test_valid_gherkin_passes_validation():
    validate_gherkin(VALID_FEATURE, expected_scenario_min=2)  # should not raise


def test_gherkin_missing_tags_fails():
    broken = VALID_FEATURE.replace("@story-ABC-1 @component-login\n", "")
    with pytest.raises(GherkinValidationError):
        validate_gherkin(broken, expected_scenario_min=2)


def test_gherkin_too_few_scenarios_fails():
    with pytest.raises(GherkinValidationError):
        validate_gherkin(VALID_FEATURE, expected_scenario_min=5)


def test_gherkin_missing_then_fails():
    broken = VALID_FEATURE.replace("    Then the user is logged in\n", "")
    with pytest.raises(GherkinValidationError):
        validate_gherkin(broken, expected_scenario_min=2)


# --- Gate state machine -------------------------------------------------------

def test_evaluate_gate_below_threshold_needs_no_gherkin():
    result = _fake_interrogation({dim: 4.0 for dim in RUBRIC_DIMENSIONS})
    score = compute_testability_score(result)
    outcome = evaluate_gate(score, gherkin=None)
    assert outcome.decision == GateDecision.BELOW_GATE


def test_evaluate_gate_above_threshold_requires_gherkin():
    result = _fake_interrogation({dim: 9.0 for dim in RUBRIC_DIMENSIONS})
    score = compute_testability_score(result)
    with pytest.raises(ValueError):
        evaluate_gate(score, gherkin=None)  # scored high but nothing generated — should never happen


def test_evaluate_gate_above_threshold_pending_approval():
    result = _fake_interrogation({dim: 9.0 for dim in RUBRIC_DIMENSIONS})
    score = compute_testability_score(result)
    gherkin = GherkinSpec(story_id="ABC-1", feature_text=VALID_FEATURE, scenario_count=2,
                           tags=["@story-ABC-1", "@component-login"], model_used="test-model")
    outcome = evaluate_gate(score, gherkin)
    assert outcome.decision == GateDecision.PENDING_APPROVAL


def test_approve_story_requires_named_human():
    with pytest.raises(ApprovalRequiresNamedHuman):
        approve_story("ABC-1", score=9.0, approver_id="")


def test_approve_story_with_named_human_succeeds():
    record = approve_story("ABC-1", score=9.0, approver_id="jdoe", notes="looks good")
    assert record.decision == GateDecision.APPROVED
    assert record.actor == "jdoe"


def test_reject_story_requires_reason():
    with pytest.raises(ValueError):
        reject_story("ABC-1", score=9.0, approver_id="jdoe", reason="")
