# Roadmap

Last updated: 2026-04-03 10:25 UTC

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

- the demo produces a final Lean file and compile logs under `artifacts/runs/`.

### Activity Log

- [2026-04-03 10:25 UTC] Initialized the project surface around five durable directories: `src/`, `examples/`, `assets/`, `artifacts/`, and `lean_workspace_template/`.
- [2026-04-03 10:25 UTC] Chose Python for the v0 engine, using typed dataclasses and protocols instead of an agent framework.
- [2026-04-03 10:25 UTC] Added an approval-driven workflow scaffold with theorem-spec review, plan review, compile attempts, and final review.
- [2026-04-03 10:25 UTC] Added `docs/landscape.md` so the repo starts with explicit borrow-vs-rebuild guidance rather than an ungrounded agent loop.
- [2026-04-03 10:25 UTC] Athena consult was requested for the architecture/language decision, but the MCP call timed out before a usable response arrived. The current scaffold therefore records only the locally verified design.

## Milestone 2 — Add A Real Provider Adapter

Success criteria:

- a model-backed agent can produce theorem specs, plans, and Lean drafts,
- prompts and responses are persisted without changing the artifact contract,
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
