"""
Command-line interface — two things this gives you that the webhook
doesn't:

1. `python cli.py groom <file.json>` — manually deliver a story into the
   agent without needing a live Jira webhook wired up. Useful for
   testing, backfilling stories groomed before the agent existed, or
   running this against a story you're drafting before it's even in
   Jira yet.

2. `python cli.py review` — the human verification step. Lists every
   story currently sitting at PENDING_APPROVAL, lets you open its full
   report, and lets the named UAT Lead approve, edit-then-approve, or
   reject it right from the terminal. This is the same action a review
   UI would trigger — this CLI is a minimal stand-in for that UI.

Input JSON shape for `groom` (matches models.RawStory):
{
  "story_id": "ABC-123",
  "title": "...",
  "description": "...",
  "acceptance_criteria_raw": "1. ...\\n2. ...",
  "epic_id": "EPIC-9",
  "epic_summary": "...",
  "labels": ["security"],
  "component": "auth",
  "linked_openapi_spec": null
}
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import audit
from gate import ApprovalRequiresNamedHuman, approve_story, reject_story
from models import RawStory
from pipeline import groom_story
from report import REPORTS_DIR


def cmd_groom(args: argparse.Namespace) -> None:
    payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
    raw = RawStory(
        story_id=payload["story_id"],
        title=payload["title"],
        description=payload.get("description", ""),
        acceptance_criteria_raw=payload["acceptance_criteria_raw"],
        epic_id=payload.get("epic_id"),
        epic_summary=payload.get("epic_summary"),
        labels=payload.get("labels", []),
        component=payload.get("component"),
        linked_openapi_spec=payload.get("linked_openapi_spec"),
    )

    outcome = groom_story(raw, write_to_jira=args.write_jira)

    print(f"\nStory {outcome.story_id}: {outcome.decision.value}")
    print(f"Score: {outcome.score.overall_score} / {outcome.score.gate_threshold}")
    report_path = REPORTS_DIR / f"{outcome.story_id}.md"
    print(f"Full report: {report_path}")
    if args.write_jira:
        print("Written back to Jira.")
    else:
        print("NOT written to Jira (pass --write-jira to actually post back to the ticket).")


def cmd_review(args: argparse.Namespace) -> None:
    pending = audit.list_pending_story_ids()
    if not pending:
        print("Nothing pending review.")
        return

    print(f"{len(pending)} stories pending UAT Lead review:\n")
    for i, story_id in enumerate(pending, 1):
        score = audit.get_latest_score(story_id)
        print(f"  [{i}] {story_id}  (score={score})")

    choice = input("\nOpen which? (number, or 'q' to quit): ").strip()
    if choice.lower() == "q":
        return
    try:
        story_id = pending[int(choice) - 1]
    except (ValueError, IndexError):
        print("Invalid selection.")
        return

    report_path = REPORTS_DIR / f"{story_id}.md"
    if report_path.exists():
        print("\n" + "=" * 70)
        print(report_path.read_text(encoding="utf-8"))
        print("=" * 70 + "\n")
    else:
        print(f"(no report file found at {report_path} — was this story groomed by this CLI/pipeline?)")

    action = input("Approve (a), reject (r), or skip (s)? ").strip().lower()
    if action == "s":
        return

    approver_id = input("Your Jira/user ID (required — this is who gets recorded as the approver): ").strip()
    score = audit.get_latest_score(story_id)

    try:
        if action == "a":
            notes = input("Notes (optional): ").strip()
            approve_story(story_id, score=score, approver_id=approver_id, notes=notes)
            print(f"Approved {story_id} by {approver_id}.")
        elif action == "r":
            reason = input("Reason for rejection (required): ").strip()
            reject_story(story_id, score=score, approver_id=approver_id, reason=reason)
            print(f"Rejected {story_id} by {approver_id}.")
        else:
            print("Unrecognized action, nothing done.")
    except ApprovalRequiresNamedHuman as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Agent 1 — Spec & Grooming CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    groom_parser = sub.add_parser("groom", help="Manually deliver a story (JSON file) into the agent")
    groom_parser.add_argument("file", help="Path to a JSON file matching the RawStory shape")
    groom_parser.add_argument("--write-jira", action="store_true", help="Actually write the result back to Jira")
    groom_parser.set_defaults(func=cmd_groom)

    review_parser = sub.add_parser("review", help="Interactively review and approve/reject pending stories")
    review_parser.set_defaults(func=cmd_review)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
