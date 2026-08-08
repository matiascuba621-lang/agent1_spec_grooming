"""
Data models for the Spec & Grooming Agent (Agent 1).

These are plain dataclasses, not an ORM — swap in SQLAlchemy/Pydantic
models backed by your actual datastore when you wire this to a real
Jira/ADO instance and a real Quality Insights & Governance store.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class GateDecision(str, Enum):
    BELOW_GATE = "below_gate"          # score < 8.0 -> blocked, returned to PO/BA
    PENDING_APPROVAL = "pending_approval"  # score >= 8.0 -> awaiting UAT Lead sign-off
    APPROVED = "approved"              # UAT Lead approved -> DoR-compliant
    REJECTED = "rejected"              # UAT Lead rejected despite score >= 8.0


@dataclass
class RawStory:
    """Component A input: the unmodified payload pulled from Jira/ADO."""
    story_id: str
    title: str
    description: str
    acceptance_criteria_raw: str
    epic_id: str | None
    epic_summary: str | None
    labels: list[str] = field(default_factory=list)
    component: str | None = None
    linked_openapi_spec: str | None = None  # URL or inline schema, if applicable


@dataclass
class NormalizedStory:
    """Component A output: the consistent schema every downstream component reads."""
    story_id: str
    title: str
    description: str
    acceptance_criteria: list[str]  # split into discrete, numbered AC statements
    epic_id: str | None
    epic_summary: str | None
    component: str | None
    labels: list[str]
    linked_openapi_spec: str | None
    team_prior_gap_patterns: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Six-dimension rubric
#
# IMPORTANT: these dimension names and weights are placeholders illustrating
# the shape of the model. Replace them with your organization's actual
# six-dimension Story Testability Score definition and weights before this
# is used to gate anything — the interrogation prompt, the scoring engine,
# and the audit schema all need to agree on the same six dimensions.
# ---------------------------------------------------------------------------
RUBRIC_DIMENSIONS: list[str] = [
    "independently_testable",   # each AC can be verified in isolation
    "observable_outcome",       # AC specifies an outcome, not an implementation detail
    "edge_cases_covered",       # negative paths / boundary conditions present
    "measurable_pass_fail",     # unambiguous, objective pass/fail condition
    "epic_alignment",           # story demonstrably serves the linked EPIC's intent
    "data_precondition_clarity",  # required test data / preconditions are stated
]

# Must sum to 1.0 — validated at import time below.
RUBRIC_WEIGHTS: dict[str, float] = {
    "independently_testable": 0.20,
    "observable_outcome": 0.20,
    "edge_cases_covered": 0.15,
    "measurable_pass_fail": 0.20,
    "epic_alignment": 0.10,
    "data_precondition_clarity": 0.15,
}

assert set(RUBRIC_WEIGHTS) == set(RUBRIC_DIMENSIONS), "weights must cover exactly the six dimensions"
assert abs(sum(RUBRIC_WEIGHTS.values()) - 1.0) < 1e-9, "dimension weights must sum to 1.0"

GATE_THRESHOLD = 8.0


@dataclass
class DimensionFinding:
    """One rubric dimension's score (0-10) plus the evidence that justified it."""
    dimension: str
    score: float  # 0-10, per-dimension
    rationale: str
    gaps: list[str] = field(default_factory=list)


@dataclass
class InterrogationResult:
    """Component B output: structured critique against the six-dimension rubric."""
    story_id: str
    findings: list[DimensionFinding]
    model_used: str
    raw_response_id: str | None = None


@dataclass
class TestabilityScore:
    """Component C output: the deterministic, reproducible 0-10 score."""
    story_id: str
    overall_score: float
    per_dimension: dict[str, float]
    gate_threshold: float
    passes_gate: bool
    all_gaps: list[str]
    computed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class GherkinSpec:
    """Component D output: the tagged .feature file content."""
    story_id: str
    feature_text: str
    scenario_count: int
    tags: list[str]
    model_used: str


@dataclass
class AuditRecord:
    """Every gate transition writes one of these. Immutable once written."""
    record_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    story_id: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event: str = ""                      # e.g. "scored", "gherkin_generated", "approved"
    actor: str = ""                      # "agent:spec-grooming" or a named human user ID
    decision: GateDecision | None = None
    score: float | None = None
    gaps: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)
