# Artifacts

Workflow traces and generated outputs live here.

- `runs/` — one directory per engine run
- `canonical/` — future curated outputs worth keeping stable
- `runs/demo-zero-add/` — deterministic scaffold trace
- `runs/demo-command-agent/` — external-turn trace that repairs after one failed draft

Each run should preserve prompts, parsed outputs, generated Lean drafts, compile logs,
review decisions, and final approved files. Build caches can be ignored; the point is to
keep the decision-relevant artifacts in version control.
