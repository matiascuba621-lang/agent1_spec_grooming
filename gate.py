"""
DoR Gate and Human Gate Logic.

This is the governance-critical part of the build (Section 4 of the
implementation guide). The state machine:

  1. score < 8.0  -> BELOW_GATE. Story blocked from sprint entry, gap list
     posted back to the story, ticket returns to product owner/BA.
     No human UAT review required — there's nothing ready to review yet.

  2. score >= 8.0 -> Gherkin generated -> PENDING_APPROVAL, routed to the
     named UAT Lead.

  3. UAT Lead approves -> APPROVED. Story is DoR-compliant, enters the
     sprint, and the approved spec becomes Agent 2's source of truth.

  4. UAT Lead rejects -> REJECTED, with a reason, routed back for rework.

CRITICAL DESIGN CONSTRAINT: nothing in this module can transition a story
to APPROVED except approve_story(), and approve_story() requires a named
human approver_id. There is no auto-advance path — enforced below by
raising if approver_id is empty, and by the fact that generate-and-score
never calls approve_story() themselves.
"""
from __future__ import annotations

from dataclasses import dataclass

from audit import write_record
from models import AuditRecord, GateDecision, GherkinSpec, TestabilityScore


class ApprovalRequiresNamedHuman(Exception):
    pass


@dataclass
class GroomingOutcome:
    story_id: str
    decision: GateDecision
    score: TestabilityScore
    gherkin: GherkinSpec | None  # None when below gate


def evaluate_gate(score: TestabilityScore, gherkin: GherkinSpec | None) -> GroomingOutcome:
    """
    Called once Components B/C (and D, if the gate was cleared) have run.
    Writes the initial audit record and returns the outcome — this function
    never itself grants final approval; it only determines whether the
    story is now eligible for human review.
    """
    if score.passes_gate:
        if gherkin is None:
            raise ValueError(
                f"story {score.story_id}: score passes gate but no Gherkin was generated — "
                "pipeline.py should always generate before evaluating the gate"
            )
        decision = GateDecision.PENDING_APPROVAL
    else:
        decision = GateDecision.BELOW_GATE

    write_record(
        AuditRecord(
            story_id=score.story_id,
            event="scored",
            actor="agent:spec-grooming",
            decision=decision,
            score=score.overall_score,
            gaps=score.all_gaps,
            details={"per_dimension": score.per_dimension, "gate_threshold": score.gate_threshold},
        )
    )

    if decision == GateDecision.PENDING_APPROVAL:
        write_record(
            AuditRecord(
                story_id=score.story_id,
                event="gherkin_generated",
                actor="agent:spec-grooming",
                decision=decision,
                score=score.overall_score,
                details={"scenario_count": gherkin.scenario_count, "tags": gherkin.tags},
            )
        )

    return GroomingOutcome(story_id=score.story_id, decision=decision, score=score, gherkin=gherkin)


def approve_story(story_id: str, score: float, approver_id: str, notes: str = "") -> AuditRecord:
    """
    The ONLY function in this codebase that can mark a story DoR-compliant.
    Must be called from the UAT Lead's approval action in the UI — never
    from anywhere in the automated pipeline.
    """
    if not approver_id or not approver_id.strip():
        raise ApprovalRequiresNamedHuman(
            f"story {story_id}: approval requires a named human approver_id — "
            "no default, no service account, no auto-advance"
        )

    record = AuditRecord(
        story_id=story_id,
        event="approved",
        actor=approver_id,
        decision=GateDecision.APPROVED,
        score=score,
        details={"notes": notes},
    )
    write_record(record)
    return record


def reject_story(story_id: str, score: float, approver_id: str, reason: str) -> AuditRecord:
    if not approver_id or not approver_id.strip():
        raise ApprovalRequiresNamedHuman(f"story {story_id}: rejection also requires a named human approver_id")
    if not reason or not reason.strip():
        raise ValueError(f"story {story_id}: rejection requires a reason — routed back to the story as feedback")

    record = AuditRecord(
        story_id=story_id,
        event="rejected",
        actor=approver_id,
        decision=GateDecision.REJECTED,
        score=score,
        details={"reason": reason},
    )
    write_record(record)
    return record
