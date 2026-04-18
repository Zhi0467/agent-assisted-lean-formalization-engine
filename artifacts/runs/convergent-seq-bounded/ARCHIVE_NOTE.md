# Archived Run Note

This directory is the checked-in archive of the first nontrivial Terry/Codex run on
merged `main` that genuinely needed repair turns before Lean accepted the proof.

- Source input is mirrored at `examples/inputs/convergent_sequence_bounded.md`.
- The original Terry execution happened in a scratch workdir on 2026-04-18 03:41 UTC to
  2026-04-18 04:05 UTC.
- To keep the committed example portable, only location-dependent control-plane metadata
  was normalized before check-in:
  - `manifest.json` source and template paths
  - `request.json` `repo_root`
  - checkpoint and workflow-log resume commands
- Proof attempts, backend prompts/responses, review decisions, compile logs, and the
  final Lean output are otherwise preserved from the original run.
- Build dependencies and shared caches remain excluded from Git, including `.terry/`,
  `.lake/`, and `build/`.
- If you want to compile `04_final/final.lean` manually outside Terry, restore the Lean
  dependency state first with `lake update` or by reusing Terry's warmed
  `.terry/lean_workspace/`. The tracked template intentionally omits downloaded
  mathlib/build state.
