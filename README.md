# Agent 1 — Spec & Grooming Agent (Reference Implementation)

[![Build](https://github.com/matiascuba621-lang/agent1_spec_grooming/actions/workflows/build.yml/badge.svg)](https://github.com/matiascuba621-lang/agent1_spec_grooming/actions/workflows/build.yml)
[![Lint](https://github.com/matiascuba621-lang/agent1_spec_grooming/actions/workflows/lint.yml/badge.svg)](https://github.com/matiascuba621-lang/agent1_spec_grooming/actions/workflows/lint.yml)
[![Tests](https://github.com/matiascuba621-lang/agent1_spec_grooming/actions/workflows/tests.yml/badge.svg)](https://github.com/matiascuba621-lang/agent1_spec_grooming/actions/workflows/tests.yml)
[![Coverage](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/matiascuba621-lang/agent1_spec_grooming/master/coverage-badge.json)](https://github.com/matiascuba621-lang/agent1_spec_grooming/actions/workflows/coverage.yml)
[![License: MIT](https://img.shields.io/github/license/matiascuba621-lang/agent1_spec_grooming)](LICENSE)
[![Contributors](https://img.shields.io/github/contributors/matiascuba621-lang/agent1_spec_grooming)](https://github.com/matiascuba621-lang/agent1_spec_grooming/graphs/contributors)
[![Top Language](https://img.shields.io/github/languages/top/matiascuba621-lang/agent1_spec_grooming)](https://github.com/matiascuba621-lang/agent1_spec_grooming)
[![Code Size](https://img.shields.io/github/languages/code-size/matiascuba621-lang/agent1_spec_grooming)](https://github.com/matiascuba621-lang/agent1_spec_grooming)
[![Repo Size](https://img.shields.io/github/repo-size/matiascuba621-lang/agent1_spec_grooming)](https://github.com/matiascuba621-lang/agent1_spec_grooming)

A working implementation of the four components described in
`Agent1_Spec_Grooming_Implementation_Guide.docx`, wired together with the
DoR gate state machine, an audit trail, Jira write-back, a human
verification report, and a review CLI. Tested — see **Verified** below.

## Input, Output, and Verification — the short version

**Input:** a `RawStory` (title, description, raw acceptance criteria,
EPIC link, component). Delivered one of two ways:
- **Automatic** — `webhook_service.py` listens for a Jira/ADO
  status-change event ("Ready for Grooming") and triggers grooming
  without anyone doing anything manually. This is the production path.
- **Manual** — `python cli.py groom story.json` for testing, backfill,
  or grooming a story before it's even in Jira yet.

**Output — three things, every run:**
1. **The Jira ticket itself** (`jira_client.py`) — a comment with the
   score/breakdown/gaps, a custom-field update with the numeric score,
   and (if the gate passed) the generated Gherkin plus a
   `grooming-pending-approval` label.
2. **The audit trail** (`audit_log.jsonl`) — the immutable
   system-of-record Agent 7 reads.
3. **A human verification report** (`reports/<story_id>.md`) — this is
   the one to actually read. Score, per-dimension breakdown with a
   visual bar, the full gap list, the complete generated Gherkin, and an
   explicit "what happens next" line.

**Verification — for you and the team:**
- `python cli.py review` lists every story sitting at
  `PENDING_APPROVAL`, opens its full report right in the terminal, and
  lets the named UAT Lead approve / edit-and-approve / reject on the
  spot — this *is* the human gate from the implementation guide, not a
  separate thing bolted on.
- The report file itself is a shareable artifact — attach it to a Slack
  thread, a PR, an email; it's not locked inside this codebase.
- `pytest tests/` (34 tests) verifies the code is correct; the report +
  CLI verify that a *specific groomed story* is trustworthy. Those are
  different questions — the tests don't replace a human reading the
  report before approving.

## Structure

| File | Component | Type |
|---|---|---|
| `ingestion.py` | A. Ingestion & Normalization | Deterministic, no LLM |
| `interrogation.py` | B. Interrogation Module | Claude API, forced tool-use for structured output |
| `scoring.py` | C. Scoring Engine | Deterministic, no LLM |
| `gherkin_gen.py` | D. Gherkin Generation | Claude API, template-constrained + syntax-validated |
| `gate.py` | DoR gate + human approval | Deterministic state machine |
| `audit.py` | Audit trail | Append-only log + pending-review derivation |
| `jira_client.py` | **Output: Jira write-back** | Comment + custom field + label, via Jira Cloud REST API v3 |
| `report.py` | **Output: verification report** | Human-readable Markdown per story |
| `cli.py` | **Input delivery + review** | Manual `groom` command, interactive `review` command |
| `pipeline.py` | Orchestrator | Wires A → B → C → D → gate → report → Jira |
| `webhook_service.py` | Automatic input delivery | FastAPI stub for the Jira/ADO status-change webhook |
| `models.py` | Shared data models | Six-dimension rubric, story/score/spec schemas |

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY="sk-ant-..."

# In production, point this at your governed internal LLM gateway instead
# of the public API — no code change needed, only this env var:
# export ANTHROPIC_BASE_URL="https://llm-gateway.internal.example/anthropic"

# Jira write-back (jira_client.py) — either real credentials:
export JIRA_BASE_URL="https://yourorg.atlassian.net"
export JIRA_EMAIL="agent-service-account@yourorg.com"
export JIRA_API_TOKEN="..."
export JIRA_TESTABILITY_SCORE_FIELD="customfield_10050"  # your actual custom field ID
# ...or, to test the wiring without real Jira credentials:
export JIRA_DRY_RUN=1
```

## Run the tests

```bash
pytest tests/ -v
```

34 tests, all passing without a live API key or real Jira credentials:

- `test_deterministic_components.py` (18 tests) — ingestion, scoring,
  Gherkin syntax validation, and the full gate state machine, including
  the constraint that `approve_story()` refuses to run without a named
  human `approver_id`.
- `test_llm_components_mocked.py` (6 tests) — verifies the request shape
  sent to Claude (forced tool choice, all six rubric dimensions present
  in the schema) and the response-parsing logic, against a mocked
  client, so these run without network access.
- `test_output_and_review.py` (10 tests) — the verification report's
  content for both gate outcomes, the Jira client in `JIRA_DRY_RUN` mode
  (and that it correctly refuses to run without credentials when *not*
  in dry-run mode), and the audit log's pending-review derivation
  (a story shows up in `list_pending_story_ids()` only between
  `gherkin_generated` and a human decision, never before or after).

I also ran the CLI's actual interactive `review` flow end-to-end in this
sandbox (seed a pending story → `cli.py review` → select it → approve as
a named user) and confirmed the audit trail recorded the right actor and
the story dropped out of the pending list afterward — not just unit
tests in isolation.

## Run the live demo

Requires a real `ANTHROPIC_API_KEY` — this makes actual API calls:

```bash
python run_example.py
```

Runs two stories through the full pipeline: one deliberately vague story
(expected to score below the 8.0 gate, so no Gherkin is generated) and
one well-specified story (expected to pass and produce a tagged
`.feature` file), then demonstrates the human-approval step.

## What's a placeholder vs. what's real logic

**Real, load-bearing logic** — safe to build on directly:
- The gate state machine and its constraint that approval requires a
  named human (`gate.py`)
- The immutable audit trail shape (`audit.py`, `models.AuditRecord`),
  including the pending-review derivation the CLI's `review` command
  relies on
- The Gherkin syntax validator (`gherkin_gen.py:validate_gherkin`) — this
  actually checks for tags, scenario count vs. AC count, and a `Then` in
  every scenario, not just a smoke test
- The forced-tool-use pattern in `interrogation.py`, which guarantees
  parseable structured output from Claude every time
- **`jira_client.py`** — real HTTP calls against Jira Cloud REST API v3
  (comment, custom-field update, label), with a `JIRA_DRY_RUN` mode for
  testing the wiring without real credentials. If you're on Jira
  Server/Data Center or Azure DevOps instead of Jira Cloud, the three
  `_post_comment` / `_update_custom_field` / `_add_label` functions are
  the only things that need to change — nothing else in the codebase
  calls the REST API directly.
- **`report.py`** — the Markdown report is generated from the actual
  `GroomingOutcome` object, not a separate summary that could drift from
  what was really decided.

**Placeholders you must replace before this touches a real sprint:**
- **The six rubric dimensions and their weights** (`models.py`,
  `RUBRIC_DIMENSIONS` / `RUBRIC_WEIGHTS`) — these are illustrative. Swap
  in your organization's actual six-dimension Story Testability Score
  definition, and update `interrogation.py`'s system prompt to match,
  since the prompt and the schema must agree.
- **The Jira/ADO payload mapping** (`webhook_service.py:_payload_to_raw_story`)
  — the field names here are generic placeholders, not your actual
  custom-field IDs.
- **`JIRA_TESTABILITY_SCORE_FIELD`** — set this env var to your org's
  actual custom field ID for the testability score.
- **The audit log backend** (`audit.py`) — writes newline-delimited JSON
  to a local file as a stand-in for your real Quality Insights &
  Governance datastore. Swap `write_record()` / `read_all_records()`'s
  bodies only; every caller stays the same.
- **`cli.py review`'s terminal UI** — this is a minimal stand-in for a
  real review UI. The state transitions it triggers
  (`approve_story` / `reject_story`) are real; the interface calling
  them is meant to be replaced by whatever your team's actual review
  workflow is.

## Design notes carried over from the implementation guide

- Components A and C are plain deterministic code by design — no LLM
  call, so the 8.0 gate is reproducible and auditable without re-running
  the model (Section 3 of the guide).
- Component D only runs after Component C confirms the gate is cleared
  (enforced in `pipeline.py`), and its output is syntax-validated before
  it can reach Agent 2 — a malformed `.feature` file never leaves this
  codebase.
- `gate.approve_story()` is the *only* function that can mark a story
  `APPROVED`, and it raises if called without a named `approver_id`.
  Nothing in the automated pipeline calls it — it's meant to be wired to
  the UAT Lead's "Approve" button in your review UI.
