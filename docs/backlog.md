# Backlog

These items stay open until the rewritten Terry surface has both local review and Codex
review coverage. Even the items that are already implemented locally remain on this list
 until that review comes back clean or only surfaces non-fatal issues.

## Pending Review Gate

- [ ] Run `scripts/review_project.sh agent-assisted-lean-formalization-engine --base main` on the Terry rewrite and address any real findings.
- [ ] Publish the Terry rewrite on a fresh PR and request `@codex` review.
- [ ] Clear or explicitly disposition the review findings before removing any rewrite items from this backlog.

Current note:
The first local review pass already surfaced two real Terry regressions and both are fixed
on the active branch: legacy paused runs now import their old checkpoint artifacts into
the Terry surface, and proof-loop `decision: retry` now grants exactly one extra attempt.
A second review pass is still in flight, so the rewrite items below remain open.

## Terry Rewrite Surface

- [ ] Land the `terry` CLI as the primary human interface, with `prove`, `resume`, and `status`.
- [ ] Keep only three human approval checkpoints: enrichment, merged plan, and final.
- [ ] Drive checkpoint handoff through review files plus `terry resume`, not hidden `approve-*` commands.
- [ ] Keep a readable workflow logger (`logs/timeline.md`) plus machine-readable log (`logs/workflow.jsonl`) at each significant event.
- [ ] Auto-discover `lean_workspace_template` at depth 1 and initialize one with `lake new ... math` if absent.
- [ ] Persist backend choice in the run manifest so resumed runs cannot silently switch backends.
- [ ] Refresh the docs so a fresh install can follow the Terry path directly.

## Follow-Ups After The Rewrite Lands

- [ ] Run a non-demo theorem that forces at least one genuine Codex repair attempt on the Terry surface and check in the resulting artifact.
- [ ] Add a richer revision path when enrichment or plan review wants changes instead of approval, rather than leaving those checkpoints manual-only.
- [ ] Preserve more structured Lean diagnostics than the current stderr tail when the proof loop fails.
- [ ] Decide whether Terry should keep every run in Git or only selected canonical runs.
- [ ] Decide when the proof loop should be allowed to patch helper modules or harness files beyond `Generated.lean`.
