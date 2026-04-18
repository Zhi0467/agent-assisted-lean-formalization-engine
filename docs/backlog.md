# Backlog

The architecture correction is implemented on the current head now: Terry is back to
workflow orchestration only, the built-in backends write stage files directly, and the
old Terry-owned theorem/parsing layer is gone. The remaining blocker is no longer a
known architecture gap in Terry itself but the review gate on the shared-cache follow-up.
The current branch fixed the latest concrete cache/runtime findings too: same-repo runs
now have an explicit `--workdir` / `--repo-root` CLI surface, sibling local path
dependencies are mirrored into `.terry/` so shared-cache relocation does not break
`path = "../..."`, stale copied mirrors are removed when the real source disappears,
path-dependency mirrors are constrained to Terry-owned `.terry/` paths instead of
escaping into repo or parent directories, nested sibling deps behind symlinked mirrors
now stay mirrored correctly, multi-parent path dependencies like `../../Shared` are
rebased into Terry's cache layout instead of regressing valid templates, vendored packed
refs are read correctly, and nested vendored build garbage no longer counts as source
readiness. The backlog is still open because the review gate is blocked at the tooling
layer now: the detached local `codex review --base main` rerun is again non-terminal,
and GitHub `@codex review` on this repo now replies that a Codex environment must be
created before live review can run.

Current verification:

- `PYTHONPATH=src python3 -m unittest discover -s tests` (`100` tests, all passing)
- targeted CLI e2e tests still pass on the current head:
  `DemoWorkflowTest.test_cli_demo_backend_e2e`
  `DemoWorkflowTest.test_cli_command_backend_e2e`
- new workdir/cache e2e also passes on the current head:
  `DemoWorkflowTest.test_cli_demo_backend_e2e_accepts_workdir_after_subcommand`
- direct local `codex review --base main` on current head `7c1c945` is still unresolved:
  the latest local rerun did flush out and justify two more path-layout regressions, and
  those fixes are now in `7c1c945`, but the next rerun is again hanging without a final
  clean/fail verdict
- live GitHub `@codex review` is blocked on repo setup:
  the latest PR comments got the bot reply `create an environment for this repo`, so the
  live review surface is not currently usable until that environment exists

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
layout. The next product work still lives in `docs/roadmap.md` under Milestones 2 and
3, but this cache branch is not review-closed yet.
