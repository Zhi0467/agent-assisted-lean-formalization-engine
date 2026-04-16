# Backlog

These items stay open until the rewritten Terry surface has both local review and Codex
review coverage. Even the items that are already implemented locally remain on this list
 until that review comes back clean or only surfaces non-fatal issues.

## Pending Review Gate

- [ ] Run `scripts/review_project.sh agent-assisted-lean-formalization-engine --base main` on the Terry rewrite and address any real findings.
- [ ] Publish the Terry rewrite on a fresh PR and request `@codex` review.
- [ ] Clear or explicitly disposition the review findings before removing any rewrite items from this backlog.

Current note:
The local review gate kept surfacing compatibility regressions on the active Terry branch,
and each one is now fixed on `murphy/terry-three-stage`: legacy paused runs migrate into
the Terry checkpoint surface honestly, command-backed resumes preserve their
`--agent-command` instructions, successful proof retries clear stale `latest_error`,
legacy status views point at the real review directories, and the old subprocess-provider
`theorem_spec` alias now carries honest assumptions / conclusion / symbols. The branch-local
suite is currently `52/52`, and a fresh clean-shell review rerun is still in flight, so
the rewrite items below remain open.

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
