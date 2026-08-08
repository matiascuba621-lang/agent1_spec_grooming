"""
Pipeline orchestrator — wires Components A -> B -> C -> D and the gate
together. This is the "four coordinated services, not one giant prompt"
seam described in Section 1 of the implementation guide: each function
below is independently testable and independently replaceable.

In production this would be triggered by the event-driven webhook
described in Section 2 (new story enters "Ready for Grooming") rather
than called directly — see webhook_service.py for that entry point.

Every run produces THREE outputs, per Section 2's "where it writes back
to": the audit trail (always, via gate.evaluate_gate), a human-readable
verification report (always, via report.save_report), and a Jira
write-back (score/gaps always, Gherkin additionally if the gate passed)
when write_to_jira=True. write_to_jira defaults to False so running this
locally or in tests never touches a real Jira instance by accident.
"""
from __future__ import annotations

import logging

import jira_client
import report
from gate import GroomingOutcome, evaluate_gate
from gherkin_gen import GherkinValidationError, generate_gherkin
from ingestion import normalize_story
from interrogation import interrogate_story
from models import GherkinSpec, NormalizedStory, RawStory
from scoring import compute_testability_score

logger = logging.getLogger("agent1.pipeline")


def groom_story(
    raw: RawStory,
    team_prior_gap_patterns: list[str] | None = None,
    write_to_jira: bool = False,
) -> GroomingOutcome:
    """
    Runs the full A -> B -> C -> D pipeline for a single story and returns
    the outcome. Does not itself approve anything — see gate.approve_story
    for the human-only approval action.
    """
    logger.info("story %s: ingesting", raw.story_id)
    story: NormalizedStory = normalize_story(raw, team_prior_gap_patterns)

    logger.info("story %s: interrogating against six-dimension rubric", story.story_id)
    interrogation = interrogate_story(story)

    logger.info("story %s: scoring", story.story_id)
    score = compute_testability_score(interrogation)
    logger.info(
        "story %s: score=%.2f gate=%.1f passes=%s",
        story.story_id, score.overall_score, score.gate_threshold, score.passes_gate,
    )

    gherkin: GherkinSpec | None = None
    if score.passes_gate:
        logger.info("story %s: generating Gherkin", story.story_id)
        try:
            gherkin = generate_gherkin(story)
        except GherkinValidationError as e:
            # A story that scored >= 8.0 but produced unparseable Gherkin is a
            # signal worth surfacing loudly, not silently downgrading the gate
            # decision. Re-raise so the caller (and monitoring) sees it clearly.
            logger.error("story %s: Gherkin generation failed validation: %s", story.story_id, e)
            raise

    outcome = evaluate_gate(score, gherkin)
    logger.info("story %s: gate decision=%s", story.story_id, outcome.decision.value)

    # Output 1: human-readable verification report — always produced.
    report_path = report.save_report(outcome)
    logger.info("story %s: verification report written to %s", story.story_id, report_path)

    # Output 2: Jira write-back — score/gaps always, Gherkin only if generated.
    if write_to_jira:
        jira_client.write_score_and_gaps(story.story_id, score)
        if gherkin:
            jira_client.write_gherkin_and_mark_pending(story.story_id, gherkin)

    # Output 3: the audit trail — already written by evaluate_gate() above.

    return outcome
