"""
Configuration for the Spec & Grooming Agent.

In production, ANTHROPIC_BASE_URL should point at your organization's
governed internal LLM gateway rather than the public Anthropic API
endpoint, so every model call stays inside the audit and
data-governance boundary described in the implementation guide.
The Anthropic Python SDK honors ANTHROPIC_BASE_URL out of the box —
no code change needed to switch, only the environment variable.
"""
import os

# Model selection: Sonnet 5 is a solid default for this kind of structured
# extraction/generation workload — strong instruction-following at lower
# cost/latency than Opus. Move to claude-opus-4-8 if you find borderline
# scoring calls (stories near the 8.0 gate) need more careful reasoning.
INTERROGATION_MODEL = os.environ.get("AGENT1_INTERROGATION_MODEL", "claude-sonnet-5")
GHERKIN_MODEL = os.environ.get("AGENT1_GHERKIN_MODEL", "claude-sonnet-5")

MAX_TOKENS_INTERROGATION = 2048
MAX_TOKENS_GHERKIN = 2048

# Point this at your governed gateway in production, e.g.:
#   export ANTHROPIC_BASE_URL="https://llm-gateway.internal.jpmc.example/anthropic"
#   export ANTHROPIC_API_KEY="<issued-by-gateway>"
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL")  # None => public API default
