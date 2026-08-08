"""
Event-driven webhook entry point (Section 2 of the implementation guide):
"new story enters 'Ready for Grooming' -> triggers the pipeline" rather
than scheduled polling.

This is a minimal FastAPI app illustrating the shape of the integration —
swap _payload_to_raw_story() for your actual Jira/ADO webhook payload
format, and run() for a queue-backed worker rather than in-request
processing once you're past the pilot (grooming a story involves two LLM
calls and can take a few seconds; don't block the webhook response on it).

Run locally with:
    uvicorn webhook_service:app --reload
"""
from __future__ import annotations

import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from gate import GroomingOutcome
from models import RawStory
from pipeline import groom_story

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = FastAPI(title="Agent 1 — Spec & Grooming Webhook")


class JiraWebhookPayload(BaseModel):
    """Shape this to match your actual Jira Automation / ADO service hook
    payload. Kept intentionally minimal here."""
    issue_key: str
    status_to: str
    fields: dict


def _payload_to_raw_story(payload: JiraWebhookPayload) -> RawStory:
    fields = payload.fields
    return RawStory(
        story_id=payload.issue_key,
        title=fields.get("summary", ""),
        description=fields.get("description", ""),
        acceptance_criteria_raw=fields.get("customfield_acceptance_criteria", ""),
        epic_id=fields.get("epic_link"),
        epic_summary=fields.get("epic_summary"),
        labels=fields.get("labels", []),
        component=(fields.get("components") or [None])[0],
        linked_openapi_spec=fields.get("customfield_openapi_link"),
    )


def _process(raw: RawStory) -> None:
    try:
        outcome: GroomingOutcome = groom_story(raw, write_to_jira=True)
        logger.info("story %s groomed: decision=%s", raw.story_id, outcome.decision.value)
        # Score/gaps and (if generated) Gherkin are now written back to the
        # Jira ticket by groom_story() itself — see jira_client.py. A
        # human-readable report is also saved to reports/<story_id>.md.
    except Exception:
        logger.exception("story %s: grooming pipeline failed", raw.story_id)
        # TODO: route to a dead-letter queue / alert channel rather than
        # silently dropping a failed grooming attempt.


@app.post("/webhooks/jira/status-change")
def handle_status_change(payload: JiraWebhookPayload, background_tasks: BackgroundTasks):
    if payload.status_to != "Ready for Grooming":
        return {"skipped": True, "reason": f"status is '{payload.status_to}', not 'Ready for Grooming'"}

    try:
        raw = _payload_to_raw_story(payload)
    except Exception as e:  # noqa: BLE001 - any parsing failure on external input becomes a 400
        raise HTTPException(status_code=400, detail=f"malformed payload: {e}")

    # Don't block the webhook response on two LLM calls — process async.
    background_tasks.add_task(_process, raw)
    return {"accepted": True, "story_id": raw.story_id}


@app.get("/health")
def health():
    return {"status": "ok"}
