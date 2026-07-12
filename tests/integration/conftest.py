"""Shared pytest configuration and harness setup for tests.

Covers:
- Early Windows SelectorEventLoop policy for psycopg/async checkpointer
  compatibility under pytest (Proactor is default on Win32 and incompatible).
- Portable: no-op on non-Windows.
"""

from __future__ import annotations

import asyncio
import os
import sys

# Set policy at conftest import time (before pytest-asyncio instantiates
# any event loops for fixtures or tests). This resolves LangGraph
# psycopg async checkpointer failures on Windows when DOCKER_HOST
# integration tests run.
if sys.platform == "win32" or os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
