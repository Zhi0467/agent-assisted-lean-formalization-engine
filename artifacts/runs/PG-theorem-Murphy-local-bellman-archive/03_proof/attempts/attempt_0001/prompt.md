You are the backend for Terry, a Lean 4 formalization workflow.
Terry is only the orchestrator. Do the theorem work through files.

Stage: proof
Repo root: current working directory
Run directory: artifacts/runs/PG-theorem-Murphy
Output directory: artifacts/runs/PG-theorem-Murphy/03_proof/attempts/attempt_0001

Read the listed input files from disk and write the required output files into the output directory.
Treat the listed pointer names as the complete context surface for this turn. If the needed proof or theorem facts are not present there, say so explicitly in the stage outputs instead of assuming hidden context.
The pointer names are request keys, not required field names inside the theorem source itself.
The `source` pointer may be any original input file type; if it is not already plain text, the backend is responsible for ingesting or extracting what it needs from that file.
Do not edit files outside the output directory.

Stage inputs:
- enrichment_review: artifacts/runs/PG-theorem-Murphy/01_enrichment/review.md
- enrichment_theorem_statement: artifacts/runs/PG-theorem-Murphy/01_enrichment/theorem_statement.lean
- natural_language_proof: artifacts/runs/PG-theorem-Murphy/01_enrichment/natural_language_proof.md
- natural_language_statement: artifacts/runs/PG-theorem-Murphy/01_enrichment/natural_language_statement.md
- proof_status: artifacts/runs/PG-theorem-Murphy/01_enrichment/proof_status.json
- provenance: artifacts/runs/PG-theorem-Murphy/00_input/provenance.json
- relevant_lean_objects: artifacts/runs/PG-theorem-Murphy/01_enrichment/relevant_lean_objects.md
- source: artifacts/runs/PG-theorem-Murphy/00_input/source.pdf

Required outputs:
- artifacts/runs/PG-theorem-Murphy/03_proof/attempts/attempt_0001/candidate.lean


Stage-specific instructions:
- Read every pointer listed in the "Stage inputs" block above — especially `enrichment_theorem_statement`, `natural_language_statement`, `natural_language_proof`, optional `relevant_lean_objects`, and any `enrichment_review` / `proof_review` reviewer notes — before editing Lean.
- `enrichment_theorem_statement` points to the enrichment-stage `theorem_statement.lean` file. Reproduce the theorem signature (name, binders, hypotheses, conclusion) from that file verbatim in `candidate.lean` and only replace the `sorry` placeholder with a real proof body.
- The imports listed in `enrichment_theorem_statement` and `relevant_lean_objects` are advisory starting points, not closed sets. If the natural-language proof requires additional mathlib modules, add the import — do not refuse to proceed because an import was not pre-listed.
- Objective: the natural-language proof is your contract — translate it into a Lean 4 proof that compiles cleanly. Follow the math and adjust tactics, lemmas, or intermediate steps until the proof type-checks. Do not stop, fall back to `sorry`, or hand back a half-finished draft until you believe the Lean compiler will come back clean on this `candidate.lean`.
- Keep the theorem surface aligned with the approved statement unless reviewer notes explicitly change it.
Reviewer notes path: artifacts/runs/PG-theorem-Murphy/01_enrichment/review.md
Attempt: 1/3

When you are done, reply with a brief plain-text note describing what you wrote.
