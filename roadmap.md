# Roadmap

Last updated: 2026-04-04 05:36 UTC

## Current Status

The repo now has a concrete v0 scaffold:

- typed Python engine under `src/`,
- runnable demo under `examples/`,
- persisted run artifacts under `artifacts/`,
- and a minimal Lean workspace template for compile checks.

The repo's core agentic object is now pinned more sharply than the first scaffold note
made it sound: spec, plan, then a bounded compile-repair loop. The generic external turn
boundary is still there via a subprocess-backed agent, and the live Codex path now has
two checked-in surfaces: an auto-approved zero-add run and a manual-review run on the
non-demo theorem `n + 0 = n`. That means the repo now proves both halves of the intended
workflow object: live model turns plus explicit human checkpoints on a real theorem path.
The next gate is to make Codex the default real-run backend in the CLI/runtime and then
push onto harder theorems that actually exercise repair quality.

## Milestone 1 — Lock the Engine Skeleton

Success criteria:

- the repo has a stable directory layout,
- the engine modules have explicit interfaces,
- the run state machine persists artifacts at each stage,
- a demo example exercises the full flow.

Gate:

- the demo produces a final Lean file and compile logs under `artifacts/runs/`.

### Activity Log

- [2026-04-03 10:25 UTC] Initialized the project surface around five durable directories: `src/`, `examples/`, `assets/`, `artifacts/`, and `lean_workspace_template/`.
- [2026-04-03 10:25 UTC] Chose Python for the v0 engine, using typed dataclasses and protocols instead of an agent framework.
- [2026-04-03 10:25 UTC] Added an approval-driven workflow scaffold with theorem-spec review, plan review, compile attempts, and final review.
- [2026-04-03 10:25 UTC] Added `docs/landscape.md` so the repo starts with explicit borrow-vs-rebuild guidance rather than an ungrounded agent loop.
- [2026-04-03 10:59 UTC] Synced the repo-local and packaged Lean workspace templates so both surfaces compile the same generated module path.
- [2026-04-03 10:59 UTC] Switched persisted source and final-output metadata to repo-relative paths so checked-in artifacts stay portable across machines.
- [2026-04-03 10:59 UTC] Athena standard consult confirmed the local direction: keep Python for v0, use a filesystem-backed state machine with explicit human gates, avoid a heavyweight agent framework, and add a `ProofSession` layer next. Immediate borrow targets are LeanInteract and PyPantograph, with LeanDojo-v2 as the broader later substrate. Full consult record: `.agent/runtime/consult_history/1775197696.768269.jsonl`.
- [2026-04-04 00:28 UTC] Tightened the project-language after Wangzhi's loop question: the core agentic surface is not generic "provider wiring" but the bounded post-plan Lean compile-repair cycle, where compiler diagnostics feed the next draft attempt until success, retry-cap stall, or escalation back to spec/plan review.
- [2026-04-04 00:28 UTC] Reordered the backlog so the first follow-ups center on the model-backed compile-repair loop, structured diagnostics, and explicit escalation policy before deeper interactive proof sessions.
- [2026-04-04 00:40 UTC] Fixed an actual repair-loop gap uncovered by the local review attempt: interrupted runs can now resume from `repairing`, and the workflow reloads the last persisted compile result so the next attempt still sees the prior compiler diagnostics. Added a regression test covering crash-then-resume behavior inside the compile-repair phase.
- [2026-04-04 03:15 UTC] Added a subprocess-backed agent adapter so theorem-spec, plan, and Lean-draft turns can already cross a real external command boundary without changing the run-state machine or artifact schema.
- [2026-04-04 03:15 UTC] Made repair context explicit in the agent protocol: the repeated draft turn now receives retry-budget state, the previous draft, and the previous compile result, and resumed runs reload both persisted artifacts before re-entering repair.
- [2026-04-04 03:15 UTC] Added a local command-agent demo plus regression coverage showing a provider can fail once, read the saved compile feedback, and repair the theorem on the next attempt.
- [2026-04-04 04:40 UTC] Merged PR `#1` on `main`, then tightened the core loop around the review findings: run IDs are now safe and unique, rejected final decisions cannot silently complete a run, stall review can explicitly grant one more repair attempt, and pre-compile provider crashes can resume from the persisted `created` surface instead of stranding the run.
- [2026-04-04 04:40 UTC] Added `CodexCliFormalizationAgent` as the first built-in live provider path. The CLI can now select `--agent-backend codex`, the repo ships a runnable `examples/run_codex_agent_demo.py`, and the engine still persists the same prompt/request/response artifacts as the demo and subprocess-backed paths.
- [2026-04-04 04:40 UTC] Ran the new live Codex path end to end on the smallest theorem object (`examples/inputs/zero_add.md`) and checked the resulting canonical artifact into the repo at `artifacts/runs/demo-codex-agent/`. That run compiled on the first attempt and preserved the same stage-by-stage trail as the scripted paths.
- [2026-04-04 05:03 UTC] Removed the stale wording that framed Codex-as-default as an open product choice. The remaining work is to implement Codex as the default real-run path and push it through a non-demo theorem, not to re-ask for direction that was already given in-thread.

## Milestone 2 — Add A Real Provider Adapter

Success criteria:

- an external provider can produce theorem specs, plans, and Lean drafts,
- prompts and responses are persisted without changing the artifact contract,
- compilation failures feed a bounded repair loop with explicit repair context,
- repeated repair failures escalate cleanly instead of silently thrashing.

Gate:

- at least one non-demo theorem runs through a live API-backed path with persisted prompts and diagnostics.

### Activity Log

- [2026-04-04 05:36 UTC] Simulated the full human-in-the-loop Codex path on a first non-demo theorem (`n + 0 = n`) without `--auto-approve`. The run paused at spec review, plan review, and final review in turn, accepted explicit human notes at each gate, compiled on the first attempt, and was checked into the repo at `artifacts/runs/demo-codex-manual-right-add/`.

## Milestone 3 — Improve Lean Context And Repair

Success criteria:

- the engine can choose imports more intelligently,
- the repair loop uses structured diagnostics rather than raw stderr only,
- auxiliary lemma generation can be turned on without changing the base pipeline.

Gate:

- at least one previously failing theorem is recovered by the repair loop without manual file editing.
