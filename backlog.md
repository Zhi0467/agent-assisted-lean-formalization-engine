# Backlog

## Immediate Follow-Ups

- Run the Codex-backed path on a first non-demo theorem and check in that canonical artifact alongside the zero-add trace.
- Make the Codex-backed path the default CLI/backend surface for real runs while keeping the deterministic demo path explicit for examples and tests.
- Add an explicit retry/escalation policy so repeated compile failures cleanly route to plan revision, spec revision, or human intervention.
- Add a `ProofSession` interface for stepwise Lean interaction once the file-level compile-repair loop is stable.
- Add richer theorem examples beyond the deterministic `0 + n = n` demo.
- Extend PDF ingestion with optional `PyMuPDF` or `pypdf` adapters once dependency policy is settled.
- Decide whether long-term artifact storage should keep every run in Git or only selected canonical runs.
- Decide when to swap the file-copy Lean runner for a richer backend such as LeanInteract or PyPantograph.

## Controlled Repair Layer Follow-Ups

- Split theorem generation from compile-retry control instead of assuming one model owns the whole loop end to end.
- Add a bounded `ProofSession` or `RepairSession` layer that sits on top of theorem generation and owns the compile-diagnose-repair cycle.
- Replace single-file `LeanDraft` retries with a persisted workspace-patch attempt model so a run can repair both theorem code and theorem-specific harness code when needed.
- Keep the repo template as the default scaffold, but treat it as a run-local starting point rather than a permanently fixed wrapper.
- Restrict harness edits to the copied run workspace under `artifacts/runs/<run_id>/workspace/` so theorem-specific repairs do not mutate the checked-in template.
- Define the allowed repair surface explicitly. Initial candidates:
  `FormalizationEngineWorkspace/Generated.lean`, helper modules such as `Basic.lean` or new sibling modules, top-level import wiring, and possibly `lakefile.toml` if dependency edits are allowed.
- Decide whether package and dependency edits belong in the bounded repair loop for v1 or should remain a manual review boundary.
- Persist richer per-attempt artifacts for workspace repairs:
  requested actions, files changed, applied patch or file snapshots, rationale, compiler diagnostics, and stop reason.
- Add attempt-level guardrails for the repair controller:
  max iterations, max files touched, max new helper modules, and explicit disallow lists for repo-global edits.
- Evaluate controller backends separately from theorem-generation backends. The inner theorem model can stay specialized for Lean generation, while the outer repair controller may use a code-capable agent when multi-file edits are needed.
- Update the agent protocol to represent dual responsibility during repair:
  theorem drafting plus bounded workspace maintenance in response to Lean diagnostics.

## Lean-Side Follow-Ups

- Add import selection heuristics beyond the local basic workspace module.
- Distinguish parse and type errors from proof failures in compile diagnostics.
- Add a quality gate that checks for placeholders beyond the literal string `sorry`.
- Preserve machine-readable Lean diagnostics alongside the raw compiler logs so repair prompts can stay structured.

## Product Follow-Ups

- Add a reviewer-friendly summary artifact per run.
- Add source-span provenance for PDF snippets instead of normalized text only.
- Add a browser or notebook view for run artifacts.
