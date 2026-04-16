# Orchestrator-Only Contract

This is the intended boundary for Terry after Wangzhi's 2026-04-16 merge-blocking
feedback. Terry should orchestrate the workflow; the chosen backend should own the
actual theorem understanding, enrichment, planning, and proving content.

## Terry Owns

- run creation under `artifacts/runs/<run_id>/`
- source ingestion and provenance capture under `00_input/`
- `checkpoint.md`, `review.md`, and persisted `decision.json` at each human handoff
- `logs/timeline.md` and `logs/workflow.jsonl`
- Lean workspace discovery / bootstrap and the compile invocation
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

- `00_input/source.txt`
- `00_input/normalized.md`
- `<stage>/checkpoint.md`
- `<stage>/review.md`
- `<stage>/decision.json`
- `logs/timeline.md`
- `logs/workflow.jsonl`

### Required backend-written files

- `01_enrichment/handoff.md`
  The default human review target for stage 1. The backend may add any supporting files
  beside it.
- `02_plan/handoff.md`
  The default human review target for stage 2. The backend may add any supporting files
  beside it.
- `03_proof/attempts/attempt_<n>/candidate.lean`
  The Lean file Terry compiles for that attempt.

### Optional backend-written files

- `01_enrichment/*`
- `02_plan/*`
- `03_proof/attempts/attempt_<n>/*` other than the required `candidate.lean`
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
- attempt metadata such as attempt number / retry cap
- path to the latest compile result file when Terry is asking for a repair attempt
- human review notes file path when the stage resumes from a handoff

The control plane should not restate theorem meaning, assumptions, symbols, plan fields,
or proof content that already lives on disk.

## Current Violations In This Branch

- `models.py` / `agents.py`
  Terry-owned stage dataclasses and typed backend protocol
- `codex_agent.py`
  JSON-schema-constrained stage outputs
- `subprocess_agent.py`
  `parsed_output` contract plus theorem-spec fallback synthesis
- `workflow.py`
  Terry-authored extraction / enrichment / plan summaries and context-pack synthesis

## Refactor Order

1. Replace the typed backend API with a filesystem-first stage API.
2. Change Codex and subprocess backends to read/write stage files directly.
3. Remove Terry-owned theorem / enrichment / plan dataclasses and fallback parsers.
4. Rewrite checkpoint generation so Terry points at backend-owned handoff files.
5. Revalidate the Terry happy path and one blocked proof-loop resume on the new file
   contract before merging.
