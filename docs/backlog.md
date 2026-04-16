# Backlog

These items stay open until the rewritten Terry surface has both local review and Codex
review coverage. Even the items that are already implemented locally remain on this list
 until that review comes back clean or only surfaces non-fatal issues.

## Pending Review Gate

- [x] Run direct local `codex review` on the Terry rewrite and address the real findings it surfaced.
- [x] Publish the Terry rewrite on a fresh PR and request `@codex` review.
- [ ] Clear or explicitly disposition the review findings before removing any rewrite items from this backlog.

Current note:
The wide local-review loop flushed out a long tail of migration and old-provider
compatibility bugs on `murphy/terry-three-stage`, and they are now fixed on the published
branch. The last parser cleanup covered qualified binders, mixed descriptor+explicit type
forms, comma-separated binders, and repeated typed binders for the synthesized legacy
`theorem_spec` fallback. The branch-local suite is now `71/71`, the focused direct local
review on the final delta (`codex review ... --base 9bf0e54`) came back clean, and draft
PR `#3` is now open with `@codex` requested. The remaining open gate is the live PR
review surface, not another local compatibility rerun.

## Terry Rewrite Surface

- [x] Land the `terry` CLI as the primary human interface, with `prove`, `resume`, and `status`.
- [x] Keep only three human approval checkpoints: enrichment, merged plan, and final.
- [x] Drive checkpoint handoff through review files plus `terry resume`, not hidden `approve-*` commands.
- [x] Keep a readable workflow logger (`logs/timeline.md`) plus machine-readable log (`logs/workflow.jsonl`) at each significant event.
- [x] Auto-discover `lean_workspace_template` at depth 1 and initialize one with `lake new ... math` if absent.
- [x] Persist backend choice in the run manifest so resumed runs cannot silently switch backends.
- [x] Refresh the docs so a fresh install can follow the Terry path directly.

## Follow-Ups After The Rewrite Lands

- [ ] Run a non-demo theorem that forces at least one genuine Codex repair attempt on the Terry surface and check in the resulting artifact.
- [ ] Add a richer revision path when enrichment or plan review wants changes instead of approval, rather than leaving those checkpoints manual-only.
- [ ] Preserve more structured Lean diagnostics than the current stderr tail when the proof loop fails.
- [ ] Decide whether Terry should keep every run in Git or only selected canonical runs.
- [ ] Decide when the proof loop should be allowed to patch helper modules or harness files beyond `Generated.lean`.
