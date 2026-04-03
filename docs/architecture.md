# Architecture

## Design Principles

- Filesystem-first: every stage emits real artifacts on disk
- Explicit contracts: no untyped cross-module payloads
- Bounded agent loop: draft, compile, repair, stop
- Human checkpoints at meaning, formal target, and final output
- Lean as the acceptance gate, not a hidden side effect

## Module Layout

- `src/lean_formalization_engine/models.py`
  Defines source types, theorem specs, formalization plans, Lean drafts, compile attempts,
  human decisions, and the persisted run manifest.
- `src/lean_formalization_engine/agents.py`
  Declares the `FormalizationAgent` protocol.
- `src/lean_formalization_engine/demo_agent.py`
  Deterministic agent implementation for the shipped zero-add example.
- `src/lean_formalization_engine/ingest.py`
  Reads Markdown and LaTeX directly and provides an optional PDF extraction path.
- `src/lean_formalization_engine/storage.py`
  Owns run directory creation, JSON and text persistence, and event logging.
- `src/lean_formalization_engine/lean_runner.py`
  Copies the Lean template into a run-local workspace and executes the compile checks.
- `src/lean_formalization_engine/workflow.py`
  The state machine that advances a run until it blocks or completes.
- `src/lean_formalization_engine/cli.py`
  Thin CLI surface for running, resuming, and approving stages.

## State Machine

The engine advances through these persisted stages:

1. `created`
2. `awaiting_spec_review`
3. `awaiting_plan_review`
4. `repairing`
5. `awaiting_final_review`
6. `awaiting_stall_review`
7. `completed`

The artifact tree still captures the sub-steps between those gates:

- `00_input/`
- `01_normalized/`
- `02_spec/`
- `03_context/`
- `04_plan/`
- `05_draft/`
- `06_compile/`
- `07_review/`
- `08_final/`

## Run Directory Shape

Each run lives under `artifacts/runs/<run_id>/` and preserves:

- `manifest.json`
- `events.jsonl`
- one artifact directory per workflow stage
- a reusable `workspace/` copy of the Lean template with build caches removed

Each agentic stage persists:

- `prompt.md`
- `request.json`
- `raw_response.json`
- `parsed_output.json`

## Human Checkpoints

- Spec approval:
  confirm the extracted theorem meaning before any Lean target is committed.
- Plan approval:
  confirm the theorem name, imports, target statement, and proof strategy outline.
- Final approval:
  confirm the compiling Lean candidate is the one worth keeping.

The example workflow auto-approves these checkpoints. The contracts keep the checkpoints
explicit so model-backed runs can stop there later.
