# Backlog

Milestone 1 is merged on `main` now. PR `#4` landed as merge commit `b352acc`, so the
shared-cache follow-up is no longer a pending review surface. Terry now has the
cache-owning working-directory contract Wangzhi asked for (`--workdir` / `--repo-root`),
keeps the warmed Lean/mathlib state under `.terry/lean_workspace/`, mirrors valid local
path dependencies into that cache without escaping into repo-owned paths, rebuilds the
shared workspace when it is partially damaged, and degrades gracefully when convenience
steps like `.git/info/exclude` writes or alias symlink creation fail. The Milestone 1
backlog is clean.

Milestone 2's gate is now met as well. The repo now carries the exact nontrivial Terry
run under `artifacts/runs/convergent-seq-bounded/`, backed by
`examples/inputs/convergent_sequence_bounded.md`. That archived run needed all `3`
default proof attempts: attempts `1` and `2` failed on real Lean theorem-code issues,
and attempt `3` passed.

Current verification:

- `PYTHONPATH=src python3 -m unittest discover -s tests` (`114` tests, all passing)
- targeted CLI e2e tests still pass on the merged head:
  `DemoWorkflowTest.test_cli_demo_backend_e2e`
  `DemoWorkflowTest.test_cli_command_backend_e2e`
  `DemoWorkflowTest.test_cli_review_command_writes_attempt_artifacts`
  `DemoWorkflowTest.test_cli_retry_command_allows_one_more_attempt`
- `DemoWorkflowTest.test_cli_demo_backend_e2e_accepts_workdir_after_subcommand`
- real same-`--workdir` Terry CLI e2e on two elementary analysis theorems passed after
  the final cache hardening pass:
  - `0 <= |x|` finished with `lake update` then `lake build`
  - `0 <= x^2` in the same working directory finished with `lake build` only
  - the shared `.terry/lean_workspace/.lake/packages/mathlib` cache stayed warm between
    those runs
- the last detached bug pass on PR head `428b4d4` closed two final cache-recovery
  issues before merge:
  - stale nested files under ancestor-overlay path dependencies are now removed
  - a partially deleted shared workspace now recopies itself instead of being treated as
    reusable
- all live GitHub review threads on PR `#4` were resolved before merge, and the local
  project checkout was cleaned of untracked Terry test junk after the final e2e
- the first checked-in nontrivial Terry/Codex archive is now in the repo:
  - input: `examples/inputs/convergent_sequence_bounded.md`
  - run: `artifacts/runs/convergent-seq-bounded/`
  - final output: `artifacts/runs/convergent-seq-bounded/04_final/final.lean`

Open follow-ups:

- [ ] Decide whether Terry's default `3`-attempt proof budget should become a CLI-level knob instead of a code default.
- [ ] Decide whether final approval should add a second fresh-workspace verification pass instead of trusting one passing Terry compile.
- [ ] Build a small checked-in benchmark set beyond `convergent-seq-bounded` so proof-loop behavior is not judged from one theorem.
- [ ] Decide whether `proof_status.json` should grow a stricter provenance enum or stay as the current minimal control-plane gate.

## Orchestrator-Only Refactor

- [x] Remove Terry-owned stage-content schemas and theorem/parser logic so the chosen backend owns enrichment, planning, and proving end to end through files.
- [x] Replace the typed backend API with a file-first stage request that only passes directories, file paths, attempt metadata, and review-note paths.
- [x] Make the Codex and subprocess backends write `handoff.md` / `candidate.lean` directly instead of returning Terry-owned structured payloads.
- [x] Rewrite the docs and tests around backend-owned stage files rather than Terry-owned JSON summaries.
- [x] Run fresh direct `codex review --base main` on the orchestrator-only head and fix anything it finds before clearing this item.

Current note:
The current branch no longer routes theorem meaning through `models.py`, no longer asks
Codex for JSON-schema stage payloads, and no longer synthesizes theorem or plan content
inside `workflow.py`. The file contract from `docs/orchestrator-contract.md` is the live
implementation now: `01_enrichment/handoff.md`, `02_plan/handoff.md`, and
`03_proof/attempts/attempt_<n>/candidate.lean`. The last direct review loop found and
closed three final recovery/runtime issues on top of that refactor: plan resumes now
reuse an already-written `02_plan/` turn instead of silently rerunning the backend,
packaged-template runs keep their original workspace on resume instead of drifting to a
new local template, Codex now writes inside a temp sandbox so only the stage output dir
comes back to the real repo, successful `lake new` keeps its own Lean/mathlib pins, and
proof-turn reruns clear stale artifacts before retrying the backend. Terry now also
compiles through a shared repo-local cache at `.terry/lean_workspace/`, so later runs in
the same repo keep the warmed `.lake` state instead of redownloading mathlib into a
fresh per-run workspace. That cache now tracks vendored template `.lake/` contents and
the real toolchain identity behind `lake`, while still respecting templates that already
carry their own lockfile or vendored dependency state. The newest regressions now cover
same-path toolchain changes, vendored package edits, incomplete vendored trees, nested
vendored build-output stripping, dirty git-backed vendored packages, `lakefile.lean`
templates, explicit `--workdir` CLI routing, sibling local path dependencies, vendored
packed refs, nested vendored build-only trees, stale copied mirror removal after source
deletion, the safety guard that keeps multi-`..` path dependencies from rewriting
non-cache directories, nested sibling dependency mirroring behind symlinked cache
packages, and rebasing of valid multi-parent path dependencies into Terry's cache
layout. Milestone 1 is shipped; the next product work lives in `docs/roadmap.md` under
Milestones 2 and 3.
