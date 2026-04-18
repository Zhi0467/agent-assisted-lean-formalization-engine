# Roadmap

Last updated: 2026-04-18 03:17 UTC

## Current Status

The Terry rewrite is still the repo's main workflow surface, but the important change
since the merge pause is architectural rather than cosmetic: Terry no longer owns theorem
payload schemas, theorem parsing, or backend-facing plan objects. The current repo now
centers the orchestrator-only contract directly:

- the installable CLI is now `terry`
- the human path is `terry prove` plus `terry resume`
- the workflow has three approvals only: enrichment, merged plan, and final
- plan approval now locks the backend-owned merged theorem meaning / Lean plan handoff
- the proof phase is an explicit prove-and-repair loop between plan approval and final approval
- each checkpoint writes `checkpoint.md` plus `review.md`
- each run now has `logs/timeline.md` and `logs/workflow.jsonl`
- backend choice is persisted in the manifest, so resumed runs cannot silently swap providers
- template discovery is now part of the CLI contract rather than an implicit repo assumption
- fresh-root bootstrap now also covers the known mathlib revision mismatch by falling
  back to the packaged workspace template while logging the failed `lake` stderr into
  structured workflow details
- Terry now reuses a shared repo-local compile cache at `.terry/lean_workspace/` so the
  first theorem in a repo can warm mathlib once and later Terry runs reuse it
- the backend now writes `01_enrichment/handoff.md`, `02_plan/handoff.md`, and
  `03_proof/attempts/attempt_<n>/candidate.lean` directly
- Terry now stores only the narrow control-plane request / prompt / response beside those
  outputs, then validates that the required file exists before continuing

The final local verification surface on the merged head is now `107/107`, and that
suite is deliberately rewritten around the file-first contract rather than the removed
Terry-owned JSON payload layer. It covers the demo workflow, the subprocess repair loop,
the file-first stage request shape, legacy-resume compatibility, legacy compatibility
approvals after rejected review files, sandboxed Codex stage writes, template-pin
preservation after successful `lake new`, stale-proof-artifact cleanup on rerun, shared
compile-cache reuse across runs, template-triggered cache refresh, vendored-template
cache refresh, incomplete-vendored-tree repair, `lakefile.lean` vendored-template
support, in-place toolchain refresh behind the same `lake` path, fallback lock recovery,
best-effort cache-alias and git-exclude setup, the legacy pending-review-template
filters, explicit `--workdir` routing, sibling local path dependency mirroring,
ancestor-overlay cleanup, packed-ref vendored revisions, and nested vendored build-only
readiness checks. The targeted CLI e2e tests for the demo backend, the scripted command
backend, and the explicit workdir path still pass on fresh temp repo roots.

PR `#4` is merged into `main` now as `b352acc`, so Milestone 1 is closed again on the
shipped repo surface rather than a pending PR branch. The final cache-hardening pass
after the old review loop closed two more real recovery issues in `lean_runner.py`:
ancestor-overlay path dependencies now remove stale nested files instead of leaving old
modules behind in `.terry/`, and a partially deleted shared workspace now recopies
itself instead of being treated as reusable because `Basic.lean` happened to survive.
The merged head also keeps the earlier workdir/cache contract Wangzhi asked for:
`--workdir` is an alias for `--repo-root`, Terry accepts it before or after the
subcommand, and that chosen working directory owns `artifacts/`,
`lean_workspace_template/`, and `.terry/lean_workspace/`.

Final validation on the merged surface is now:

- `PYTHONPATH=src:. pytest -q` (`107/107` passing)
- targeted CLI e2e tests still pass:
  - `DemoWorkflowTest.test_cli_demo_backend_e2e`
  - `DemoWorkflowTest.test_cli_command_backend_e2e`
  - `DemoWorkflowTest.test_cli_demo_backend_e2e_accepts_workdir_after_subcommand`
