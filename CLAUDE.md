# CLAUDE.md

Project: AnalystEngine

**Follow the [Workflow](#workflow) strictly for feature implementation**. Do not start implementation until Steps 1-3 are complete. Before editing, show which step you are on.

Any change made to `CLAUDE.md` should also be applied to `AGENTS.md`.

## Project Map

- Architecture: [docs/architecture.md](docs/architecture.md)
- Database / Persistence: [docs/database.md](docs/database.md)
- Patterns: [docs/patterns.md](docs/patterns.md)
- Testing: [docs/testing.md](docs/testing.md)
- Commands: [docs/commands.md](docs/commands.md)
- Agent Harness: [docs/agent-harness.md](docs/agent-harness.md)
- Full Index: [docs/index.md](docs/index.md)

## Code Graph / Repo Map

If a code graph, dependency map, or architecture index exists, use it before touching unfamiliar code.

Rules:
- Do not rebuild the graph while files are being modified.
- Only rebuild on a clean working tree.
- Use the graph as a snapshot, not a live source of truth.
- Query the graph first, then read files directly.

## Workflow

1. (Preamble) Ensure you're in a dedicated local branch/worktree under `.worktree/<session-name>` and activate the project environment (see [docs/commands.md](docs/commands.md)). Read the `docs/insights.md` file and the [Workflow Rules](#workflow-rules).
2. (GitNexus) Read the [GitNexus](#gitnexus--code-intelligence) section at the start of every session.
3. (Spec Writing + Lightweight Plan) For feature implementation, write a detailed specification document following a spec-driven development process (requirements, data models, interfaces, workflows, edge cases, success criteria, and constraints). Do not write implementation plans or code until the spec is complete and accepted. Read the docs (see [Project Map](#project-map)) and use GitNexus as your primary means to understand the codebase. For debugging or minor patching, skip this step. Once the spec is accepted, produce a **lightweight implementation plan** that serves as the implementer's contract — file structure, task decomposition, per-task **Interfaces** (Consumes/Produces signatures), build order, and risks. Do **not** inline verbatim per-step code or exact shell commands; the implementer regenerates those from the contract. The plan's value is the cross-task contract (who calls what, in what order), not transcribed code — that contract is what catches the class of bug a narrowly-scoped implementer cannot see (e.g. a changed signature breaking another caller). This preserves the spec→plan→implementation independent-verification chain at a fraction of the planning cost.
4. (Implementing) Log tasks and sub-items in `TODO.md` first, then implement each task. Capture work in a structured way. After each delegated task, the main agent independently validates with the **full** test suite plus lint/typecheck before committing — never trust a scoped self-report. Also review the diff and normalize output (e.g. trailing newlines) during review. Commit any files written by sub-processes immediately (per Workflow Rule 9). Cross each sub-item and item once done. Where the task graph allows — independent tasks with disjoint files and no shared dependency on unlanded work — run multiple implementers in parallel using isolated git worktrees; otherwise implement sequentially. After a delegated implementation task, validate with the **full** suite + typecheck + lint (not the implementer's scoped tests) before committing. A per-task implementer self-scopes its own verification and structurally cannot see cross-task breakage.
5. (Submit PR) Finally, follow the instructions in the [Submit PR](#submit-pr) workflow — using non-interactive commands where possible to trigger reviews — and notify the user once every step has been completed.
6. (Post-PR) Update documentation files once the PR has been merged and archive completed TODO items from `TODO.md` into `docs/iterations/archive/`; ensure each subitem in the TODO are tagged with the commit hash and each session are tagged with the merge ID - `TODO.md` should only contain **active or future** work only. These Post-PR doc/archive commits are pushed **directly to `main`** (no PR — the feature PR is already merged); fast-forward only, never force.
7. (Reflection) Conclude the session by doing the [Reflection](#reflection) exercise; the Reflection commit is likewise pushed **directly to `main`** (no PR). After receiving confirmation from the user, delete the worktree and branch.

### Workflow Rules

1. Every TODO sub-item should land as its own commit.
2. Any extension or modification to the task should be logged in the TODO.
3. Use specific staging, never `git add -A`.
4. Never force-push, reset `--hard`, merge or amend unless explicitly asked.
5. Keep comments sparse, naming clear, abstractions minimal, and avoid compatibility shims.
6. When lint/typecheck/test fails only on files you did not touch, note it as pre-existing and proceed — do not attempt workarounds that affect other files.
7. After submitting the PR, delegate the code review (and optional security review) to an agent as ephemeral subagent sessions via the non-interactive CLI where available. Capture the `sessionId` from the JSON result, process the review output/side-effects (e.g. PENDING review posts), then immediately delete the corresponding session directory for that security-review or code-review subagent task. Do not rely on GitHub Copilot Code Review. Rigorously address findings using the reception protocol.
8. After context compaction resumes, run `git status` before any other action — the summary describes intent, not exact commit state.
9. Commit any files written by subagents immediately; do not advance the workflow with a dirty tree. For agent-based subagents (security-review, bundled code-review, etc.), always capture the sessionId via `--output-format json` and delete the ephemeral chat session directory after the delegation completes and findings are processed.
10. After a delegated implementation task, validate with the **full** suite + typecheck + lint (not the implementer's scoped tests) before committing. A per-task implementer self-scopes its own verification and structurally cannot see cross-task breakage (e.g. a changed signature breaking another caller); only the full project-level run catches it.

### Submit PR

1. Fill out the **[Template](.github/pull_request_template.md)** and submit the PR (capture the PR number/URL, e.g. via `gh pr create --json number,url`).

2. (Optional) If the changes affect security (or explicitly stated), delegate a non-interactive security review to an agent (ephemeral session). Always cite justification. Capture the session ID and clean it up afterwards so the review chat session is deleted.

3. Generate the main professional code review by delegating the reviewer per the implementation/review handoff pattern. Capture the PR number first and use the review prompt. The skill does the heavy lifting (diff collection, reviewer persona, posting the PENDING GitHub review as a side-effect); the handoff is just the delegation + cleanup wrapper. Capture the returned `sessionId`, process the summary, then delete the session per the handoff. Do not rely on GitHub Copilot Code Review.

- Rigorously address the review findings before considering the task complete. Use the reception protocol defined in the receiving-code-review skill:
  - Read the full feedback first.
  - Verify each item technically against the actual codebase.
  - Push back (with clear technical reasoning) on items that seem incorrect, unclear, or low-value.
  - Implement one change at a time and test it.
  - Avoid performative agreement ("You're right!", "Great catch!"); just state what was done or ask for clarification.

### Reflection

After every session completion, you reflect on how the workflow pertaining to the workflow and agent harness - the commands you executed (and which failed consistently), the tools you used, skills invoked, MCP accessed, etc. **Do not include anything feature-specific**. For example, when the Codebase Graph output is too verbose or if certain powershell commands keeps failing. This is not about the features you implemented, but about *how* you implemented them. Write this down in [Insights](docs/insights.md) and then suggest workflow updates to the user in chat.

---

## GitNexus — Code Intelligence

(If/when GitNexus or equivalent code intelligence tooling is added, document usage here. For now: always start sessions by exploring current structure via file listing, reading key docs.)

---

## Core Operating Rules for Agents

The agent must:
- read `CLAUDE.md` before implementation
- read `docs/index.md` after `CLAUDE.md`
- use technical docs before touching unfamiliar modules
- log work in `TODO.md`
- keep commits small
- validate before committing (lint, typecheck, relevant tests)
- attach git notes
- update docs with behavior changes
- archive completed work
- record useful insights

The agent must not:
- force-push
- hard reset
- amend commits
- merge branches
- use `git add -A`
- run graph rebuilds on dirty mid-edit trees
- silently expand task scope
- rely on AI memory as the source of truth
- skip validation unless explicitly blocked and reported

---

## Project-Specific Notes

(Leave blank until SPEC.md or equivalent is provided.)
