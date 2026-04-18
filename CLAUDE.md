# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

- Install locally: `python3 -m pip install . --user` (then `export PATH="$(python3 -m site --user-base)/bin:$PATH"` if needed).
- Lean toolchain on PATH: `source "$HOME/.elan/env"`.
- Run the full test suite: `PYTHONPATH=src python3 -m unittest discover -s tests`.
- Run a single test module: `PYTHONPATH=src python3 -m unittest tests.test_demo_workflow`.
- Run a single test: `PYTHONPATH=src python3 -m unittest tests.test_codex_agent.TestCodexAgent.<method>`.
- Main CLI: `terry prove <source>`, `terry resume <run_id>`, `terry status <run_id>` (all accept `--workdir` / `--repo-root` before or after the subcommand).
- Example end-to-end demo without codex: see the `examples/run_*_demo.py` scripts (e.g. `run_command_agent_demo.py`, `run_zero_add_demo.py`).

## Architecture

Terry is a CLI-first orchestrator that drives a theorem source to a compiling Lean 4 file through five on-disk phases under `artifacts/runs/<run_id>/`:

1. `00_input/` normalized source + provenance (Terry owns).
2. `01_enrichment/` backend writes `handoff.md`; Terry writes `checkpoint.md` / `review.md` / `decision.json`.
3. `02_plan/` backend writes merged meaning + Lean statement in `handoff.md`; Terry writes review files.
4. `03_proof/attempts/attempt_<n>/candidate.lean` — bounded prove-and-repair loop. Terry compiles, persists diagnostics, retries up to the cap, and can open a blocked `handoff.md` with `decision: retry` when the cap is hit or the toolchain is unavailable.
5. `04_final/` compiling candidate plus the final approval review files.

The happy path has exactly three human approvals: enrichment, plan, final. `terry resume` parses `review.md`, records `decision.json`, logs the transition, and continues only when the expected decision value is present.

### Orchestrator/backend split

Terry owns run creation, ingestion, checkpoint + review files, proof-loop accounting, Lean compile invocation, and the manifest that makes resumed runs backend-stable. The backend (`demo`, `command`, or `codex`) owns *all* theorem content — enrichment, plan, Lean candidates — and writes it directly to the stage directory. Do **not** reintroduce Terry-owned theorem/plan/spec schemas, theorem parsing, JSON-only stage payloads, or Terry-authored summaries of theorem meaning. See `docs/orchestrator-contract.md` for the full list of what Terry must not own.

Each backend call receives only a narrow control-plane payload (stage name, run dir, output dir, prior-stage paths, attempt metadata, review-notes path). Theorem content travels through files only.

### Module map

- `cli.py` — `terry prove` / `resume` / `status`.
- `workflow.py` — state machine, checkpoint writing, review parsing, stage-output validation, prove-loop control.
- `agents.py` — file-first backend protocol (`run_stage(StageRequest) -> AgentTurn`).
- `demo_agent.py`, `subprocess_agent.py`, `codex_agent.py` — the three backend kinds persisted in the manifest.
- `template_manager.py` — depth-1 template discovery and `lake new ... math` bootstrap.
- `lean_runner.py` — shared `.terry/lean_workspace/` compile cache.
- `storage.py` — run-store helpers and workflow logging (`logs/timeline.md` + `logs/workflow.jsonl`).
- `models.py` — control-plane-only request/manifest/compile types (no theorem/plan schemas).

### Template + compile cache

`terry prove` searches the `--workdir` at depth 1 for a `lean_workspace_template/` containing the Terry scaffold (`FormalizationEngineWorkspace/Basic.lean` + `Generated.lean`) with mathlib. If none exists Terry runs `lake new ... math` and overlays the packaged scaffold; on the known `revision not found 'v4.29.1'` mathlib-mismatch failure Terry falls back to the packaged template and logs the stderr. Other `lake new` failures stop the run.

Compiles run inside the shared repo-local `.terry/lean_workspace/` (git-ignored) so `.lake` stays warm across runs. Terry only skips `lake update` when template deps are purely local path deps it can verify on disk; otherwise it reruns `lake update` and records the new manifest before compiling. Before each compile Terry overwrites only `FormalizationEngineWorkspace/Generated.lean` and clears that module's build outputs. If the template, vendored `.lake/` contents, or the toolchain behind `lake` changes, Terry rebuilds the cache; if `lake update` fails it drops the partial manifest so the next run retries cleanly.

### `--workdir`

`--workdir` (alias `--repo-root`) is the owning directory for `artifacts/`, `lean_workspace_template/`, and `.terry/lean_workspace/`. Pass it to `prove`, `resume`, and `status` when invoking from outside the project so they all land on the same run and cache.

## Project-specific conventions

- Python deps are managed via `pyproject.toml` with `uv`; update `pyproject.toml` when adding a dependency.
- Keep private vs public helpers in separate files; don't mix utility functions with CLI entry points.
- After a successful round of edits + tests, ask before pushing to GitHub.

## Key docs

- `docs/architecture.md` — workflow shape, logger, template handling, compile cache.
- `docs/orchestrator-contract.md` — the Terry-vs-backend boundary (read before changing workflow/persistence).
- `docs/manual-review-walkthrough.md` — literal CLI walkthrough.
- `docs/roadmap.md` / `docs/backlog.md` — milestone state and review-gated open tasks.
