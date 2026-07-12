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
  - Strict specific staging with explicit file list (`git add docs/foo.md TODO.md`) and `git diff --cached` review before every commit.
  - todo_write tool to break Task 7 into 13 trackable sub-items and mark them progressively.
  - python -c one-liner for reliable cross-file trailing-newline normalization on text docs.
  - Targeted read_file (offset + limit) + grep for precise inspection of large docs without loading everything.
  - Structured git notes matching the exact format from prior commits (Task / Summary / Docs / TODO / Validation).
  - Polling backgrounded long commands (mypy) via get_command_or_subagent_output.
  - Always running `git status --porcelain` before staging or commit actions.

- What failed:
  - Unix utilities (head, tail, grep, ls -1, | cat) do not work reliably in pwsh; every command had to be rewritten with Get-ChildItem, Select-Object, Select-String, Get-Content.
  - read_file output format (LINE_NUMBER|CONTENT) is easy to accidentally copy into search_replace old_string, causing "not unique" or "not found" failures until stripped.
  - Long-running verification commands are automatically backgrounded; the immediate response often says "(no output yet)" or task-id only.
  - MCP servers (gitnexus, linear, tasks, vercel) frequently show "connecting", "disconnected", or "failed to connect" messages mid-session; had to work without gitnexus at times.
  - Select-String on piped git diff output sometimes returned no matches even when strings were present in the file; had to fall back to direct read_file + grep tool.

- Useful commands:
  - git status --porcelain (before any git action)
  - git diff --no-color -- <specific-files> | Select-Object -First N
  - python -c "import pathlib; ... rstrip('\n') + '\n' ..." for normalization
  - uv run ruff format --check . ; uv run ruff check . ; uv run mypy src
  - Get-ChildItem ... -Name ; Select-String -Path file -Pattern ...
  - get_command_or_subagent_output with task_ids for background results

- Scripts created: none (all one-liners or tool calls)

- Workflow improvement:
  - For pure documentation / reconciliation tasks, still run the full py static checks (ruff + mypy) as "focused verification" — proves no accidental breakage to the rest of the tree.
  - The TODO placeholder + structured note pattern works but should be called out explicitly in AGENTS.md as the standard way to handle hash tagging when the commit itself is the one that marks the item.
  - Document a standard "normalize trailing newlines for text files" step using python -c so every agent doesn't reinvent it.
  - When copying strings from read_file for search_replace, always remind to drop the "N|" prefix.

- Skill worth adding or updating:
  - A small "normalize-text" or "doc-hygiene" helper command/skill for newlines, trailing whitespace, etc.
  - check-work or review skill should have a "docs-only" mode that skips full test runs but still does ruff/mypy + diff hygiene.
