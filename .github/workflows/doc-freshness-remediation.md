# Doc Freshness Remediation Workflow Documentation

## Purpose
Remediate documentation drift discovered during audits or during implementation.

## Guidelines
- Update the canonical source of truth first (usually the technical doc in `docs/` or AGENTS.md).
- Propagate to mirrors (AGENTS.md ↔ CLAUDE.md).
- If behavior changed, also update changelog.md.
- Archive completed TODO items only after merge.

## Workflow Integration
- Remediation changes follow the same rules as feature work: TODO entry, validation, small commits, git notes, PR.
- Post-PR doc commits go directly to main (fast-forward).

## Agent Behavior
Agents must not silently edit docs outside the task scope. All doc changes related to implementation must be logged in the active TODO session.
