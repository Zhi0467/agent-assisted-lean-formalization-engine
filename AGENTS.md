# Project: Agent-Assisted Lean Formalization Engine

CLI-first engine for turning theorem sources into compiling Lean 4 code with explicit
human checkpoints. Current focus: strip Terry down to workflow orchestration only so the
chosen backend owns enrichment, planning, and proving end to end through files, then
stress that surface on a non-demo theorem with a real repair turn.

## Key Docs

- `docs/roadmap.md` — current milestone state and activity log
- `docs/backlog.md` — open tasks and review-gated follow-ups
- `docs/architecture.md` — workflow shape, run layout, logger, and template rules
- `docs/orchestrator-contract.md` — target workflow/backend boundary after the merge pause
- `docs/manual-review-walkthrough.md` — literal `terry prove` / `terry resume` path

## Sub-Session Instructions

- Install: `python3 -m pip install . --user`
- PATH helper: `export PATH="$(python3 -m site --user-base)/bin:$PATH"`
- Main CLI: `terry prove ...`, `terry resume ...`, `terry status ...`
- Tests: `PYTHONPATH=src python3 -m unittest discover -s tests`
- Lean tools: `source "$HOME/.elan/env"`
- Do not communicate on Slack from inside the project repo

## Context Loading

- New to this project? Read `docs/roadmap.md` then `docs/README.md`
- Changing workflow or persistence? Read `docs/architecture.md` then `docs/orchestrator-contract.md`
- Updating the user-facing CLI path? Read `docs/manual-review-walkthrough.md`
- Need adjacent-system context? Read `docs/landscape.md`
