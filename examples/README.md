# Examples

The human-facing surface is the Terry CLI, not helper scripts. The examples here are
theorem inputs and provider fixtures that exercise the same run contract Terry uses.

- `examples/inputs/zero_add.md` — smallest shipped theorem source
- `examples/inputs/right_add_zero.md` — manual-review theorem used in the walkthrough
- `examples/inputs/convergent_sequence_bounded.md` — college-level real-analysis theorem used by the first archived nontrivial Terry repair run
- `examples/providers/scripted_repair_provider.py` — scripted subprocess backend fixture for command-backed runs and tests

For the full checked-in artifact trail of the nontrivial sequence-bounded proof, inspect
`artifacts/runs/convergent-seq-bounded/`.
