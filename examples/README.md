# Examples

The human-facing surface is the Terry CLI, not the example scripts. The examples here are
backend and regression demos that exercise the same run contract Terry uses.

- `examples/inputs/zero_add.md` — smallest shipped theorem source
- `examples/inputs/right_add_zero.md` — manual-review theorem used in the walkthrough
- `examples/inputs/convergent_sequence_bounded.md` — college-level real-analysis theorem used by the first archived nontrivial Terry repair run
- `examples/run_zero_add_demo.py` — deterministic end-to-end demo with auto-approval
- `examples/run_command_agent_demo.py` — same workflow routed through the scripted subprocess provider
- `examples/run_codex_agent_demo.py` — same workflow routed through the live Codex backend
- `examples/run_codex_manual_review_demo.py` — live Codex walkthrough that edits review files and resumes the run
- `examples/providers/scripted_repair_provider.py` — scripted subprocess backend used by the command demo

For the full checked-in artifact trail of the nontrivial sequence-bounded proof, inspect
`artifacts/runs/convergent-seq-bounded/`.
