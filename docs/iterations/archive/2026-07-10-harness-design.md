# 2026-07-10 — Harness Design (spec + plan, direct to main)

**Merge:** N/A — planning-only session, committed directly to `main` (no feature branch/PR).
Preceded and fed the `codex/harness-20260710` implementation branch archived at
[2026-07-10-technical-harness-implementation.md](2026-07-10-technical-harness-implementation.md) (PR #1).

Spec: `docs/superpowers/specs/2026-07-10-harness-design.md`
Plan: `docs/superpowers/plans/2026-07-10-technical-harness.md`

## Completed Work

- [x] Write and validate the approved local-first technical harness specification. (`cd6bf4e`, `d912f3d`)
- [x] Clarify batch-summary provenance and the temporal-holdout demo test. (`ed02bfe`)
- [x] Defer claim-event persistence and define cadence-specific frontier outputs. (`6e0ee11`)
- [x] Accelerate the temporal-holdout replay without relaxing visibility controls. (`14134cb`)
- [x] Produce the lightweight implementation contract for the approved technical harness. (`fec2cfa`, `bd11db8`)

## Summary

Defined the approved local-first technical harness specification (Python, LangGraph, DashScope, PostgreSQL/pgvector, LangSmith, quality-gate contract) and its lightweight implementation plan (file structure, interface contracts, build order, coverage map, risks), per the spec-driven Workflow step 3. Resolved two open design questions during spec writing — batch-summary-to-claim-event lineage plus an opt-in temporal-holdout evaluation, and deferring structured claim events pending prototype evaluation while still defining daily/weekly/monthly frontier outputs — and specified an accelerated virtual-clock temporal-holdout replay with no real-time waiting and no relaxed visibility controls.

This was pure spec/plan authoring with no application code; the resulting contract was implemented in the following session (Tasks 1-8, `codex/harness-20260710`, PR #1).

## Verification

- `git diff --check` and placeholder/active-reference scans on each spec/plan commit (no application code to gate; see the linked implementation session's archive for the build-time quality gates).
