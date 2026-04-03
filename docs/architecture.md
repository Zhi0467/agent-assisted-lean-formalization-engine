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
  and the persisted run manifest.
- `src/lean_formalization_engine/ingest.py`
  Reads Markdown/LaTeX directly and provides an optional PDF extraction path.
- `src/lean_formalization_engine/agents.py`
  Declares the `FormalizationAgent` protocol and the typed `AgentTurn` wrapper.
- `src/lean_formalization_engine/demo_agent.py`
  Deterministic agent implementation for the shipped example workflow.
- `src/lean_formalization_engine/storage.py`
  Owns run directory creation, JSON/text persistence, and event logging.
- `src/lean_formalization_engine/lean_runner.py`
  Copies the Lean template into a run-local workspace and executes `lake build`.
- `src/lean_formalization_engine/workflow.py`
  The state machine that advances a run until it blocks or completes.
- `src/lean_formalization_engine/cli.py`
  Thin CLI surface for running the engine without importing it manually.

## State Machine

The engine advances through these persisted stages:

1. `created`
2. `ingested`
3. `spec_drafted`
4. `waiting_for_spec_approval`
5. `spec_approved`
6. `plan_drafted`
7. `waiting_for_plan_approval`
8. `plan_approved`
9. `draft_generated`
10. `compile_passed` or `compile_failed`
11. `waiting_for_final_approval`
12. `completed`

## Run Directory Shape

Each run lives under `artifacts/runs/<run_id>/`:

- `manifest.json`
- `events.jsonl`
- `00_input/`
- `01_normalized/`
- `02_spec/`
- `03_plan/`
- `04_draft/`
- `05_compile/`
- `06_final/`

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
  confirm the compiling Lean file is the one worth keeping.

The example workflow auto-approves these checkpoints. The engine contracts keep the
checkpoints explicit so model-backed runs can stop there later.