- real same-`--workdir` Terry CLI e2e on two elementary analysis theorems:
  - `0 <= |x|` completed with `lake update` then `lake build`
  - `0 <= x^2` in the same working directory completed with `lake build` only
  - the shared `.terry/lean_workspace/.lake/packages/mathlib` cache stayed warm across
    those two runs

The review tool still never produced a final terminal message on its last detached rerun,
but that pass did not surface any new issue beyond the final two cache-recovery bugs
fixed before merge, and all live GitHub review threads on PR `#4` were resolved. The
next product work is no longer review closure; it is Milestone 2 on the merged surface.

## Milestone 1 — Terry CLI Contract

Status: complete on `main` as of merge commit `b352acc`.

Success criteria:

- humans can run `terry prove` and `terry resume` without using hidden approval commands
- Terry writes the review artifacts humans need at each checkpoint
- the workflow logger is readable and complete enough to follow a run from disk

Gate:

- the rewritten CLI passes local tests, survives real manual Terry e2e in a reusable
  working directory, and lands merged on `main`

### Activity Log

- [2026-04-18 03:17 UTC] Merged PR `#4` (`Reuse Terry Lean cache across runs`) into `main` as `b352acc` after one more detached bug pass and a real same-`--workdir` Terry CLI walk on two elementary analysis theorems. The first run (`0 <= |x|`) warmed the shared workspace with `lake update` then `lake build`; the second run (`0 <= x^2`) in the same directory finished with `lake build` only, which is the exact cache-reuse behavior Wangzhi asked for.
- [2026-04-18 03:17 UTC] The final code delta before merge was `428b4d4`, which closed two last shared-workspace recovery bugs: stale nested files under ancestor-overlay path dependencies are now removed before reuse, and a partially deleted `.terry/lean_workspace/` now recopies itself instead of limping into repeated broken builds. The full local test surface is now `107/107`, all live GitHub review threads on PR `#4` are resolved, and the project checkout was cleaned of untracked Terry test junk after the final e2e.
- [2026-04-18 01:09 UTC] Added the explicit Terry working-directory surface that Wangzhi asked for. `terry` now accepts `--workdir` as an alias for `--repo-root`, that flag can appear before or after the subcommand, status output now prints the working directory explicitly, and the README / manual walkthrough / architecture docs now explain that this directory owns `artifacts/`, `lean_workspace_template/`, and `.terry/lean_workspace/`.
- [2026-04-18 01:09 UTC] The next direct review loop stayed inside the shared-cache implementation and found one real P1: moving the workspace to `.terry/lean_workspace/` broke valid templates with sibling local path dependencies like `path = "../LocalDep"`. Terry now mirrors those local path dependencies into `.terry/` before build, and the suite covers that exact shape directly.
- [2026-04-18 01:09 UTC] The live PR Codex pass on `5c97c48` then surfaced two smaller vendored-cache checks that were still too loose: packed refs in vendored git repos could bypass revision matching, and nested `.lake/packages/*/build` artifacts could still count as source readiness. Both are fixed on `7b4bcfc`, both have dedicated regressions, and the suite is now `96/96`.
- [2026-04-18 01:09 UTC] The old open blocker at that point was review closure. That is no longer the product gate after the final manual pass and merge, but this note stays here as provenance for why PR `#4` paused before the last e2e/merge decision.
- [2026-04-17 22:02 UTC] The later review loops stayed entirely inside the new shared-cache contract and flushed out four more real edges there: build artifacts inside vendored packages were still being copied into `.terry/lean_workspace`, vendored-package completeness was being inferred from directory names alone, `lakefile.lean` templates were always forcing `lake update`, and dirty git-backed vendored packages could still leave the cache looking falsely clean. All four are now fixed in `lean_runner.py`.
- [2026-04-17 22:02 UTC] The branch-local suite is now `68/68` after adding direct regressions for nested vendored build-output stripping, incomplete vendored trees, dirty git-backed vendored packages, and `lakefile.lean` vendored-template support. The targeted CLI e2e tests still pass. The only remaining blocker on this branch is procedural rather than a reproduced runtime bug: the final detached local `codex review --base main` rerun is currently stalling after runtime probes instead of returning a clean or failing verdict.
- [2026-04-17 21:16 UTC] Tightened the shared-cache contract after the first cache review pass. Terry now fingerprints the real toolchain behind `lake` instead of only the executable path, and the template hash now includes vendored `.lake/` source state instead of blindly ignoring it. That closes the two false-reuse cases where the cache could otherwise survive a same-path toolchain upgrade or a vendored dependency edit inside `lean_workspace_template/`.
- [2026-04-17 21:16 UTC] Terry also stopped forcing `lake update` after every cache rebuild. If a rebuilt template already carries its own `lake-manifest.json` or vendored `.lake/packages/` state, Terry now trusts that pinned dependency surface instead of rewriting it; `lake update` is only automatic when the copied workspace has no manifest yet. The branch-local suite is now `64/64` after adding direct regressions for vendored-template cache refresh and same-path toolchain refresh, and the targeted CLI e2e tests still pass.
- [2026-04-17 20:33 UTC] Terry no longer compiles by copying a cache-stripped template into each run directory. `lean_runner.py` now keeps a shared repo-local workspace at `.terry/lean_workspace/`, runs `lake update` there once when the manifest is missing, preserves the warmed `.lake` state across Terry runs in the same repo, clears only the current theorem module's old build outputs before recompiling, and rebuilds the shared workspace when the template or the selected `lake` toolchain changes.
- [2026-04-17 20:33 UTC] Refreshed the test and doc surface around that change. The branch-local suite is now `62/62` after adding direct regressions for shared-workspace reuse, template-triggered cache refresh, toolchain-triggered cache refresh, attempt-anchored diagnostic path sanitization, and the non-`fcntl` shared-workspace lock fallback, the targeted CLI e2e tests still pass, and the README / architecture docs now describe the hidden `.terry/` compile cache honestly instead of the old run-local workspace copy.
- [2026-04-17 05:45 UTC] The final direct review loop on the orchestrator-only head found three last recovery/runtime bugs and they are now fixed too: resumed plan approvals now reopen an already-written `02_plan/` handoff instead of silently rerunning the backend, packaged-template runs keep the exact workspace recorded in the manifest instead of drifting to a new local template on resume, and proof-turn reruns now clear stale turn artifacts before calling the backend so a crashed `candidate.lean` cannot be mistaken for the retry output.
- [2026-04-17 05:45 UTC] The same review loop also tightened two repo-safety details on the Terry surface: the built-in Codex backend now writes inside a temp sandbox and only copies the stage output directory back into the real repo, and successful `lake new lean_workspace_template math` bootstraps now keep the generated Lean/mathlib version pins while still overlaying Terry's packaged workspace files. The full branch-local suite is now `57/57`, the targeted CLI e2e tests still pass, and the latest direct local `codex review --base main` came back clean with no actionable pre-merge bugs.
- [2026-04-17 05:15 UTC] The next direct review loop stayed entirely inside the legacy compatibility surface and flushed out three more real issues there: hidden old-command JSON was still emitting Terry stage names instead of the old stage vocabulary, `approve-enrichment` / `approve-plan` / `approve-final` could not recover rejected legacy review files because they were writing the wrong review surface, and untouched legacy `03_enrichment/review.md` / `06_plan/review.md` templates could still be fed back into the backend as fake human guidance on auto-approved or compatibility-driven resumes.
- [2026-04-17 05:15 UTC] Fixed all three legacy follow-ups, added direct regressions for each, and reran the full branch-local suite: `PYTHONPATH=src python3 -m unittest discover -s tests` is now `53/53`, while the targeted CLI e2e tests (`DemoWorkflowTest.test_cli_demo_backend_e2e` and `DemoWorkflowTest.test_cli_command_backend_e2e`) still pass on the same head. A fresh direct `codex review --base main` rerun is in flight on top of that patched surface.

