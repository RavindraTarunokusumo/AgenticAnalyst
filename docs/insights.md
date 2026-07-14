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

## 2026-07-14 — RSS-to-Daily-Brief Vertical Slice (codex/rss-daily-brief-plan, PR #3)

- What worked:
  - Grok CLI delegation (`grok -p ... -m grok-composer-2.5-fast --always-approve --output-format json`) handled most of the 14 implementation tasks; independent post-delegation verification (full ruff/mypy/pytest gate, not the implementer's scoped self-report) caught roughly 10 real bugs across the session (idempotency logic, test-harness bugs, an auth accidental-pass, a date-cutoff exclusion bug) that a "trust the implementer" workflow would have shipped. This is the single strongest validation yet of Workflow Rule 10.
  - Distinguishing Grok's two distinct failure modes mattered: "killed but real (uncommitted, unverified) work was done" (Tasks 10, 12) vs. "killed with zero output and no session even registered" (Task 14, 3x) required checking `git status --porcelain` and `grok sessions list`, not just the wrapper's exit status, before deciding whether to salvage or fall back.
  - Once Grok had failed 3x in a session (Task 14), extending that same distrust to review-type delegations (security review, code review) rather than re-attempting Grok for them was the right call — native Agent-tool subagents (the `security-review` builtin skill's pattern, and the `requesting-code-review` superpowers skill's template) worked cleanly as a same-session fallback with no further setup cost.
  - `gh run watch <id> --exit-status` and `gh pr checks <n>` were effective for monitoring CI after a push without manual polling.
  - Git notes on every commit (Task/Summary/Docs/TODO/Validation) again made post-hoc reconstruction possible without re-reading diffs, including across the mid-flight security-fix and CI-fix commits that weren't part of the original 14-task plan.

- What failed / had to be worked around:
  - A CI-only failure class was completely invisible locally: Docker is unavailable in this dev environment, so 19-21 Postgres-backed tests were silently skipped on every local gate run. "Full local suite green" was not sufficient evidence the PR was mergeable — the first push to PR #3 failed 5 tests in CI that had never executed locally at all. The workflow's "run the full gate before committing" rule needs an explicit caveat: when a local environment is missing a dependency CI has (Docker, here), the local gate cannot validate that dependency's code paths, and CI must be watched as a genuinely separate, non-redundant check, not a formality after "tests passed."
  - Root-causing those 5 CI failures required reading actual GitHub Actions logs (`gh run view <id> --log-failed`) rather than guessing; the real cause (5 test modules sharing one physical CI Postgres database with zero cleanup between tests, so literal fixture values like `url_fingerprint="fp-a1"` collided across files) was a cross-task bug invisible to any single task's own scoped verification — each task's Grok delegation wrote its own copy-pasted `migrated`/`pg_container` fixture boilerplate with no shared cleanup, and nothing caught the aggregate effect until all 5 modules existed together in one CI run.
  - The `advisor` tool was unavailable for the entire session ("do not try to use it again") — had to make several judgment calls (whether to fix vs. push back on a code-review finding, how to scope the CI-failure fix) without that second opinion. Worth checking advisor availability early in a session rather than assuming it.
  - `--always-approve` for Grok delegation was blocked by a safety classifier on first use and needed an explicit `AskUserQuestion` confirmation before every subsequent delegation could proceed unattended — worth setting this expectation at session start next time Grok delegation is planned, rather than rediscovering the prompt mid-task.
  - The main-branch worktree had pre-existing uncommitted changes (CLAUDE.md/AGENTS.md) unrelated to this session at Post-PR time; had to explicitly diff-check that the incoming merge range didn't touch those files before running `git merge --ff-only`, to avoid conflating this session's Post-PR commit with the user's own in-progress unrelated edits.

- Useful commands:
  - `gh pr checks <n>` / `gh run watch <id> --exit-status` / `gh run view <id> --log-failed` — CI status and failure-log retrieval without opening the browser.
  - `git merge-base --is-ancestor <commit> <merge-commit>` — confirm a specific late-session commit (e.g. a post-review fix) actually made it into the merged PR before starting Post-PR archival.
  - `git diff --stat <base>..<remote> -- <dirty-file>` — check whether an incoming fast-forward range touches files with pre-existing uncommitted local changes, before merging.
  - `gh pr comment <n> --body "$(cat <<'EOF' ... EOF)"` — post structured review-reception summaries (security review, code review triage) directly to the PR as the audit trail, matching the reception-protocol requirement without a separate doc.

- Scripts created: none (all direct tool edits and one `TRUNCATE`-based test fixture helper in `tests/fixtures.py`).

- Workflow improvement:
  - Add an explicit note to Workflow Rule 10 (or a new rule) that a local "full gate green" claim is only as strong as local environment parity with CI — when Docker (or any CI-only dependency) is unavailable locally, treat the first CI run after push as a required, non-redundant verification step, not a formality.
  - When Grok delegation fails 3x in a session, treat that as a session-scoped signal to route ALL remaining delegation-eligible work (not just the task that failed) through the native-Agent-tooling fallback for the rest of that session, rather than re-attempting Grok per-task.
  - Consider a shared root-level pytest fixture (or a `docs/testing.md`-documented convention, added this session) for Postgres-backed test modules, so future task delegations don't each reinvent their own `migrated`/`pg_container` boilerplate without cleanup — the current per-module copy-paste pattern is what caused the CI-only collision.

- Skill worth adding or updating:
  - The `requesting-code-review` superpowers skill's template is a solid same-session Grok fallback for the "main professional code review" Submit-PR step; consider referencing it directly in CLAUDE.md's Submit PR section as the named fallback path, rather than only the generic "spawn native subagents" clause.
  - A lightweight "check advisor availability" step near session start (or graceful degradation messaging) would avoid silently losing that safety net for judgment-call decisions mid-session.

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
