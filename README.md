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

## Human-In-The-Loop Flow

The engine is built around three explicit checkpoints:

1. approve the extracted theorem meaning,
2. approve the intended Lean target and imports,
3. approve the final compiling Lean candidate.

The demo auto-approves those checkpoints so the flow can run end to end.

The model-call surface is intentionally narrow:

- one turn to draft the theorem spec from source text,
- one turn to draft the Lean-facing formalization plan,
- then a bounded Lean-draft repair loop where compiler feedback drives repeated draft attempts.

That post-plan compile-repair loop is the core agentic object of the system. The shipped
demo keeps those turns deterministic so the repo can prove the workflow shape before a
real provider adapter is added.

## Key Docs

- `AGENTS.md` — project-specific working instructions
- `roadmap.md` — milestones and current status
- `backlog.md` — open follow-ups
- `docs/architecture.md` — module layout and run-state model
- `docs/landscape.md` — adjacent repos and products worth borrowing from
