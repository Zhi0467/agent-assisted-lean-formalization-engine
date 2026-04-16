# Architecture

## Design Principles

- CLI-first: humans use `terry`, not Python approval helpers
- Three approval checkpoints: enrichment, merged plan, final
- Bounded prove-and-repair loop after plan approval
- Filesystem-first persistence: every checkpoint, attempt, and decision is on disk
- Readable logging: a human timeline plus a machine-readable event log

## Workflow Shape

Terry runs through five phases:

1. `00_input/`
   Normalized source text plus provenance
2. `01_enrichment/`
   Internal extraction artifact, enrichment report, human handoff, and enrichment review files
3. `02_plan/`
   The merged checkpoint that locks mathematical meaning, Lean theorem statement, imports, and proof sketch together
4. `03_proof/`
   The bounded prove-and-repair loop: draft Lean, compile, persist diagnostics, retry if needed
5. `04_final/`
   The compiling candidate, final review files, and the approved final Lean file

The only human approvals Terry expects on the happy path are:

- enrichment approval
- plan approval
- final approval

The proof loop can open one extra blocked handoff when it hits the retry cap or the Lean
toolchain is unavailable. That handoff lives under `03_proof/` and uses `decision: retry`
instead of `decision: approve`.

## Review Files

Each human checkpoint writes two files:

- `checkpoint.md`
  What to inspect, where to write the review, and the exact `terry resume <run_id>` command
- `review.md`
  Human-edited decision file

The review file is intentionally simple:

```text
decision: approve

Notes:
- review notes here
```

For proof-loop retries the decision is `retry` instead of `approve`.

`terry resume` parses `review.md`, records the result into `decision.json`, logs the
handoff, and continues only when the expected decision value is present.

## Logging

Every run writes:

- `logs/workflow.jsonl`
  Structured event stream
- `logs/timeline.md`
  Human-readable chronological log

Events include:

- run start
- extraction ready
- enrichment ready
- checkpoint open / approval
- proof loop start
- proof attempt start / failure / success
- proof blocked
- final candidate ready
- run completion

## Module Layout

- `src/lean_formalization_engine/cli.py`
  `terry prove`, `terry resume`, and `terry status`
- `src/lean_formalization_engine/workflow.py`
  State machine, checkpoint writing, review parsing, and prove-loop control
- `src/lean_formalization_engine/template_manager.py`
  Depth-1 template discovery and `lake new ... math` initialization
- `src/lean_formalization_engine/lean_runner.py`
  Run-local workspace copy plus compile checks
- `src/lean_formalization_engine/storage.py`
  Run-store helpers and workflow logging
- `src/lean_formalization_engine/agents.py`
  Agent protocol
- `src/lean_formalization_engine/demo_agent.py`
  Deterministic baseline backend
- `src/lean_formalization_engine/subprocess_agent.py`
  External provider command backend
- `src/lean_formalization_engine/codex_agent.py`
  `codex exec` backend

## Template Discovery

`terry prove` searches the current project root at depth 1 for an eligible
`lean_workspace_template/` directory. A template is eligible when:

- it contains the Terry scaffold files (`FormalizationEngineWorkspace/Basic.lean` and `Generated.lean`)
- its Lean project includes `mathlib`

If none is found, Terry runs `lake new lean_workspace_template math` with a long timeout
and then overlays the shipped Terry workspace scaffold onto that new directory. If that
bootstrap fails with the known mathlib revision mismatch (`revision not found 'v4.29.1'`),
Terry falls back to the packaged workspace template, records the full `lake` stderr in
the structured workflow log, and continues. Other `lake new` failures still stop the run.

## Backend Persistence

The run manifest now records:

- backend kind (`demo`, `command`, or `codex`)
- resolved subprocess command when Terry is using the command backend
- optional Codex model override
- template directory used for the run

That makes resumed runs backend-stable: `terry resume` rebuilds the agent from the
manifest instead of guessing from the current CLI flags.
