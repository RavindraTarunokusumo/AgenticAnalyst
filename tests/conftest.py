"""Root pytest configuration shared across all test modules."""

from __future__ import annotations

from typing import Any


def pytest_configure(config: Any) -> None:
    """Prevent third-party import-time dotenv loading from polluting os.environ.

    crawl4ai calls `dotenv.load_dotenv()` unconditionally at import time, which
    walks up from the working directory and loads whatever ancestor .env file it
    finds - including blank optional-field placeholders - into the process
    environment. That leaks into every later test in the same pytest session
    (e.g. DATABASE_URL becoming "" instead of unset), breaking fixtures that rely
    on specific env vars being genuinely absent. Neutralize it before collection
    imports any module that triggers the load, so the patched no-op is what
    third-party `from dotenv import load_dotenv` bindings pick up.
    """
    del config
    import dotenv

    dotenv.load_dotenv = lambda *args, **kwargs: False
