# Agent-Assisted Lean Formalization Engine

This repo builds a CLI-first workflow for taking a theorem source and turning it into
compiling Lean 4 code. The human surface is `terry`: start a run with `terry prove`,
inspect the checkpoint files Terry writes into `artifacts/runs/<run_id>/`, edit the
review file for the active checkpoint, and continue with `terry resume`.

## Current Shape

- `src/lean_formalization_engine/` holds the engine, CLI, template resolver, and Lean runner.
- `examples/` holds theorem inputs plus runnable demo scripts for the demo, command, and Codex backends.
- `artifacts/runs/<run_id>/` is the system of record for each run: checkpoints, proof attempts, final artifacts, and logs.
- `lean_workspace_template/` is the Terry workspace scaffold. The CLI auto-discovers it at depth 1, and initializes one with `lake new ... math` if none is present.
- `docs/` holds the durable workflow contract, backlog, roadmap, and walkthroughs.

## Install

1. Install Lean:
   `curl https://elan.lean-lang.org/elan-init.sh -sSf | sh -s -- -y`
2. Put Lean on `PATH`:
   `source "$HOME/.elan/env"`
3. Install Terry:
   `python3 -m pip install . --user`
4. Put the user-site scripts directory on `PATH` if needed:
   `export PATH="$(python3 -m site --user-base)/bin:$PATH"`

## Quick Start

Start a run:

```bash
terry prove examples/inputs/right_add_zero.md --run-id right-add-zero
```

Terry pauses at three human checkpoints:

1. enrichment approval: scope and missing prerequisites
2. plan approval: mathematical meaning plus Lean theorem statement and proof plan
3. final approval: the compiling Lean candidate

At each pause Terry writes:

- `checkpoint.md` with the files to inspect and the exact resume command
- `review.md` where the human writes the decision and notes

After editing the review file, continue with:

```bash
terry resume right-add-zero
```

Use this if you want a quick summary of where a run stopped:

```bash
terry status right-add-zero
```

## Run Layout

Each run lives under `artifacts/runs/<run_id>/`:

- `00_input/` — original source text and provenance
- `01_enrichment/` — extraction, enrichment report, and enrichment checkpoint files
- `02_plan/` — merged meaning+plan checkpoint
- `03_proof/` — prove-and-repair attempts, run-local workspace, and proof-blocked handoff if needed
- `04_final/` — final candidate, final review files, and approved output
- `logs/` — readable `timeline.md` plus structured `workflow.jsonl`

## Docs

- `docs/manual-review-walkthrough.md` — literal CLI walkthrough
- `docs/architecture.md` — workflow, logger, checkpoints, and template handling
- `docs/backlog.md` — review-gated open tasks
- `docs/roadmap.md` — milestone status and dated activity log
