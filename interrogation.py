"""
Component B — Interrogation Module.

This is where the LLM does real work. Structured critique against a fixed
rubric, not open-ended chat: for each of the six dimensions, Claude must
return a 0-10 score, a rationale, and (where the score is imperfect) a
list of concrete gaps.

Output is forced into a tool call (tool_choice) so the response is always
valid, parseable JSON matching RUBRIC_DIMENSIONS — never free text.
"""
from __future__ import annotations

import os

import anthropic

from config import ANTHROPIC_BASE_URL, INTERROGATION_MODEL, MAX_TOKENS_INTERROGATION
from models import (
    RUBRIC_DIMENSIONS,
    DimensionFinding,
    InterrogationResult,
    NormalizedStory,
)

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            base_url=ANTHROPIC_BASE_URL,  # None -> SDK default (public API)
        )
    return _client


_RUBRIC_TOOL = {
    "name": "record_testability_findings",
    "description": (
        "Record the structured testability critique of a user story's acceptance "
        "criteria against all six rubric dimensions. Every dimension must be scored, "
        "even if the score is low."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "minItems": len(RUBRIC_DIMENSIONS),
                "maxItems": len(RUBRIC_DIMENSIONS),
                "items": {
                    "type": "object",
                    "properties": {
                        "dimension": {
                            "type": "string",
                            "enum": RUBRIC_DIMENSIONS,
                        },
                        "score": {
                            "type": "number",
                            "description": "0-10, may be fractional (e.g. 7.5)",
                        },
                        "rationale": {
                            "type": "string",
                            "description": "1-2 sentences citing specific text from the AC",
                        },
                        "gaps": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Concrete, actionable gaps. Empty if the dimension is fully met.",
                        },
                    },
                    "required": ["dimension", "score", "rationale", "gaps"],
                },
            },
        },
        "required": ["findings"],
    },
}

_SYSTEM_PROMPT = """You are a testability reviewer for a UAT grooming pipeline. \
You critique user stories against a fixed six-dimension rubric before they are \
allowed into a sprint. You are deliberately strict: a story with vague or \
untestable acceptance criteria should score low, even if it reads well as prose.

Score each dimension independently on a 0-10 scale:

- independently_testable: can each AC be verified in isolation, without needing \
  another AC to already be true?
- observable_outcome: does the AC specify an observable result (what the user/system \
  sees), not an implementation detail (how it's built)?
- edge_cases_covered: are negative paths, boundary conditions, and error states \
  addressed, not just the happy path?
- measurable_pass_fail: is there an unambiguous, objective condition a tester could \
  check without further interpretation?
- epic_alignment: does the story clearly and directly serve the linked EPIC's stated \
  intent, not just loosely relate to it?
- data_precondition_clarity: are the test data states / preconditions required for \
  each AC actually stated, not assumed?

For any dimension scoring below 8, list the specific, concrete gaps — phrased so a \
product owner could act on them directly (e.g. "AC #2 does not specify the expected \
error message when the account balance is insufficient" rather than "needs more detail").

Call record_testability_findings with all six dimensions scored. Do not skip any \
dimension, and do not inflate scores to be encouraging — an inflated score here \
produces Gherkin specs later that nobody can actually execute."""


def _build_user_message(story: NormalizedStory) -> str:
    ac_block = "\n".join(f"{i+1}. {ac}" for i, ac in enumerate(story.acceptance_criteria))
    prior_gaps = (
        "\n".join(f"- {g}" for g in story.team_prior_gap_patterns)
        if story.team_prior_gap_patterns
        else "(none on file)"
    )
    return f"""STORY: {story.title}

DESCRIPTION:
{story.description or "(none provided)"}

LINKED EPIC: {story.epic_summary or "(not linked)"}

ACCEPTANCE CRITERIA:
{ac_block or "(none — this alone should fail independently_testable and measurable_pass_fail)"}

THIS TEAM'S RECURRING GAP PATTERNS (calibrate scrutiny accordingly):
{prior_gaps}

Critique this story against all six rubric dimensions."""


def interrogate_story(story: NormalizedStory) -> InterrogationResult:
    """Component B entry point. Raises on a malformed/unparseable model response
    rather than silently returning a partial or default-scored result."""
    client = get_client()

    response = client.messages.create(
        model=INTERROGATION_MODEL,
        max_tokens=MAX_TOKENS_INTERROGATION,
        system=_SYSTEM_PROMPT,
        tools=[_RUBRIC_TOOL],
        tool_choice={"type": "tool", "name": "record_testability_findings"},
        messages=[{"role": "user", "content": _build_user_message(story)}],
    )

    tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use_block is None:
        raise RuntimeError(f"story {story.story_id}: model returned no tool_use block")

    payload = tool_use_block.input
    findings_raw = payload.get("findings", [])

    seen_dims = {f["dimension"] for f in findings_raw}
    missing = set(RUBRIC_DIMENSIONS) - seen_dims
    if missing:
        raise RuntimeError(f"story {story.story_id}: model omitted dimensions {missing}")

    findings = [
        DimensionFinding(
            dimension=f["dimension"],
            score=float(f["score"]),
            rationale=f["rationale"],
            gaps=list(f.get("gaps", [])),
        )
        for f in findings_raw
    ]

    return InterrogationResult(
        story_id=story.story_id,
        findings=findings,
        model_used=INTERROGATION_MODEL,
        raw_response_id=response.id,
    )
