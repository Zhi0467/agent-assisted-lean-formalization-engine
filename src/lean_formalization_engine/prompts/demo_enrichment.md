Write the deterministic demo enrichment artifacts for `{theorem_name}`.

Required files in `{output_dir}`:
- `handoff.md`
- `natural_language_statement.md`
- `natural_language_proof.md`
- `proof_status.json`

Objective:
- confirm that the theorem already has an existing natural-language statement and proof in the input surface
- keep the demo prompt explicit about proof provenance rather than implying Terry authored the proof
- fail closed if that proof surface were ever missing
