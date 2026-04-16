# Backlog

These items stay open until the rewritten Terry surface has both local review and Codex
review coverage. Even the items that are already implemented locally remain on this list
 until that review comes back clean or only surfaces non-fatal issues.

## Pending Review Gate

- [x] Run direct local `codex review` on the Terry rewrite and address the real findings it surfaced.
- [x] Publish the Terry rewrite on a fresh PR and request `@codex` review.
- [ ] Clear or explicitly disposition the review findings before removing any rewrite items from this backlog.

Current note:
The first live GitHub Codex pass on draft PR `#3` reviewed older commit `49053f8` and
surfaced two real compatibility bugs in the legacy subprocess path: optional
`draft_theorem_spec` probing was still too brittle for soft-fail providers, and
prime-suffixed binders like `n'` were still rejected by the fallback parser. The later
direct local review on the actual Terry checkout flushed out a few more honest gaps on
top of that same stack: legacy plan payloads still needed adaptation, repo-relative
`--lake-path` overrides needed to anchor against `--repo-root`, Terry was dropping human
plan-review guidance after the first failed compile, migrated legacy stall approvals were
not truly one-shot, and resume-time backend/model overrides were still too easy to lose.

Those issues are now fixed on the current branch head, along with Unicode binder support
for the same legacy fallback. One more fresh-root Terry smoke then exposed a real
bootstrap failure too: on this machine, `lake new lean_workspace_template math` can die
with `revision not found 'v4.29.1'` before the proof loop ever starts. Terry now treats
that as a packaged-template fallback instead of a hard stop, logs the failed `lake`
output into the workflow timeline, and keeps going in the same fresh repo. The
branch-local suite is `90/90`, and the bootstrap-fallback delta is now covered by a
fresh real Terry smoke plus dedicated template-resolution / CLI regressions. This backlog
still stays open until the refreshed live PR review on the updated head either comes back
clean or only finds non-fatal follow-ups.

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