- [2026-04-16 08:46 UTC] Rebased work onto `origin/main` after the new enrichment commit landed and stopped building on the older dirty `murphy/codex-agent-backend` branch.
- [2026-04-16 08:46 UTC] Replaced the old four-gate CLI surface with the new Terry contract: `terry prove`, `terry resume`, review-file checkpoints, merged plan approval, and a readable workflow logger.
- [2026-04-16 08:46 UTC] Added depth-1 `lean_workspace_template` discovery plus fallback initialization through `lake new lean_workspace_template math`, with the shipped Terry scaffold overlaid onto the initialized project.
- [2026-04-16 08:46 UTC] Persisted backend configuration in the run manifest so resumed runs rebuild the original backend instead of guessing from current CLI flags.
- [2026-04-16 08:46 UTC] Refreshed the project docs around the Terry path and updated the examples/tests to exercise review files and `resume`, not hidden `approve-*` commands.
- [2026-04-16 09:35 UTC] Re-ran the local unit suite on the rewrite surface: `PYTHONPATH=src python3 -m unittest discover -s tests` (`20` tests, all passing), plus a fresh-directory CLI smoke that still completed end to end.
- [2026-04-16 09:35 UTC] The first local review pass surfaced two real rewrite regressions and both are now fixed: legacy paused runs now import their old artifact paths / plan schema into Terry honestly, and proof-loop `decision: retry` now really means one extra attempt. A second local review pass is running against that patched branch.
- [2026-04-16 13:00 UTC] Three more local review rounds flushed out Terry migration and compatibility edges that only showed up on older runs: stale `latest_error` now clears after a successful retry, legacy command-backed runs preserve `--agent-command` in their resume instructions, untouched legacy spec-review runs now surface the real Terry review directory, and the restored old-provider `theorem_spec` alias now derives honest assumptions / conclusion / symbols from the extracted statement instead of placeholder fields.
- [2026-04-16 13:00 UTC] Re-ran the branch-local suite on the patched Terry head: `PYTHONPATH=src python3 -m unittest discover -s tests` (`52` tests, all passing). A fresh clean-shell `scripts/review_project.sh agent-assisted-lean-formalization-engine --base main` rerun is now the remaining local gate before opening the PR.
- [2026-04-16 14:00 UTC] The direct local review on the real Terry worktree found one last P2 compatibility regression: the repo still published the old `lean-formalize` entrypoint but had dropped the legacy `run`, `resume --run-id`, `status --run-id`, and `approve-*` commands. The fix keeps Terry as the documented CLI while restoring those old forms as hidden compatibility shims so existing automation does not break.
- [2026-04-16 14:00 UTC] Re-ran the CLI compatibility regressions plus the full branch-local suite after the shim landed: `PYTHONPATH=src python3 -m unittest discover -s tests` (`62` tests, all passing). One more direct `codex review --base main` rerun is now the remaining local gate before opening the PR.
- [2026-04-16 14:09 UTC] That rerun flushed out two smaller compatibility gaps inside the shim itself: the old global option ordering (`--agent-backend demo run ...`) was still getting overwritten by subparser defaults, and a resumed `--agent-command ...` override only affected the current turn instead of replacing the stale command stored in the manifest.
- [2026-04-16 14:09 UTC] Fixed both shim follow-ups and reran the branch-local suite: `PYTHONPATH=src python3 -m unittest discover -s tests` (`63` tests, all passing). Another direct `codex review --base main` pass is now the remaining local gate before opening the PR.
- [2026-04-16 14:16 UTC] The next direct local review found one more old-provider compatibility edge: when the informal theorem text also carried an explicit `Target statement:` line, the synthesized fallback `theorem_spec` conclusion could absorb the whole prose block instead of the target formula. The fallback parser now strips that line out of the prose read, uses it as the conclusion when present, and keeps the quantified sentence only for assumption inference.
- [2026-04-16 14:16 UTC] Re-ran the targeted legacy-`theorem_spec` regression plus the full branch-local suite after that parser fix: `PYTHONPATH=src python3 -m unittest discover -s tests` (`63` tests, all passing). One more direct `codex review --base main` pass is now the remaining local gate before opening the PR.
- [2026-04-16 14:26 UTC] The next review finally moved from parsing single-target statements to full legacy-consumer compatibility: the hidden legacy commands were still printing Terry prose summaries instead of the old JSON manifest contract, and the fallback theorem-spec binder inference was still dropping earlier variables in multi-binder statements like `m and n`.
- [2026-04-16 14:26 UTC] Restored JSON stdout on the legacy command surface, taught the fallback theorem-spec parser to emit every quantified binder, and reran the affected compatibility regressions plus the full branch-local suite: `PYTHONPATH=src python3 -m unittest discover -s tests` (`64` tests, all passing). One more direct `codex review --base main` pass is now the remaining local gate before opening the PR.
- [2026-04-16 14:56 UTC] The remaining local loop stayed in the legacy theorem-spec fallback rather than the Terry-facing workflow. The later direct reviews surfaced four more real binder spellings that older subprocess providers can send through that compatibility path: qualified binders (`positive integers m and n`), mixed descriptor+explicit type binders (`positive integers m and n : Int`), comma-separated binders (`m, n`), and repeated typed binders (`m : Nat, n : Nat` / `(m : Nat), (n : Nat)`).
- [2026-04-16 14:56 UTC] Tightened the fallback parser across those cases, added dedicated regressions for each, and reran the full branch-local suite after every step. The branch-local verification now sits at `71/71` via `PYTHONPATH=src python3 -m unittest discover -s tests`.
- [2026-04-16 14:56 UTC] The focused direct local Codex review on the final parser delta (`codex review -c 'mcp_servers.consult.command=\"\"' -c 'mcp_servers.slack.command=\"\"' --base 9bf0e54`) came back clean. The branch is now published as draft PR `#3` with `@codex` requested, so the remaining gate is the live PR review surface rather than another local rerun.
- [2026-04-16 19:42 UTC] The first live GitHub Codex pass on PR `#3` turned out to be reviewing older commit `49053f8`, and it surfaced two real issues in the legacy subprocess compatibility path: optional `draft_theorem_spec` probing still aborted on malformed soft-fail responses, and prime-suffixed binders like `n'` were still rejected by the fallback theorem-spec parser. I fixed both on the current branch.
- [2026-04-16 19:42 UTC] The direct local review on the actual Terry worktree then pushed further into that same migration stack and flushed out more honest compatibility issues: old plan payloads still needed adaptation into Terry's merged plan object, repo-relative `--lake-path` values needed to resolve against `--repo-root`, proof-loop human guidance was still being dropped after the first failed compile, migrated legacy stall approvals were not truly one-shot, resumed backend/model overrides were not fully persisted, hidden `approve-spec` still targeted the old spec checkpoint for Terry-native runs, and the legacy theorem-spec fallback still rejected Unicode binders like `α` and `β`. Those are now fixed too.
- [2026-04-16 19:42 UTC] Re-ran the full branch-local suite after the latest compatibility pass: `PYTHONPATH=src python3 -m unittest discover -s tests` (`87` tests, all passing). The latest direct local review on the real Terry worktree also came back clean, so the remaining open gate is the refreshed live PR review on the updated branch head rather than another local bug-hunt.
- [2026-04-16 20:12 UTC] A fresh no-template Terry smoke on `examples/inputs/right_add_zero.md` exposed one more real bootstrap failure in the CLI contract: `lake new lean_workspace_template math` can reach the live mathlib clone and then die with `revision not found 'v4.29.1'`, which meant a fresh repo still failed before the proof loop even started. Terry now treats that specific mathlib-revision mismatch as a packaged-template fallback instead of a hard stop, logs the failed `lake` output into structured workflow details, and keeps the run moving in the same repo.
- [2026-04-16 20:12 UTC] The first focused local review on that bootstrap delta then found two follow-ups and both are fixed now: non-recoverable `lake new` failures still raise immediately instead of limping into the proof loop, and multi-line `lake` diagnostics stay out of the one-line `logs/timeline.md` surface. The fallback path is now covered by a fresh Terry smoke plus dedicated template-resolution / CLI regressions, and the full branch-local suite is `90/90`.
- [2026-04-16 22:12 UTC] The later live GitHub Codex pass on `1a7761e` surfaced two smaller compatibility gaps outside the bootstrap patch: `terry resume` still rejected `--agent-backend` / `--codex-model` after the subcommand, and the legacy typed-binder fallback still dropped assumptions for Unicode type names like `ℕ`. Both are fixed now with parser and theorem-spec regressions.
- [2026-04-16 22:12 UTC] Re-ran the full branch-local suite after those last compatibility fixes: `PYTHONPATH=src python3 -m unittest discover -s tests` (`92` tests, all passing). The docs/backlog now treat the Terry rewrite gate as closed, so the next work starts at Milestone 2 rather than another review-only loop.
- [2026-04-16 22:16 UTC] During the final doc+merge pass, Wangzhi rejected the remaining Terry stage-schema design itself: each stage should be owned end to end by the chosen backend, with files as the interface, not Terry-authored parsing or theorem-spec synthesis.
- [2026-04-16 22:16 UTC] Paused the merge and mapped the current hardcoded surfaces that violate that rule: `models.py` / `agents.py` stage dataclasses, `codex_agent.py` JSON-schema output, `subprocess_agent.py` `parsed_output` plus fallback theorem parsing, and the Terry-authored extraction/enrichment/plan summaries in `workflow.py`. The next cut is to move actual formalization content fully behind the backend/file boundary.
- [2026-04-16 22:22 UTC] Wrote `docs/orchestrator-contract.md` to turn that merge blocker into a concrete target. The doc fixes the allowed Terry surface to run directories, review files, logs, template/bootstrap handling, and compile / retry control, while moving theorem understanding, enrichment, planning, and proof content fully into backend-owned stage files.
- [2026-04-17 02:07 UTC] Replaced the typed Terry/backend contract with a file-first stage request: `agents.py` now exposes a single stage runner, `models.py` now only carries orchestration types plus the narrow stage request object, and `workflow.py` now validates backend-written `handoff.md` / `candidate.lean` files instead of parsing Terry-owned theorem, enrichment, or plan payloads.
- [2026-04-17 02:07 UTC] Rewrote the built-in backends onto that contract. `codex_agent.py` now instructs `codex exec` to read prior files and write the required stage file inside the run directory, `subprocess_agent.py` now expects only a prompt/raw-response envelope while the provider writes files directly, and the demo / scripted provider paths now follow the same backend-owned file surface.
- [2026-04-17 02:07 UTC] Rewrote the validation surface to match the new architecture: `PYTHONPATH=src python3 -m unittest discover -s tests` is now `25/25` on a smaller file-contract suite, and both fresh CLI e2e paths pass on temp repo roots (`demo` happy path and command-backend repair path with `2` proof attempts). The fresh direct local `codex review --base main` run on this head is now the remaining Milestone 1 gate.
- [2026-04-17 02:07 UTC] The first direct review on the orchestrator-only cut found two real regressions and both are now fixed: auto-approved runs no longer advertise missing review files to backends, and paused legacy runs now stay on their legacy checkpoint surfaces until Terry can migrate them honestly. The suite is back to green after adding regressions for both fixes.
- [2026-04-17 03:48 UTC] The next direct review surfaced two more real workflow compatibility gaps and both are now fixed: reopened proof-blocked checkpoints now reset a consumed `decision: retry` review file back to `pending`, and legacy resumed runs now hand backends the real normalized-source path by falling back to `01_normalized/normalized.md` when `00_input/normalized.md` is absent.
- [2026-04-17 03:48 UTC] Re-ran the full branch-local suite plus a manual-review command-backend CLI smoke after those fixes: `PYTHONPATH=src python3 -m unittest discover -s tests` is now `47/47`, the fresh CLI path still completes after one explicit proof retry, and the fresh direct `codex review --base main` rerun is now the remaining Milestone 1 gate.

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
