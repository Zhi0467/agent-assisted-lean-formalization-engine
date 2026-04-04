# Agent-Assisted Lean Formalization Engine

This repository contains a scaffold for an agentic engine that turns a theorem source
(PDF snippet, Markdown, or LaTeX) into Lean 4 code, with explicit human checkpoints and
persisted workflow artifacts.

## Repo Layout

- `src/lean_formalization_engine/` — typed engine package, CLI, state machine, and Lean runner
- `examples/` — runnable example inputs and demo entrypoints
- `assets/` — presentation material and future slide assets
- `artifacts/` — persisted run traces, prompts, parsed outputs, and generated Lean files
- `lean_workspace_template/` — minimal Lean workspace copied into each run before compilation
- `docs/` — durable architecture notes and nearby systems worth borrowing from

## Why Python For v0

The initial scaffold uses Python because it is the fastest path to combine:

- text and PDF ingestion,
- explicit typed contracts,
- simple provider adapters,
- subprocess orchestration for Lean,
- and a readable artifact trail instead of a hidden agent framework.

The code keeps boundaries typed with dataclasses and protocols so the engine does not
collapse into an untyped scripting surface.

## Quick Start

1. Install Lean:
   `curl https://elan.lean-lang.org/elan-init.sh -sSf | sh -s -- -y`
2. Ensure `lean` and `lake` are on your `PATH`:
   `source "$HOME/.elan/env"`
3. Run the demo from the repo root:
   `PYTHONPATH=src python3 examples/run_zero_add_demo.py`
4. Optional installed CLI surface:
   `python3 -m pip install . --user`
5. Run the external-turn demo locally:
   `PYTHONPATH=src python3 examples/run_command_agent_demo.py`
6. Run the live Codex-backed demo locally:
   `PYTHONPATH=src python3 examples/run_codex_agent_demo.py`
7. Run the explicit human-review Codex demo locally:
   `PYTHONPATH=src python3 examples/run_codex_manual_review_demo.py`

The demo writes a full run record in this repo under `artifacts/runs/demo-zero-add/`,
including:

- normalized source,
- drafted theorem spec,
- formalization plan,
- generated Lean file,
- compile logs,
- final review artifacts.

The packaged CLI falls back to the same Lean workspace template shipped inside
`src/lean_formalization_engine/workspace_template/`, so repo-local and installed runs share
the same compile surface.

The CLI can also swap the demo stub for an external turn provider without changing the
run-state machine:

`PYTHONPATH=src python3 -m lean_formalization_engine --agent-command "python3 examples/providers/scripted_repair_provider.py" run --source examples/inputs/zero_add.md --run-id cli-command-demo --auto-approve`

The checked-in command-backed example run lives under
`artifacts/runs/demo-command-agent/`.
The checked-in live Codex-backed example run lives under
`artifacts/runs/demo-codex-agent/`.
The checked-in manual-review Codex run on `n + 0 = n` lives under
`artifacts/runs/demo-codex-manual-right-add/`.

Each run ID is treated as a durable artifact object under `artifacts/runs/`, so starting
another run with the same ID fails instead of silently reusing old approvals or
overwriting the older record.

For a live backend, the CLI can now use Codex directly without going through a separate
provider script:

`PYTHONPATH=src python3 -m lean_formalization_engine --agent-backend codex run --source examples/inputs/zero_add.md --run-id codex-cli-demo --auto-approve`

## Human-In-The-Loop Flow

The engine is built around three explicit checkpoints:

1. approve the extracted theorem meaning,
2. approve the intended Lean target and imports,
3. approve the final compiling Lean candidate.

The deterministic, command-backed, and first Codex demo auto-approve those checkpoints so
the flow can run end to end.

`examples/run_codex_manual_review_demo.py` exercises the same live Codex path without
`--auto-approve`: it waits at spec review, plan review, and final review, records explicit
human notes at each gate, then resumes the run. The current checked-in manual-review
artifact also captures a real repair turn: the first draft fails the Lean compile gate,
the saved diagnostics flow into attempt 2, and the repaired file passes.

The model-call surface is intentionally narrow:

- one turn to draft the theorem spec from source text,
- one turn to draft the Lean-facing formalization plan,
- then a bounded Lean-draft repair loop where compiler feedback drives repeated draft attempts.

That post-plan compile-repair loop is the core agentic object of the system. The shipped
demo keeps those turns deterministic so the repo can prove the workflow shape before a
live API-backed provider is added. The subprocess adapter still pins the generic boundary,
and the repo now also ships a first built-in live provider path through `codex exec`.
Both surfaces preserve the same persisted prompts, parsed outputs, repair context, and
compile artifacts.

If Lean was missing, `resume` retries the same stalled run after the toolchain is
installed. If the run stalled on the retry cap, `approve-stall` records the explicit
human decision to allow one more repair attempt on the same artifact trail.

## Key Docs

- `AGENTS.md` — project-specific working instructions
- `roadmap.md` — milestones and current status
- `backlog.md` — open follow-ups
- `docs/architecture.md` — module layout and run-state model
- `docs/landscape.md` — adjacent repos and products worth borrowing from
