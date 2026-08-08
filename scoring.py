"""
Component C — Scoring Engine.

Deterministic. No LLM call here — this takes Component B's structured
findings and computes the weighted 0-10 score. An auditor should be able
to recompute this score from the stored per-dimension values without
re-running the model, which is why this is plain arithmetic, not a
second model call asking "so, does this pass?"
"""
from __future__ import annotations

from models import GATE_THRESHOLD, RUBRIC_WEIGHTS, InterrogationResult, TestabilityScore


def compute_testability_score(result: InterrogationResult) -> TestabilityScore:
    per_dimension = {f.dimension: f.score for f in result.findings}

    missing = set(RUBRIC_WEIGHTS) - set(per_dimension)
    if missing:
        raise ValueError(f"story {result.story_id}: cannot score, missing dimensions {missing}")

    overall = sum(per_dimension[dim] * weight for dim, weight in RUBRIC_WEIGHTS.items())
    overall = round(overall, 2)

    all_gaps = [gap for f in result.findings for gap in f.gaps]

    return TestabilityScore(
        story_id=result.story_id,
        overall_score=overall,
        per_dimension=per_dimension,
        gate_threshold=GATE_THRESHOLD,
        passes_gate=overall >= GATE_THRESHOLD,
        all_gaps=all_gaps,
    )
