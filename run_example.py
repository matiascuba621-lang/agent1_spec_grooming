"""
Runnable demo of the full A -> B -> C -> D -> gate pipeline against two
stories: one deliberately weak (should fail the 8.0 gate, no Gherkin
generated) and one well-specified (should pass and produce a .feature
file). Requires a real ANTHROPIC_API_KEY in the environment — this makes
live calls to the Claude API.

    export ANTHROPIC_API_KEY="sk-ant-..."
    # optionally, to route through your governed gateway instead:
    # export ANTHROPIC_BASE_URL="https://llm-gateway.internal.example/anthropic"
    python run_example.py
"""
import os
import sys

from gate import approve_story
from models import RawStory
from pipeline import groom_story

WEAK_STORY = RawStory(
    story_id="DEMO-001",
    title="Improve login",
    description="Make login better for users.",
    acceptance_criteria_raw="1. Login should work well\n2. Users should be happy",
    epic_id="EPIC-9",
    epic_summary="Account security improvements",
)

STRONG_STORY = RawStory(
    story_id="DEMO-002",
    title="Lock account after repeated failed MFA attempts",
    description=(
        "To reduce brute-force risk against the OTP step, the account should "
        "temporarily lock after 5 consecutive failed OTP attempts within a "
        "10-minute window."
    ),
    acceptance_criteria_raw=(
        "1. Given a user has entered a valid password, when they enter an incorrect OTP "
        "5 times within 10 minutes, then the account is locked for 15 minutes and a "
        "lockout notification email is sent to the account's registered address.\n"
        "2. Given an account is locked, when the user attempts to log in with correct "
        "credentials and a correct OTP, then the login is rejected with the message "
        "'Account temporarily locked. Try again in 15 minutes.'\n"
        "3. Given an account was locked and the 15-minute window has elapsed, when the "
        "user logs in with valid credentials and a valid OTP, then the login succeeds "
        "and the failed-attempt counter resets to zero."
    ),
    epic_id="EPIC-9",
    epic_summary="Account security improvements",
    component="auth",
)


def run(story: RawStory, label: str) -> None:
    print(f"\n{'=' * 70}\n{label}: {story.story_id} — {story.title}\n{'=' * 70}")
    outcome = groom_story(story)

    print(f"Decision: {outcome.decision.value}")
    print(f"Score:    {outcome.score.overall_score} / 10  (gate = {outcome.score.gate_threshold})")
    print("Per-dimension scores:")
    for dim, val in outcome.score.per_dimension.items():
        print(f"  {dim:28s} {val:.1f}")

    if outcome.score.all_gaps:
        print("Gaps identified:")
        for gap in outcome.score.all_gaps:
            print(f"  - {gap}")

    if outcome.gherkin:
        print(f"\nGherkin generated ({outcome.gherkin.scenario_count} scenarios, tags={outcome.gherkin.tags}):")
        print("-" * 70)
        print(outcome.gherkin.feature_text)
        print("-" * 70)

        # Demonstrate the human approval step — in production this comes
        # from the UAT Lead clicking "Approve" in the review UI, not from
        # a script.
        record = approve_story(
            story.story_id, score=outcome.score.overall_score,
            approver_id="demo-uat-lead@example.com", notes="Approved via run_example.py demo",
        )
        print(f"\nApproved by {record.actor} at {record.timestamp.isoformat()}")


if __name__ == "__main__":
    if "ANTHROPIC_API_KEY" not in os.environ:
        print("Set ANTHROPIC_API_KEY before running this demo.", file=sys.stderr)
        sys.exit(1)

    run(WEAK_STORY, "WEAK STORY (expected: below gate, no Gherkin)")
    run(STRONG_STORY, "STRONG STORY (expected: passes gate, Gherkin generated)")
