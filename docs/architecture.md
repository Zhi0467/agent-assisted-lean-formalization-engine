# Architecture

Version: `0.2.0`

Tags: `mathlib-template`, `pre-spec-extraction`, `enrichment-handoff`, `bounded-repair-loop`

Last updated: `2026-04-15`

## Design Principles

- Filesystem-first: every stage emits real artifacts on disk.
- Explicit contracts: no untyped cross-module payloads.
- Staged understanding before Lean: extraction and enrichment happen before theorem-spec drafting.
- Human checkpoints at prerequisite readiness, theorem meaning, formal target, and final output.
- Lean as the acceptance gate, not a hidden side effect.

## Module Layout

- `src/lean_formalization_engine/models.py`
  Defines source types, extraction and enrichment artifacts, theorem specs, formalization plans, Lean drafts, compile attempts, human decisions, and the persisted run manifest.
- `src/lean_formalization_engine/agents.py`
  Declares the `FormalizationAgent` protocol.
- `src/lean_formalization_engine/demo_agent.py`
  Deterministic agent implementation for the shipped zero-add example.
- `src/lean_formalization_engine/codex_agent.py`
  Live `codex exec` backend that keeps the same extraction, enrichment, theorem-spec, plan, and Lean-draft contracts while letting Codex inspect the repo read-only.
- `src/lean_formalization_engine/subprocess_agent.py`
  External turn adapter that shells out to a provider command over stdin/stdout while preserving the same persisted prompt/request/response artifacts.
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
  Matching repo-local and packaged Lean templates. The template now mirrors a neutral `lake new FormalizationEngineWorkspace math` scaffold and carries an explicit mathlib dependency.

## Workflow

The workflow now has four pre-compile understanding steps:

1. Ingest and normalize the theorem source.
2. Extraction: pull out the theorem statement, required definitions, lemmas, propositions, and dependency chain into a Markdown artifact.
3. Enrichment: assess whether the extracted package is self-contained, identify what infrastructure already exists in Lean/mathlib, identify what is missing, and produce a human handoff summary.
4. Theorem-spec drafting: only after enrichment approval does the agent draft the structured theorem spec used by the later Lean plan.

The formalization plan then consumes both the approved theorem spec and the approved enrichment report, so missing prerequisites remain explicit instead of disappearing between stages.

## State Machine

The engine advances through these persisted stages:

1. `created`
2. `awaiting_enrichment_review`
3. `awaiting_spec_review`
4. `awaiting_plan_review`
5. `repairing`
6. `awaiting_final_review`
7. `awaiting_stall_review`
8. `completed`

The artifact tree captures the sub-steps between those gates:

- `00_input/`
- `01_normalized/`
- `02_extraction/`
- `03_enrichment/`
- `04_spec/`
- `05_context/`
- `06_plan/`
- `07_draft/`
- `08_compile/`
- `09_review/`
- `10_final/`

## Model Turns

`FormalizationAgent` exposes five generation turns:

1. `draft_theorem_extraction()`
2. `draft_theorem_enrichment()`
3. `draft_theorem_spec()`
4. `draft_formalization_plan()`
5. `draft_lean_file()`

The first four run once per stage. The fifth is the repeated repair-loop turn. The repair turn still receives explicit retry budget, previous draft, and previous compile result instead of only raw stderr text.

The subprocess adapter keeps this seam concrete without baking an API vendor into the engine. A provider command reads the stage request from stdin and returns:

- `prompt`
- `raw_response`
- `parsed_output`

The built-in `CodexCliFormalizationAgent` uses `codex exec` with an explicit JSON schema per turn, so the engine keeps a typed artifact trail even when the provider is a general coding agent.

## Enrichment Handoff

The enrichment stage is where the workflow surfaces the kind of judgment a human reviewer actually needs before committing to Lean work. The handoff explicitly records:

- whether the theorem package looks self-contained,
- which prerequisites appear satisfied by current Lean/mathlib infrastructure,
- which prerequisites are missing,
- which missing items must be carried into the formalization plan,
- a recommended scope and difficulty estimate,
- and a prose summary for the human handoff point.

This is where a theorem like policy gradient should say, in substance, that probability and analysis primitives may already exist while the reinforcement-learning layer still has to be defined by hand. The plan stage must then preserve those missing prerequisites explicitly in `prerequisites_to_formalize`.

## Compile-Repair Loop

After plan approval, the workflow enters the core bounded loop:

1. Draft a Lean file from the approved plan.
2. Compile it in the run-local Lean workspace.
3. Persist the exact compile result.
4. If it failed, feed the previous draft plus compile result into the next `draft_lean_file()` turn.

The loop stops when one of three things happens:

- the draft passes the compile and quality gates,
- the Lean toolchain is missing and the run stalls for human intervention,
- the retry cap is hit and the run is kicked to stall review instead of looping forever.

If a run is interrupted mid-repair, `resume()` reloads the last persisted compile result and draft so the next repair attempt still has the previous diagnostics and code in context.

## Lean Workspace Template

The checked-in Lean workspace template is now mathlib-backed rather than Lean-only. Concretely:

- `lakefile.toml` carries the mathlib requirement and the standard mathlib-oriented lean options.
- `lean-toolchain` is pinned to a released Lean version that matches an available mathlib tag.
- `FormalizationEngineWorkspace/Basic.lean` imports `Mathlib`, so theorem drafts can depend on mathlib through the local workspace module.
- The runner ignores transient `.lake/`, `build/`, and `lake-manifest.json` state when copying the template into a run-local workspace.

This keeps the repo template neutral in name while ensuring the run workspace starts with mathlib in scope.

## Run Directory Shape

Each run lives under `artifacts/runs/<run_id>/` and preserves:

- `manifest.json`
- `events.jsonl`
- one artifact directory per workflow stage
- a reusable `workspace/` copy of the Lean template with build caches removed

Run IDs are validated as single safe path segments and are never silently reused, so a new run cannot escape `artifacts/runs/` or inherit stale approvals from an older run.

Each agentic stage persists:

- `prompt.md`
- `request.json`
- `raw_response.json`
- `parsed_output.json`

## Human Checkpoints

- Enrichment approval:
  confirm the extracted theorem package is scoped correctly and the handoff says what infrastructure is missing.
- Spec approval:
  confirm the theorem meaning before any Lean target is committed.
- Plan approval:
  confirm the theorem name, imports, target statement, proof strategy outline, and explicit prerequisite work.
- Final approval:
  confirm the compiling Lean candidate is the one worth keeping.

The example workflow auto-approves these checkpoints. The contracts keep them explicit so model-backed runs can stop there later.
