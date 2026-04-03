# Roadmap

Last updated: 2026-04-03 09:30 UTC

## Current Status

The repo now has a concrete v0 scaffold:

- typed Python engine under `src/`,
- runnable demo under `examples/`,
- persisted run artifacts under `artifacts/`,
- and a minimal Lean workspace template for compile checks.

The next gate is replacing the deterministic demo agent with a real model-backed
formalization loop while preserving the same artifact and approval surface.

## Milestone 1 — Lock the Engine Skeleton

Success criteria:

- the repo has a stable directory layout,
- the engine modules have explicit interfaces,
- the run state machine persists artifacts at each stage,
- a demo example exercises the full flow.

Gate:

- demo produces a final Lean file and compile logs under `artifacts/runs/`.

### Activity Log

- [2026-04-03 09:30 UTC] Initialized the project surface around four durable directories: `src/`, `examples/`, `assets/`, and `artifacts/`.
- [2026-04-03 09:30 UTC] Chose Python for the v0 engine, using typed dataclasses and protocols instead of an agent framework.
- [2026-04-03 09:30 UTC] Added a compile-oriented workflow scaffold with theorem-spec approval, plan approval, and final review checkpoints.
- [2026-04-03 09:30 UTC] Added `lean_workspace_template/` so each run gets an isolated Lean workspace for compilation.
- [2026-04-03 09:30 UTC] Athena deep consult completed in this task thread and reinforced the same direction: Python v0, file-backed state machine, explicit checkpoints, no framework-heavy orchestration. Full transcript is archived in `.agent/runtime/consult_history/1775197696.768269.jsonl`.

## Milestone 2 — Add A Real Provider Adapter

Success criteria:

- a model-backed agent can produce theorem specs, plans, and Lean drafts,
- prompts/responses are persisted without changing the artifact contract,
- compilation failures feed a bounded repair loop.

Gate:

- at least one non-demo theorem runs through the model-backed path with persisted prompts and diagnostics.

## Milestone 3 — Improve Lean Context And Repair

Success criteria:

- the engine can choose imports more intelligently,
- the repair loop uses structured diagnostics rather than raw stderr only,
- auxiliary lemma generation can be turned on without changing the base pipeline.

Gate:

- at least one previously failing theorem is recovered by the repair loop without manual file editing.
