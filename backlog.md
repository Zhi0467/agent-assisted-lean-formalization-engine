# Backlog

## Immediate Follow-Ups

- Add a real LLM/provider adapter behind the `FormalizationAgent` protocol.
- Add explicit approval/resume CLI commands so a human can intervene between persisted stages.
- Add richer theorem examples beyond the deterministic `0 + n = n` demo.
- Extend PDF ingestion with optional `PyMuPDF` / `pypdf` adapters once dependency policy is settled.
- Decide whether long-term artifact storage should keep every run in Git or only selected canonical runs.

## Lean-Side Follow-Ups

- Add import selection heuristics beyond the core Lean prelude.
- Distinguish parse/type errors from proof failures in compile diagnostics.
- Add a `sorry`-free quality gate that also checks for placeholder terms beyond the literal string `sorry`.

## Product / UX Follow-Ups

- Add a browser or notebook view for run artifacts.
- Add a reviewer-friendly summary artifact per run.
- Add source-span provenance for PDF snippets instead of normalized text only.
