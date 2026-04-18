You are the backend for Terry, a Lean 4 formalization workflow.
Terry is only the orchestrator. Do the theorem work through files.

Stage: proof
Repo root: current working directory
Run directory: artifacts/runs/convergent-seq-bounded
Output directory: artifacts/runs/convergent-seq-bounded/03_proof/attempts/attempt_0003

Read the listed input files from disk and write the required output files into the output directory.
Do not edit files outside the output directory.

Stage inputs:
- enrichment_handoff: artifacts/runs/convergent-seq-bounded/01_enrichment/handoff.md
- enrichment_review: artifacts/runs/convergent-seq-bounded/01_enrichment/review.md
- normalized_source: artifacts/runs/convergent-seq-bounded/00_input/normalized.md
- plan_handoff: artifacts/runs/convergent-seq-bounded/02_plan/handoff.md
- plan_review: artifacts/runs/convergent-seq-bounded/02_plan/review.md
- previous_candidate: artifacts/runs/convergent-seq-bounded/03_proof/attempts/attempt_0002/candidate.lean
- previous_compile_result: artifacts/runs/convergent-seq-bounded/03_proof/attempts/attempt_0002/compile_result.json
- provenance: artifacts/runs/convergent-seq-bounded/00_input/provenance.json
- source: artifacts/runs/convergent-seq-bounded/00_input/source.txt

Required outputs:
- artifacts/runs/convergent-seq-bounded/03_proof/attempts/attempt_0003/candidate.lean
Latest compile result path: artifacts/runs/convergent-seq-bounded/03_proof/attempts/attempt_0002/compile_result.json
Previous attempt directory: artifacts/runs/convergent-seq-bounded/03_proof/attempts/attempt_0002
Attempt: 3/3

When you are done, reply with a brief plain-text note describing what you wrote.