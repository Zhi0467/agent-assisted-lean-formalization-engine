# Orchestrator-Only Contract

This is the intended boundary for Terry after Wangzhi's 2026-04-16 merge-blocking
feedback. Terry should orchestrate the workflow; the chosen backend should own the
actual theorem understanding, enrichment, planning, and proving content.

This is now the live boundary in the working tree rather than a future sketch. Terry
passes only a narrow control-plane request, the backend writes stage files directly into
the run directory, and Terry compiles only the current `candidate.lean`.

## Terry Owns

- run creation under `artifacts/runs/<run_id>/`
- source snapshotting plus minimal source metadata under `00_input/`
- `checkpoint.md`, `review.md`, and persisted `decision.json` at each human handoff
- `logs/timeline.md` and `logs/workflow.jsonl`
- Lean workspace discovery / bootstrap and the compile invocation
- the hard gate that keeps plan generation behind an obtained natural-language proof
- retry-cap accounting, proof-loop pause / resume, and final approval state
- persisted backend selection in the manifest so resumed runs do not drift

## Terry Must Not Own

- theorem extraction schemas
- enrichment report schemas
- plan / theorem-spec schemas
- theorem parsing or binder parsing
- Terry-authored summaries of theorem meaning, plan content, or proof rationale
- schema-constrained backend outputs such as JSON-only stage payloads
- synthesized fallback content for older providers

## Backend Owns

- the actual enrichment work
- the actual plan / formal-statement work
- the actual proving work
- all stage content that humans review, except Terry's generic checkpoint / review files
- any extra human-readable or machine-readable artifacts it wants to write inside the
  stage directory
- reading prior stage files to continue the run

## File Interface

The interface should be file-first. Terry may still pass a tiny control-plane payload to
launch the backend, but theorem content itself should travel only through files.

### Fixed Terry surfaces

- `00_input/source.*` (opaque source snapshot; the extension depends on the original input file)
- `00_input/provenance.json`
- `<stage>/checkpoint.md`
- `<stage>/review.md`
- `<stage>/decision.json`
- `logs/timeline.md`
- `logs/workflow.jsonl`

### Required backend-written files

- `01_enrichment/handoff.md`
  The default human review target for stage 1. The backend may add any supporting files
  beside it.
- `01_enrichment/natural_language_statement.md`
  Plain-language statement surface that later plan/proof/review workers can reference by
  path.
- `01_enrichment/proof_status.json`
  Control-plane proof gate for stage 1. Terry reads only whether the natural-language
  proof was obtained, not the theorem content itself.
- `01_enrichment/prerequisites/` in divide-and-conquer mode
  A non-empty prerequisite inventory directory covering the definitions and lemmas that
  appear before or beneath the final theorem.
- `02_plan/handoff.md`
  The default human review target for stage 2. The backend may add any supporting files
  beside it.
- `02_plan/dependency_graph.md` in divide-and-conquer mode
  A bottom-up dependency map from prerequisite definitions and lemmas to the final
  theorem, including any independently formalizable components.
- `03_proof/attempts/attempt_<n>/candidate.lean`
  The Lean file Terry compiles for that attempt.
- `03_proof/attempts/attempt_<n>/review/walkthrough.md`
- `03_proof/attempts/attempt_<n>/review/readable_candidate.lean`
- `03_proof/attempts/attempt_<n>/review/error.md`
  Terry review artifacts for that proof attempt.

- `01_enrichment/natural_language_proof.md`
  Required in practice whenever `proof_status.json` reports `obtained: true`.
- `03_proof/attempts/attempt_<n>/review/walkthrough.md`
- `03_proof/attempts/attempt_<n>/review/readable_candidate.lean`
- `03_proof/attempts/attempt_<n>/review/error.md`
  These review artifacts should also be passed back into later proof turns by pointer
  when Terry asks the backend for a repair attempt.

### Optional backend-written files

- `01_enrichment/*`
- `02_plan/*`
- `03_proof/attempts/attempt_<n>/*` other than the required `candidate.lean` and `compile_result.json`, plus review artifacts under `review/`
- `04_final/handoff.md`
- any other files the backend wants to preserve for replay or human review

Terry should point humans at the backend-written handoff file(s), not regenerate their
content into a Terry-owned schema summary.

## Minimal Control Plane

If Terry invokes the backend through stdin/stdout or subprocess arguments, the payload
should stay narrow:

- stage name
- run directory
- output directory for this stage or attempt
- paths to prior stage files that the backend should inspect
- a divide-and-conquer mode flag when Terry expects prerequisite inventory and a
  dependency graph
- attempt metadata such as attempt number / retry cap
- the current attempt's compile result when Terry is asking for an attempt review
- path to the latest compile result file when Terry is asking for a repair attempt
- human review notes file path when the stage resumes from a handoff

The control plane should not restate theorem meaning, assumptions, symbols, plan fields,
or proof content that already lives on disk.

## Implemented Surface In This Branch

- `src/lean_formalization_engine/agents.py`
  Single file-first backend protocol: `run_stage(StageRequest) -> AgentTurn`
- `src/lean_formalization_engine/models.py`
  Control-plane-only request, manifest, and compile types without Terry-owned theorem or plan schemas
- `src/lean_formalization_engine/cli_exec_agent.py`
  `codex exec` prompt that reads prior files and writes the required stage file directly
- `src/lean_formalization_engine/subprocess_agent.py`
  External provider bridge that passes the narrow request over stdin/stdout and expects the provider to write files directly
- `src/lean_formalization_engine/workflow.py`
  Checkpoint orchestration, review parsing, proof-loop control, and validation that the backend wrote the required file
- `examples/providers/scripted_repair_provider.py`
  Minimal command-backend example that follows the same file contract

## Verification Focus

The contract is only credible if Terry survives both the happy path and the repair path
without slipping back into Terry-owned stage content. The current verification surface is:

- `PYTHONPATH=src python3 -m unittest discover -s tests`
- a fresh CLI command-backend e2e run that stops for enrichment, merged plan, proof retry, and final approval through `review.md`
- direct `codex review --base main` on the working tree
