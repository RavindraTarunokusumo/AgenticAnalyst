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

## 2026-07-12 — Runtime and Persistence Repair (codex/runtime-persistence-repair, PR #2)

- What worked:
  - Strict `git status --porcelain` before every staging action, followed by explicit `git add <specific-file>` (never `git add -A`), held up across a long, iterative session with many small corrective commits.
  - Structured git notes on every commit (Task/Summary/Docs/TODO/Validation) made post-hoc reconstruction of what each commit did possible without re-reading full diffs.
  - Iterative small corrective commits in direct response to CI/PR review feedback (DATABASE_URL isolation, Windows selector policy portability) kept each fix independently reviewable instead of folding fixes back into earlier commits.
  - Doing the full quality-gate run (ruff format/check, mypy, pytest incl. Docker-backed integration tests, Compose structure) once per milestone rather than after every commit avoided repeatedly paying for expensive Docker-backed test runs.
  - Post-PR archival caught a real gap: local `main` was stale (5 commits behind `origin/main`, including the entire PR #2 merge) even though `git status` reported "up to date" — that message only compares against the *last local fetch*, not current remote state. Always `git fetch origin` before trusting `git status`/`git log` for a Post-PR or session-start check.

- What failed:
  - Reflection content was added to `docs/insights.md` mid-session (Task 7) before the session was actually done, then had to be reverted in a follow-up commit when more corrective work was still required. Reflection should only be written once at true session end (Post-PR/Post-merge), not speculatively mid-task.
  - `.worktree/harness-20260710` was left behind as a stale, unregistered directory (not tracked by `git worktree list`) after its PR merged and was archived — worktree cleanup (workflow step 7) was skipped at the end of that prior session, leaving cruft to discover and clean up later.
  - PowerShell (pwsh) consistently fails on Unix idioms (head, tail, grep, ls -1, | cat); every such command needed rewriting with Get-ChildItem, Select-Object, Select-String.
  - MCP servers (gitnexus in particular) intermittently reported "disconnected"/"connecting" mid-session, forcing fallback to direct file/git tools rather than graph queries.

- Useful commands:
  - `git fetch origin && git merge --ff-only origin/main` — the correct way to catch up local `main` before any Post-PR step; never assume `git status`'s "up to date" claim without fetching first.
  - `git merge-base --is-ancestor <branch-tip> main` — confirm a feature branch is fully merged before deleting its worktree/branch.
  - `git worktree list` — the source of truth for which `.worktree/*` directories are real registered worktrees vs. stale leftover folders.
  - `gh pr view <n> --json number,title,mergeCommit,mergedAt,url,body` — pull merge metadata for archive-file tagging without opening the browser.
  - `git ls-remote --heads origin <branch>` — check whether a merged branch's remote ref still needs cleanup.

- Scripts created: none (all one-liners or direct tool edits).

- Workflow improvement:
  - Post-PR (step 6) should start with an explicit `git fetch origin` + ancestry check, not just `git status`, since a merged PR can leave the local checkout of `main` behind the merge commit.
  - Worktree deletion (step 7) should be verified via `git worktree list` before `rm -rf`-ing a `.worktree/<name>` directory — some may be stale/unregistered and can be removed directly, others are live registered worktrees requiring `git worktree remove`.
  - Session reflection entries should be written exactly once, at Post-PR time, covering the whole session's arc — not incrementally per-task, to avoid the "premature reflection, then revert" churn seen in this session's Task 7 commits.

- Skill worth adding or updating:
  - A "post-pr-sync" checklist item (fetch + ff-only + worktree audit) could be folded into the existing Post-PR workflow step so it's not rediscovered ad hoc each time.
