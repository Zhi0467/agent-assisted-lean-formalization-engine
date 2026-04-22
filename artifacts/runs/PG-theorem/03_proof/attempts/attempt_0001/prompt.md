You are the backend for Terry, a Lean 4 formalization workflow.
Terry is only the orchestrator. Do the theorem work through files.

Stage: proof
Repo root: current working directory
Run directory: artifacts/runs/PG-theorem
Output directory: artifacts/runs/PG-theorem/03_proof/attempts/attempt_0001

Read the listed input files from disk and write the required output files into the output directory.
Treat the listed pointer names as the complete context surface for this turn. If the needed proof or theorem facts are not present there, say so explicitly in the stage outputs instead of assuming hidden context.
The pointer names are request keys, not required field names inside the theorem source itself.
The `source` pointer may be any original input file type; if it is not already plain text, the backend is responsible for ingesting or extracting what it needs from that file.
Do not edit files outside the output directory.

Stage inputs:
- enrichment_handoff: artifacts/runs/PG-theorem/01_enrichment/handoff.md
- natural_language_proof: artifacts/runs/PG-theorem/01_enrichment/natural_language_proof.md
- natural_language_statement: artifacts/runs/PG-theorem/01_enrichment/natural_language_statement.md
- plan_handoff: artifacts/runs/PG-theorem/02_plan/handoff.md
- plan_theorem_statement: artifacts/runs/PG-theorem/02_plan/theorem_statement.lean
- proof_status: artifacts/runs/PG-theorem/01_enrichment/proof_status.json
- provenance: artifacts/runs/PG-theorem/00_input/provenance.json
- relevant_lean_objects: artifacts/runs/PG-theorem/01_enrichment/relevant_lean_objects.md
- source: artifacts/runs/PG-theorem/00_input/source.pdf

Required outputs:
- artifacts/runs/PG-theorem/03_proof/attempts/attempt_0001/candidate.lean


Stage-specific instructions:
- Read `plan_handoff`, `plan_theorem_statement`, `natural_language_statement`, `natural_language_proof`, optional `relevant_lean_objects`, and any `plan_review` / `proof_review` notes before editing Lean.
- `plan_theorem_statement` points to the plan-stage `theorem_statement.lean` file. Treat the imports and locked theorem signature there as authoritative for `candidate.lean`; reproduce them verbatim and only replace the `sorry` placeholder with a real proof body.
- Objective: produce exactly the next `candidate.lean` for this attempt while staying inside the approved theorem statement and proof route.
- Formalize the approved plan into Lean.
- Reuse the existing Lean/mathlib objects identified during enrichment when that pointer is available.
- Keep the theorem surface aligned with the approved statement unless reviewer notes explicitly change it.
- On repair attempts, read the previous candidate and compile result before editing.
- Read any previous walkthrough, readable-candidate, or error-report pointers before repairing.
- Write only `candidate.lean` for this attempt.
Attempt: 1/3

When you are done, reply with a brief plain-text note describing what you wrote.
