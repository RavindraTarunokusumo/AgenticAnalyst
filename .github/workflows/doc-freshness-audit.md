# Doc Freshness Audit Workflow Documentation

## Purpose
Ensure that documentation stays in sync with the actual code and behavior.

## What to Check
- Architecture, database, patterns, commands, and testing docs reflect current implementation.
- Changelog and insights are up to date after merges.
- TODO.md does not contain stale completed items (they belong in archive).
- AGENTS.md / CLAUDE.md are mirrors.

## Process
1. Compare key behaviors in code against docs.
2. Identify drift.
3. Propose minimal doc updates.
4. Run through normal validation + PR process.

## Agent Notes
- Do not update docs for behavior that has not yet landed.
- After PR merge, the post-PR step (documented in AGENTS.md) is responsible for final doc sync and archiving.
