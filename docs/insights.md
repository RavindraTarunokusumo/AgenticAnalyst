# Insights

Record reusable lessons from completed sessions.

## <YYYY-MM-DD> — <Session Name>

- What worked:
- What failed:
- Useful commands:
- Scripts created:
- Workflow improvement:
- Skill worth adding or updating:

## 2026-07-11 — Technical Harness Implementation (codex/harness-20260710, PR #1)

- What worked:
  - Task-scoped commits with specific staging (never git add -A) and attached git notes.
  - Implementing *all* tasks (4-8) first, then single full quality gate run at the end (as explicitly requested) — avoided repeated expensive full pytest/mypy during dev.
  - Delegating bundled review via subagent (captured sessionId, PENDING review posted).
  - Using receiving-code-review protocol: verified each finding vs actual code before fixing, pushed back on skeleton-scope items (intentional per approved plan).
  - Python -c and PowerShell here-strings / Set-Content for reliable multi-line edits and heredocs (pwsh parsing of << EOF is fragile in tool).
  - git status before every action + full gates (ruff + mypy src + pytest) after key fixes.

- What failed:
  - Unix tools in pwsh (head, tail, grep, | cat) consistently fail or produce parser errors — must use Select-Object, Select-String, python -c.
  - Background tasks (long gates) often return "(no output yet)" in tool; had to re-run or read .log files directly from ~/.grok/sessions/.../terminal/.
  - git remote was pointing to old AnalystEngine name (repo had moved); push --dry-run revealed it, had to set-url and re-push.
  - main checkout already claimed by another worktree; had to operate on main via git -C <main-path> and absolute paths for edits.
  - Some mypy "errors" were only 3p stub notes or layout (tests/fixtures duplicate module); had to add explicit_package_bases + overrides to get clean "Success".

- Useful commands:
  - git status --porcelain; git push --dry-run origin HEAD (always first).
  - ="copy"; uv run ... (for OneDrive hardlink issues).
  - gh pr create --body-file ... --json number,url ; gh pr merge <num> --merge
  - python -c "..." for complex re.sub on TODO, archive creation.
  - uv run ruff ... --fix ; uv run mypy src ; uv run pytest --ignore=tests/evaluation

- Scripts created: pr-body.md (temp), various python one-liners for archive/TODO strip.

- Workflow improvement:
  - "Implement all then full gate" is powerful for long-running verification steps; should be documented as option when user requests it.
  - Always surface background task logs by reading the .log file path when tool says "(no output yet)".
  - For worktrees + main post-PR pushes: document the -C <main> + absolute-path pattern for edits.

- Skill worth adding or updating:
  - receiving-code-review subagent could auto-extract actionable items + suggest patches.
  - review skill could better handle "skeleton by design" cases and avoid flagging intentional placeholders.

## 2026-07-12 — Runtime and Persistence Repair Documentation Reconciliation (codex/runtime-persistence-repair, Task 7)

- What worked:
  - Strict adherence to `git status --porcelain` before every staging action, followed by explicit `git add <specific-file>` (never `git add -A`).
  - Use of `todo_write` tool to decompose Task 7 and track sub-items (inspection, multiple doc files, TODO, verification, commit+note).
  - Structured git notes on every commit using the established Task/Summary/Docs/TODO/Validation format.
  - Precise file inspection with `read_file` (offset+limit) + `grep` tool + pwsh `Select-String`/`Get-Content` to avoid loading entire files.
  - python -c one-liners for trailing-newline normalization and reliable multi-line string handling.
  - Running focused static verification (`ruff format --check`, `ruff check`, `mypy src`) even on pure documentation changes.
  - Polling backgrounded long-running commands via `get_command_or_subagent_output`.
  - Iterative small corrective commits in direct response to spec review feedback, each independently reviewed and noted.

- What failed:
  - PowerShell (pwsh) consistently fails on Unix idioms (head, tail, grep, ls -1, | cat); every command required rewriting with Get-ChildItem, Select-Object, Select-String.
  - MCP servers (especially gitnexus) frequently report "disconnected", "connecting", or "failed to connect", forcing fallback to direct file/git tools.
  - `read_file` output format (LINE_NUMBER|CONTENT) is easy to accidentally paste into `search_replace` old_string, causing "not unique" or "not found" errors.
  - Long commands (mypy etc.) are auto-backgrounded; immediate responses often return task IDs or "(no output yet)".
  - Subtle wording issues around environment configuration (Compose forwarding vs direct app runtime) and TODO completion claims required several rounds of corrective commits.
  - Reflection content added too early had to be removed in a later commit when additional spec fixes were still required.

- Useful commands:
  - git status --porcelain; git add <exact files>; git diff --cached
  - python -c "import pathlib; ... rstrip('\n') + '\n' ..." for normalization
  - uv run ruff format --check . ; uv run ruff check . ; uv run mypy src
  - Select-String -Path file -Pattern ... ; Get-Content ... -Tail
  - git notes add -m "Task: ...\nSummary: ...\n..." <hash>
  - get_command_or_subagent_output with task_ids for background results

- Scripts created: none (all one-liners or tool-driven edits)

- Workflow improvement:
  - For documentation-only reconciliation after code work, the "inspect → targeted edit → full staged diff review → focused static checks → specific commit + note" loop is very effective at catching wording drift.
  - TODO hash tracking should be done via a dedicated post-correction commit rather than trying to include the final hash in the original reconciliation commit.
  - Explicitly leaving items unchecked when external gates (controller full suite + Docker) are required prevents premature closure.
  - Recording "premature" reflection and then removing it via a clean commit is better than leaving inaccurate content.

- Skill worth adding or updating:
  - A lightweight "doc reconciliation" or "text hygiene" helper for normalization, diff review, and structured reflection scaffolding.
  - check-work / review skills should support a "docs reconciliation" mode that emphasizes diff hygiene and static checks without running full test suites or Docker.


