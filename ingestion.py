"""
Component A — Ingestion & Normalization Layer.

Deterministic, no LLM calls. Pulls a story from the source system (Jira/ADO),
strips formatting noise, and normalizes into the consistent schema every
downstream component reads.

This module is intentionally boring: nothing upstream should depend on
model behavior for basic parsing.
"""
from __future__ import annotations

import re

from models import NormalizedStory, RawStory


def strip_formatting_noise(text: str) -> str:
    """Remove markup that Jira/ADO rich-text fields commonly inject."""
    if not text:
        return ""
    text = re.sub(r"\{code[^}]*\}", "", text)          # Jira code-block macros
    text = re.sub(r"\{[a-zA-Z:]+\}", "", text)          # other Jira macros e.g. {panel}
    text = re.sub(r"<[^>]+>", "", text)                 # stray HTML from ADO rich text
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_acceptance_criteria(raw_ac: str) -> list[str]:
    """
    Split a raw AC blob into discrete statements.

    Handles the common authoring patterns: numbered lists, bullet lists,
    and "Given/When/Then" prose already loosely structured by the author.
    Falls back to treating the whole blob as a single AC if no delimiter
    is found — that's a signal, not a bug: an ungapped AC blob is exactly
    the kind of gap the interrogation module (Component B) should flag.
    """
    cleaned = strip_formatting_noise(raw_ac)
    if not cleaned:
        return []

    # Try common list delimiters in order of specificity.
    numbered = re.split(r"\n\s*\d+[\.\)]\s+", "\n" + cleaned)
    bulleted = re.split(r"\n\s*[-*•]\s+", "\n" + cleaned)

    candidates = [numbered, bulleted]
    best = max(candidates, key=len)
    items = [item.strip() for item in best if item.strip()]

    return items if len(items) > 1 else [cleaned]


def normalize_story(raw: RawStory, team_prior_gap_patterns: list[str] | None = None) -> NormalizedStory:
    """
    Component A entry point.

    Raises ValueError on stories missing the minimum fields needed for
    grooming — reject early and loudly rather than passing a half-formed
    story into the interrogation module.
    """
    if not raw.title or not raw.title.strip():
        raise ValueError(f"story {raw.story_id}: missing title")
    if not raw.acceptance_criteria_raw or not raw.acceptance_criteria_raw.strip():
        raise ValueError(f"story {raw.story_id}: missing acceptance criteria — cannot groom an empty AC field")

    return NormalizedStory(
        story_id=raw.story_id,
        title=raw.title.strip(),
        description=strip_formatting_noise(raw.description),
        acceptance_criteria=split_acceptance_criteria(raw.acceptance_criteria_raw),
        epic_id=raw.epic_id,
        epic_summary=raw.epic_summary,
        component=raw.component,
        labels=list(raw.labels),
        linked_openapi_spec=raw.linked_openapi_spec,
        team_prior_gap_patterns=team_prior_gap_patterns or [],
    )
