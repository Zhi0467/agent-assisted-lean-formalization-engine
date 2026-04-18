# Artifacts

Workflow traces and generated outputs live here.

- `runs/` — one directory per engine run
- `canonical/` — future curated outputs worth keeping stable
- `runs/demo-zero-add/` — deterministic scaffold trace
- `runs/demo-command-agent/` — external-turn trace that repairs after one failed draft
- `runs/convergent-seq-bounded/` — first checked-in nontrivial Terry/Codex run; it reached a passing proof only on attempt `3`

Each run should preserve prompts, parsed outputs, generated Lean drafts, compile logs,
review decisions, and final approved files. Build caches can be ignored; the point is to
keep the decision-relevant artifacts in version control.

For `runs/convergent-seq-bounded/`, the original execution happened in a scratch Terry
workdir. The checked-in archive keeps the proof attempts, prompts, responses, reviews,
and compile logs intact, but normalizes location-dependent metadata to repo-relative
paths and still excludes build dependencies like `.terry/`, `.lake/`, and `build/`.
