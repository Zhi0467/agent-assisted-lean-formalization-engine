# Roadmap

Last updated: 2026-04-16 08:46 UTC

## Current Status

The repo is in the middle of a workflow rewrite on top of the new enrichment commit from
`main`. The old surface mixed four human gates, hidden `approve-*` commands, and a CLI
that still looked more like an internal scaffold than the intended Terry product. The
current rewrite changes that contract:

- the installable CLI is now `terry`
- the human path is `terry prove` plus `terry resume`
- the workflow has three approvals only: enrichment, merged plan, and final
- plan approval now locks both mathematical meaning and Lean theorem/proof plan together
- the proof phase is an explicit prove-and-repair loop between plan approval and final approval
- each checkpoint writes `checkpoint.md` plus `review.md`
- each run now has `logs/timeline.md` and `logs/workflow.jsonl`
- backend choice is persisted in the manifest, so resumed runs cannot silently swap providers
- template discovery is now part of the CLI contract rather than an implicit repo assumption

Local unit coverage for the rewritten surface is green, but the branch has not yet been
pushed through local review or Codex review. Until that review gate is clear, the rewrite
items stay open in `docs/backlog.md`.

## Milestone 1 — Terry CLI Contract

Success criteria:

- humans can run `terry prove` and `terry resume` without using hidden approval commands
- Terry writes the review artifacts humans need at each checkpoint
- the workflow logger is readable and complete enough to follow a run from disk

Gate:

- the rewritten CLI passes local tests and survives local review on a PR branch

### Activity Log

- [2026-04-16 08:46 UTC] Rebased work onto `origin/main` after the new enrichment commit landed and stopped building on the older dirty `murphy/codex-agent-backend` branch.
- [2026-04-16 08:46 UTC] Replaced the old four-gate CLI surface with the new Terry contract: `terry prove`, `terry resume`, review-file checkpoints, merged plan approval, and a readable workflow logger.
- [2026-04-16 08:46 UTC] Added depth-1 `lean_workspace_template` discovery plus fallback initialization through `lake new lean_workspace_template math`, with the shipped Terry scaffold overlaid onto the initialized project.
- [2026-04-16 08:46 UTC] Persisted backend configuration in the run manifest so resumed runs rebuild the original backend instead of guessing from current CLI flags.
- [2026-04-16 08:46 UTC] Refreshed the project docs around the Terry path and updated the examples/tests to exercise review files and `resume`, not hidden `approve-*` commands.
- [2026-04-16 08:46 UTC] Re-ran the local unit suite on the rewrite surface: `PYTHONPATH=src python3 -m unittest discover -s tests` (`16` tests, all passing).

## Milestone 2 — Real Proof Stress

Success criteria:

- a non-demo theorem forces at least one genuine repair attempt on the Terry surface
- the resulting artifact trail is readable enough that a human can audit the proof loop

Gate:

- at least one checked-in run proves a theorem only after seeing real compile feedback

## Milestone 3 — Richer Revision Control

Success criteria:

- enrichment and plan review can request changes through Terry rather than stopping at approval-only review files
- proof-loop diagnostics become more structured than the current stderr tail

Gate:

- at least one review-requested change is handled through Terry without manual artifact surgery
