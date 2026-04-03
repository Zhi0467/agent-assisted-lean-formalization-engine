# Backlog

## Immediate Follow-Ups

- Add a real LLM/provider adapter behind the `FormalizationAgent` protocol.
- Add richer theorem examples beyond the deterministic `0 + n = n` demo.
- Extend PDF ingestion with optional `PyMuPDF` or `pypdf` adapters once dependency policy is settled.
- Decide whether long-term artifact storage should keep every run in Git or only selected canonical runs.
- Decide when to swap the file-copy Lean runner for a richer backend such as LeanInteract or PyPantograph.

## Lean-Side Follow-Ups

- Add import selection heuristics beyond the local basic workspace module.
- Distinguish parse and type errors from proof failures in compile diagnostics.
- Add a quality gate that checks for placeholders beyond the literal string `sorry`.

## Product Follow-Ups

- Add a reviewer-friendly summary artifact per run.
- Add source-span provenance for PDF snippets instead of normalized text only.
- Add a browser or notebook view for run artifacts.
