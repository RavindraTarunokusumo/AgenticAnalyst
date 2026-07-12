# TODO.md

This file contains active or future work only.

Completed sessions must be moved to `docs/iterations/archive/`.

## Backlog

## Session: Runtime and Persistence Repair (2026-07-11)

- [x] Separate workflow-run creation from lifecycle updates and enforce valid transitions. (`c717d74`)
- [x] Add OpenRouter configuration and provider routing with offline contract tests. (`1f88183`)
- [x] Introduce shared runtime dependency wiring for API and scheduler modes. (`3600a6a`)
- [x] Execute cadence graphs with stable run/checkpoint identity and truthful failure handling. (`f3d585d`)
- [x] Replace hard-coded readiness and file health markers with database/migration-aware HTTP readiness. (`90a39fe`, `0bb9204`)
- [x] Enable and repair persistence, workflow, API, migration, and Compose verification for this milestone. (`86e41df`, `49ccabc`)
- [ ] Reconcile operational documentation and complete the full project quality gates. (documentation: 739a764, 0268b42, facb92e; pending Docker-backed integration and migration gates)
  - [x] Task 7: valid persistence lineage fixture (`b0b00fa`)
  - [x] Task 7: portable Docker/async integration harness (`f7ab25d`)
  - [ ] Task 7: rerun Docker migration/checkpoint/concurrency gates

## Session: Harness Design (2026-07-10)

- [x] Write and validate the approved local-first technical harness specification.
- [x] Clarify batch-summary provenance and the temporal-holdout demo test.
- [x] Defer claim-event persistence and define cadence-specific frontier outputs.
- [x] Accelerate the temporal-holdout replay without relaxing visibility controls.
- [x] Produce the lightweight implementation contract for the approved technical harness.


## Session: <Session Name> (<YYYY-MM-DD>)

- [ ] <sub-item 1>
- [ ] <sub-item 2>
- [ ] <sub-item 3>

## Future Backlog

- [ ] <future item>
