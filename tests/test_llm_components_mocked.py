"""
Mocked tests for Components B and D — verifies the request-building and
response-parsing code against a realistic fake anthropic.Anthropic client,
without needing a live API key or network access. This catches malformed
tool schemas and incorrect response-field access, which is most of what
actually breaks in this kind of integration code.

Run with:  pytest tests/test_llm_components_mocked.py -v
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from models import RUBRIC_DIMENSIONS, NormalizedStory


def _make_story() -> NormalizedStory:
    return NormalizedStory(
        story_id="ABC-1",
        title="Login with MFA",
        description="User logs in with a second factor.",
        acceptance_criteria=[
            "User enters valid credentials and is prompted for OTP",
            "Invalid OTP shows an error and does not log the user in",
        ],
        epic_id="EPIC-1",
        epic_summary="Account security",
        component="auth",
        labels=["security"],
        linked_openapi_spec=None,
    )


# --- Component B: interrogation ----------------------------------------------

def test_interrogate_story_parses_tool_use_response():
    import interrogation

    fake_findings = [
        {"dimension": dim, "score": 9.0, "rationale": "clear", "gaps": []}
        for dim in RUBRIC_DIMENSIONS
    ]
    fake_tool_block = SimpleNamespace(type="tool_use", input={"findings": fake_findings})
    fake_response = SimpleNamespace(content=[fake_tool_block], id="msg_test_123")

    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch.object(interrogation, "get_client", return_value=fake_client):
        result = interrogation.interrogate_story(_make_story())

    assert result.story_id == "ABC-1"
    assert len(result.findings) == len(RUBRIC_DIMENSIONS)
    assert result.raw_response_id == "msg_test_123"

    # Confirm the call was actually shaped correctly: forced tool choice,
    # correct tool name, all six dimensions in the schema.
    _, kwargs = fake_client.messages.create.call_args
    assert kwargs["tool_choice"] == {"type": "tool", "name": "record_testability_findings"}
    schema_enum = kwargs["tools"][0]["input_schema"]["properties"]["findings"]["items"]["properties"]["dimension"]["enum"]
    assert set(schema_enum) == set(RUBRIC_DIMENSIONS)


def test_interrogate_story_raises_on_missing_dimension():
    import interrogation

    incomplete_findings = [
        {"dimension": RUBRIC_DIMENSIONS[0], "score": 9.0, "rationale": "x", "gaps": []}
    ]
    fake_tool_block = SimpleNamespace(type="tool_use", input={"findings": incomplete_findings})
    fake_response = SimpleNamespace(content=[fake_tool_block], id="msg_test_124")

    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with (
        patch.object(interrogation, "get_client", return_value=fake_client),
        pytest.raises(RuntimeError, match="omitted dimensions"),
    ):
        interrogation.interrogate_story(_make_story())


def test_interrogate_story_raises_when_no_tool_use_block():
    import interrogation

    fake_response = SimpleNamespace(content=[SimpleNamespace(type="text", text="I'd rather not")], id="msg_test_125")
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with (
        patch.object(interrogation, "get_client", return_value=fake_client),
        pytest.raises(RuntimeError, match="no tool_use block"),
    ):
        interrogation.interrogate_story(_make_story())


# --- Component D: Gherkin generation -----------------------------------------

VALID_FEATURE_TEXT = """@story-ABC-1 @component-auth
Feature: Login with MFA

  Scenario: Valid credentials and valid OTP
    Given a user with valid credentials
    When the user enters a valid OTP
    Then the user is logged in

  Scenario: Invalid OTP shows an error
    Given a user with valid credentials
    When the user enters an invalid OTP
    Then an error message is displayed and the user is not logged in
"""


def test_generate_gherkin_parses_and_validates_response():
    import gherkin_gen

    fake_text_block = SimpleNamespace(type="text", text=VALID_FEATURE_TEXT)
    fake_response = SimpleNamespace(content=[fake_text_block])
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch.object(gherkin_gen, "get_client", return_value=fake_client):
        spec = gherkin_gen.generate_gherkin(_make_story())

    assert spec.story_id == "ABC-1"
    assert spec.scenario_count == 2
    assert "@story-ABC-1" in spec.tags
    assert "@component-auth" in spec.tags


def test_generate_gherkin_strips_markdown_fences():
    import gherkin_gen

    fenced = "```gherkin\n" + VALID_FEATURE_TEXT + "```"
    fake_text_block = SimpleNamespace(type="text", text=fenced)
    fake_response = SimpleNamespace(content=[fake_text_block])
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with patch.object(gherkin_gen, "get_client", return_value=fake_client):
        spec = gherkin_gen.generate_gherkin(_make_story())

    assert not spec.feature_text.startswith("```")
    assert spec.scenario_count == 2


def test_generate_gherkin_raises_on_too_few_scenarios():
    import gherkin_gen

    under_generated = """@story-ABC-1 @component-auth
Feature: Login with MFA

  Scenario: Only one scenario for two ACs
    Given a user with valid credentials
    When the user enters a valid OTP
    Then the user is logged in
"""
    fake_text_block = SimpleNamespace(type="text", text=under_generated)
    fake_response = SimpleNamespace(content=[fake_text_block])
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_response

    with (
        patch.object(gherkin_gen, "get_client", return_value=fake_client),
        pytest.raises(gherkin_gen.GherkinValidationError),
    ):
        gherkin_gen.generate_gherkin(_make_story())  # story has 2 ACs, only 1 scenario given
