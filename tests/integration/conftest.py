"""Shared pytest configuration and harness setup for tests.

Covers:
- Early Windows SelectorEventLoop policy for psycopg/async checkpointer
  compatibility under pytest (Proactor is default on Win32 and incompatible).
- Portable: no-op on non-Windows.
"""

from __future__ import annotations

import asyncio
import sys

# Set policy at conftest import time (before pytest-asyncio). Portable.
if sys.platform == "win32":
    policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if policy is not None:
        asyncio.set_event_loop_policy(policy())
