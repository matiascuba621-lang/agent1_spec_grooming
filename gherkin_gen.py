"""
Component D — Gherkin Generation Module.

Fires only once a story clears (or is near) the 8.0 gate — generating
Gherkin from a low-testability story just produces confident-sounding
output with no real grounding (see scoring.py's gate check, enforced by
the caller in pipeline.py, not by this module — this module trusts its
caller but validates its own output).

Generation is constrained by template (Given/When/Then per AC) and the
output is syntax-validated against Cucumber/Gherkin grammar before it's
allowed to leave this module, since malformed .feature files break
Agent 2's ingestion silently.
"""
from __future__ import annotations

import os
import re

import anthropic

from config import ANTHROPIC_BASE_URL, GHERKIN_MODEL, MAX_TOKENS_GHERKIN
from models import GherkinSpec, NormalizedStory

_client: anthropic.Anthropic | None = None


def get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(
            api_key=os.environ["ANTHROPIC_API_KEY"],
            base_url=ANTHROPIC_BASE_URL,
        )
    return _client


_SYSTEM_PROMPT = """You generate Cucumber-compatible Gherkin (.feature) specifications \
from an approved user story. Follow these rules exactly:

1. Output ONLY the .feature file content. No markdown fences, no commentary, no preamble.
2. Start with `Feature:` using the story title.
3. Tag the Feature line with @story-{story_id} and @component-{component} on the line above it.
4. Generate at least one Scenario per acceptance criterion — never merge two ACs into one \
   scenario, and never invent a scenario that doesn't trace back to a specific AC.
5. Each Scenario must use Given/When/Then (And/But permitted as continuations).
6. Given establishes preconditions and test data state. When describes the action taken. \
   Then describes an observable, checkable outcome — never an internal implementation detail.
7. Do not invent acceptance criteria or business rules not present in the input. If an AC is \
   ambiguous, write the scenario as literally as the AC allows rather than guessing intent.
8. Use plain, declarative language — no code syntax inside step text.
"""


def _build_user_message(story: NormalizedStory) -> str:
    ac_block = "\n".join(f"{i+1}. {ac}" for i, ac in enumerate(story.acceptance_criteria))
    return f"""STORY ID: {story.story_id}
COMPONENT: {story.component or "unspecified"}
TITLE: {story.title}

DESCRIPTION:
{story.description or "(none)"}

ACCEPTANCE CRITERIA:
{ac_block}

Generate the .feature file now."""


# --- Syntax validation -------------------------------------------------------

_FEATURE_LINE = re.compile(r"^\s*Feature:\s*.+$", re.MULTILINE)
_SCENARIO_LINE = re.compile(r"^\s*Scenario:\s*.+$", re.MULTILINE)
_STEP_LINE = re.compile(r"^\s*(Given|When|Then|And|But)\b", re.MULTILINE)
_TAG_LINE = re.compile(r"^\s*@story-\S+.*@component-\S+|^\s*@component-\S+.*@story-\S+", re.MULTILINE)


class GherkinValidationError(Exception):
    pass


def validate_gherkin(feature_text: str, expected_scenario_min: int) -> None:
    """Raises GherkinValidationError on any structural problem. Called before
    the spec is allowed to commit — a malformed .feature file should never
    reach Agent 2's ingestion layer."""
    if not _FEATURE_LINE.search(feature_text):
        raise GherkinValidationError("no 'Feature:' line found")

    if not _TAG_LINE.search(feature_text):
        raise GherkinValidationError("missing required @story-<id> / @component-<name> tags")

    scenario_count = len(_SCENARIO_LINE.findall(feature_text))
    if scenario_count < expected_scenario_min:
        raise GherkinValidationError(
            f"expected at least {expected_scenario_min} scenarios (one per AC), found {scenario_count}"
        )

    if not _STEP_LINE.search(feature_text):
        raise GherkinValidationError("no Given/When/Then steps found")

    # Every Scenario block should contain at least one Then (a checkable outcome).
    scenarios = re.split(r"(?=^\s*Scenario:)", feature_text, flags=re.MULTILINE)
    for block in scenarios:
        if block.strip().startswith("Scenario:") and not re.search(r"^\s*Then\b", block, re.MULTILINE):
            raise GherkinValidationError("a Scenario is missing a 'Then' outcome step")


def generate_gherkin(story: NormalizedStory) -> GherkinSpec:
    """Component D entry point. Raises GherkinValidationError if the model's
    output fails structural validation — callers should treat that as a
    retry-or-escalate signal, not silently commit a broken spec."""
    client = get_client()

    response = client.messages.create(
        model=GHERKIN_MODEL,
        max_tokens=MAX_TOKENS_GHERKIN,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_user_message(story)}],
    )

    text_block = next((b for b in response.content if b.type == "text"), None)
    if text_block is None:
        raise RuntimeError(f"story {story.story_id}: model returned no text content")

    feature_text = text_block.text.strip()
    # Defensive: strip markdown fences if the model added them despite instructions.
    feature_text = re.sub(r"^```(?:gherkin|cucumber)?\n?", "", feature_text)
    feature_text = re.sub(r"\n?```$", "", feature_text).strip()

    validate_gherkin(feature_text, expected_scenario_min=len(story.acceptance_criteria))

    scenario_count = len(_SCENARIO_LINE.findall(feature_text))
    tags = re.findall(r"@[\w-]+", feature_text)

    return GherkinSpec(
        story_id=story.story_id,
        feature_text=feature_text,
        scenario_count=scenario_count,
        tags=tags,
        model_used=GHERKIN_MODEL,
    )
