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
- `src/lean_formalization_engine/codex_agent.py`
  Live `codex exec` backend that keeps the same theorem-spec, plan, and Lean-draft
  contracts while letting Codex inspect the repo read-only.
- `src/lean_formalization_engine/subprocess_agent.py`
  External turn adapter that shells out to a provider command over stdin/stdout while
  preserving the same persisted prompt/request/response artifacts.
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
- `lean_workspace_template/` plus `src/lean_formalization_engine/workspace_template/`
  Matching repo-local and packaged Lean templates so source-tree and installed runs use the
  same compile surface.

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

## Where Model Calls Happen

`FormalizationAgent` exposes three generation turns:

1. `draft_theorem_spec()` turns source text into a structured theorem spec.
2. `draft_formalization_plan()` turns the approved spec plus local context into a Lean-facing plan.
3. `draft_lean_file()` turns the approved plan plus repair context into a Lean draft.

The first two turns happen once per approved stage. The third is the repeated one.
Today that third turn receives explicit retry budget, previous draft, and previous compile
result instead of only raw stderr text.

The new subprocess adapter makes the model-call seam concrete without baking an API vendor
into the engine. A provider command reads the stage request from stdin and returns:

- `prompt`
- `raw_response`
- `parsed_output`

The repo now also ships a first built-in live backend for that same seam. The
`CodexCliFormalizationAgent` uses `codex exec` with an explicit JSON schema per turn, so
the engine can keep a typed artifact trail even when the provider is a general coding
agent rather than a custom API wrapper.

## Compile-Repair Loop

After plan approval, the workflow enters the core bounded loop:

1. draft a Lean file from the approved plan,
2. compile it in the run-local Lean workspace,
3. persist the exact compile result,
4. if it failed, feed the previous draft plus compile result into the next `draft_lean_file()` turn.

The loop stops when one of three things happens:

- the draft passes the compile and quality gates,
- the Lean toolchain is missing and the run stalls for human intervention,
- the retry cap is hit and the run is kicked to stall review instead of looping forever.

If a run is interrupted mid-repair, `resume()` reloads the last persisted compile result
and draft so the next repair attempt still has the previous diagnostics and code in context.
If Lean was missing, `resume()` retries the stalled run after the toolchain is installed.
If the retry cap was the blocker, `approve-stall` records a fresh human decision to allow
one more repair attempt on the same persisted run.

## Run Directory Shape

Each run lives under `artifacts/runs/<run_id>/` and preserves:

- `manifest.json`
- `events.jsonl`
- one artifact directory per workflow stage
- a reusable `workspace/` copy of the Lean template with build caches removed

Run IDs are validated as single safe path segments and are never silently reused, so a
new run cannot escape `artifacts/runs/` or inherit stale approvals from an older run.

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

## Current v0 decision

Athena and the local prototype agreed on the same initial shape:

- Python hosts the orchestration layer.
- Lean remains the acceptance gate rather than the host runtime.
- The artifact trail is the system of record.
- Human review stays explicit instead of disappearing behind a generic agent framework.
