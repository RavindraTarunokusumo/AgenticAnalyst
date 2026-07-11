"""LangSmith tracing configuration with correlation and redaction.

Tracing is completely opt-in via LANGSMITH_TRACING=true + key.
When disabled, this module is a no-op.
"""

from __future__ import annotations

import os
from typing import Any

from analyst_engine.config import Settings


def _scrub_text(text: str | None, max_len: int = 200) -> str | None:
    if not text:
        return text
    # Never let raw article bodies or long excerpts leak into traces
    if len(text) > max_len:
        return text[:max_len] + "…[REDACTED]"
    # Light scrubbing for obvious secrets (keys rarely appear in content)
    if "sk-" in text or "Bearer " in text:
        return "[REDACTED]"
    return text


def redact_for_tracing(payload: dict[str, Any]) -> dict[str, Any]:
    """Remove or truncate sensitive content before any tracing export."""
    redacted = dict(payload)
    if "messages" in redacted:
        redacted["messages"] = [
            {k: _scrub_text(v) if isinstance(v, str) else v for k, v in m.items()}
            for m in redacted["messages"]
        ]
    if "input" in redacted and isinstance(redacted["input"], str):
        redacted["input"] = _scrub_text(redacted["input"])
    if "article" in redacted or "cleaned_content" in redacted:
        redacted.pop("article", None)
        redacted.pop("cleaned_content", None)
    return redacted


def configure_langsmith(settings: Settings) -> None:
    """Configure LangSmith environment if tracing enabled.

    Does not fail the process if LangSmith is misconfigured (non-fatal).
    """
    if not settings.langsmith_tracing:
        # Ensure off
        os.environ.pop("LANGSMITH_TRACING", None)
        return

    os.environ["LANGSMITH_TRACING"] = "true"
    if settings.langsmith_api_key:
        os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key.get_secret_value()
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint

    # Default to redacting in client metadata where possible (best effort)
    # Actual redaction of article content must be done by callers before
    # passing data to traceable functions or the gateway.
