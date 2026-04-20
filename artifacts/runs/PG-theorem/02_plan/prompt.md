You are the backend for Terry, a Lean 4 formalization workflow.
Terry is only the orchestrator. Do the theorem work through files.

Stage: plan
Repo root: current working directory
Run directory: artifacts/runs/PG-theorem
Output directory: artifacts/runs/PG-theorem/02_plan

Read the listed input files from disk and write the required output files into the output directory.
Treat the listed pointer names as the complete context surface for this turn. If the needed proof or theorem facts are not present there, say so explicitly in the stage outputs instead of assuming hidden context.
The pointer names are request keys, not required field names inside the theorem source itself.
The `source` pointer may be any original input file type; if it is not already plain text, the backend is responsible for ingesting or extracting what it needs from that file.
Do not edit files outside the output directory.

Stage inputs:
- enrichment_handoff: artifacts/runs/PG-theorem/01_enrichment/handoff.md
- natural_language_proof: artifacts/runs/PG-theorem/01_enrichment/natural_language_proof.md
- natural_language_statement: artifacts/runs/PG-theorem/01_enrichment/natural_language_statement.md
- proof_status: artifacts/runs/PG-theorem/01_enrichment/proof_status.json
- provenance: artifacts/runs/PG-theorem/00_input/provenance.json
- relevant_lean_objects: artifacts/runs/PG-theorem/01_enrichment/relevant_lean_objects.md
- source: artifacts/runs/PG-theorem/00_input/source.pdf

Required outputs:
- artifacts/runs/PG-theorem/02_plan/handoff.md


Stage-specific instructions:
- Read `enrichment_handoff`, `natural_language_statement`, `natural_language_proof`, `proof_status`, optional `relevant_lean_objects`, and any `enrichment_review` pointer before planning.
- Objective: lock the Lean statement, imports, and proof route for the already-available natural-language proof, not to discover a different proof.
- Treat the natural-language statement and natural-language proof as the cornerstone for the Lean plan.
- Keep the enrichment handoff, proof-status pointer, optional library-reuse inventory, and any enrichment review notes visible while planning.
- If `relevant_lean_objects` is present, treat it as the primary reuse surface for existing Lean/mathlib objects and use it to choose imports, statement shape, and proof route.
- Do not invent a new proof route that is not grounded in the available natural-language proof.
- Use `handoff.md` to lock the formal statement, imports, and the Lean proof route the proof worker should follow.

When you are done, reply with a brief plain-text note describing what you wrote.
