# Project: Agent-Assisted Lean Formalization Engine

Scaffold for an agentic workflow that turns theorem sources into compiling Lean 4 code.
Current focus: keep the scaffold surface stable while making the bounded post-plan
compile-repair loop and model-call surface explicit.

## Key Docs

- `roadmap.md` — milestones, gates, activity log
- `backlog.md` — open tasks and follow-ups
- `docs/README.md` — index into architecture and landscape notes

## Sub-Session Instructions

- Example run: `PYTHONPATH=src python3 examples/run_zero_add_demo.py`
- Optional install: `python3 -m pip install . --user`
- Tests: `PYTHONPATH=src python3 -m unittest discover -s tests`
- Lean tools: `source "$HOME/.elan/env"`
- Do not communicate on Slack from inside the project repo

## Context Loading

- New to this project? Read `roadmap.md` then `docs/README.md`
- Changing engine contracts? Read `docs/architecture.md`
- Comparing against existing systems? Read `docs/landscape.md`
