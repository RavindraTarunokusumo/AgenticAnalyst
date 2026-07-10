# Code Health Remediation Workflow Documentation

This document describes the process and expectations for automated or semi-automated code health remediation in the repository.

## Purpose
- Keep the codebase lint-clean, formatted, and free of low-level issues.
- Provide a repeatable process that agents and humans can follow.

## Triggers
- On push to main or on PRs (once CI is configured).
- Manually when a developer or agent runs the remediation.

## Steps
1. Run the project's lint + format commands (see docs/commands.md).
2. Apply safe auto-fixes where available.
3. Run full test suite to ensure fixes did not break behavior.
4. Review diff for any surprising changes.
5. Commit with clear message referencing the remediation.

## Agent Usage
Agents should:
- Use specific staging (`git add <files>`) never `git add -A`.
- Validate with full suite before committing.
- Record the work in TODO.md if it was part of a larger task.

## Notes
- This is documentation for the intended workflow.
- Actual GitHub Actions workflow YAML will be added later when CI is set up.
