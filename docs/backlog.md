# Backlog

The Terry rewrite gate is clear now. The last live GitHub Codex pass on PR `#3` only
surfaced two non-fatal P2 compatibility issues, and both are fixed on the current head.
Branch-local verification is `92/92`, so the rewrite review items below are closed. The
open blocker is no longer review cleanliness; it is the architecture correction below.

## Terry Rewrite Gate (Cleared)

- [x] Run direct local `codex review` on the Terry rewrite and address the real findings it surfaced.
- [x] Publish the Terry rewrite on a fresh PR and request `@codex` review.
- [x] Clear or explicitly disposition the review findings before removing any rewrite items from this backlog.

Current note:
The live GitHub Codex reviews on PR `#3` ended up exercising two different heads. The
older `49053f8` pass flushed out the optional `draft_theorem_spec` soft-fail handling and
prime-suffixed binder gaps, and the later `1a7761e` pass found two smaller follow-ups:
the `resume` subcommand still hid backend/model overrides, and the legacy typed-binder
fallback still rejected Unicode type names like `ℕ`. All four issues are fixed on the
current head. The later bootstrap-fallback patch for `revision not found 'v4.29.1'`
also stays in place, but Terry now records the full `lake` stderr in structured workflow
details while keeping the one-line timeline readable. Current local verification:
`PYTHONPATH=src python3 -m unittest discover -s tests` (`92` tests, all passing).

## Architecture Correction (Open)

- [ ] Remove Terry-owned stage-content schemas and theorem/parser logic so the chosen backend owns enrichment, planning, and proving end to end through files.

Current note:
After the final doc+merge pass, Wangzhi explicitly rejected the remaining schema-owned
design. The branch no longer has a review-cleanliness problem; it has a product-contract
problem. `models.py` / `agents.py` still define Terry-owned stage payloads,
`codex_agent.py` still forces JSON-schema output, `subprocess_agent.py` still expects
`parsed_output` and synthesizes fallback theorem logic, and `workflow.py` still renders
Terry-authored extraction/enrichment/plan summaries from those parsed objects. Merge is
paused until that content contract is replaced with backend-owned files plus Terry's
checkpoint / logging / compile-retry orchestration. The concrete target is now written in
`docs/orchestrator-contract.md`.

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
