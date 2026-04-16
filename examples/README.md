# Examples

The human-facing surface is the Terry CLI, not the example scripts. The examples here are
backend and regression demos that exercise the same run contract Terry uses.

- `inputs/zero_add.md` — smallest shipped theorem source
- `inputs/right_add_zero.md` — manual-review theorem used in the walkthrough
- `run_zero_add_demo.py` — deterministic end-to-end demo with auto-approval
- `run_command_agent_demo.py` — same workflow routed through the scripted subprocess provider
- `run_codex_agent_demo.py` — same workflow routed through the live Codex backend
- `run_codex_manual_review_demo.py` — live Codex walkthrough that edits review files and resumes the run
- `providers/scripted_repair_provider.py` — scripted subprocess backend used by the command demo
