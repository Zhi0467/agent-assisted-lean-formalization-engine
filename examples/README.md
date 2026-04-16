# Examples

`inputs/zero_add.md` plus `run_zero_add_demo.py` is the deterministic baseline path
through the scaffold.

`run_command_agent_demo.py` uses the same theorem input but routes all three agent turns
through an external command (`examples/providers/scripted_repair_provider.py`). The
shipped provider is still scripted, but it proves the real turn boundary and the bounded
compile-repair loop against the current artifact contract.

`run_codex_agent_demo.py` uses the same theorem input but replaces the scripted provider
with a live `codex exec` backend. It keeps the same persisted artifact contract, but it
requires a working Codex CLI login.

`run_codex_manual_review_demo.py` formalizes a different theorem (`n + 0 = n`) through
the same live Codex backend without `--auto-approve`. It stops at enrichment, spec,
plan, and final review in turn, then records explicit human approval notes before
resuming each stage.
