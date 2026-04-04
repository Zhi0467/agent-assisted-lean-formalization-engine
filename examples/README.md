# Examples

`inputs/zero_add.md` plus `run_zero_add_demo.py` is the deterministic baseline path
through the scaffold.

`run_command_agent_demo.py` uses the same theorem input but routes all three agent turns
through an external command (`examples/providers/scripted_repair_provider.py`). The
shipped provider is still scripted, but it proves the real turn boundary and the bounded
compile-repair loop against the current artifact contract.
