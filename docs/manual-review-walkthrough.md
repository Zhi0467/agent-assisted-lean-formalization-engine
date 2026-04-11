# Manual Review Walkthrough

This is the explicit human-in-the-loop CLI path for a live Codex run. It uses the
checked-in theorem input `examples/inputs/right_add_zero.md`, which states `n + 0 = n`.

Run from the repo root after Lean and the Codex CLI are available:

1. Start the run:
   `PYTHONPATH=src python3 -m lean_formalization_engine run --source examples/inputs/right_add_zero.md --run-id cli-manual-right-add`
2. Inspect the drafted theorem spec:
   `cat artifacts/runs/cli-manual-right-add/02_spec/theorem_spec.json`
3. Record the human spec approval:
   `PYTHONPATH=src python3 -m lean_formalization_engine approve-spec --run-id cli-manual-right-add --notes "Spec matches the intended right-add-zero theorem and symbols."`
4. Resume into plan review:
   `PYTHONPATH=src python3 -m lean_formalization_engine resume --run-id cli-manual-right-add`
5. Inspect the drafted plan:
   `cat artifacts/runs/cli-manual-right-add/04_plan/formalization_plan.json`
6. Record the human plan approval:
   `PYTHONPATH=src python3 -m lean_formalization_engine approve-plan --run-id cli-manual-right-add --notes "Plan uses the expected import, theorem target, and Nat.add_zero proof route."`
7. Resume into final review:
   `PYTHONPATH=src python3 -m lean_formalization_engine resume --run-id cli-manual-right-add`
8. Inspect the compiling candidate and compile result:
   `cat artifacts/runs/cli-manual-right-add/08_final/final_candidate.lean`
   `cat artifacts/runs/cli-manual-right-add/06_compile/attempt_0001/result.json`
9. Record the human final approval:
   `PYTHONPATH=src python3 -m lean_formalization_engine approve-final --run-id cli-manual-right-add --notes "Final Lean file matches the intended theorem and compiles cleanly."`
10. Finish the run:
    `PYTHONPATH=src python3 -m lean_formalization_engine resume --run-id cli-manual-right-add`

At the end, the canonical output is:

- `artifacts/runs/cli-manual-right-add/08_final/final.lean`

To inspect the persisted state at any point:

- `PYTHONPATH=src python3 -m lean_formalization_engine status --run-id cli-manual-right-add`

The deterministic demo path remains available for tests and examples:

- `PYTHONPATH=src python3 examples/run_zero_add_demo.py`
- `PYTHONPATH=src python3 -m lean_formalization_engine --agent-backend demo run --source examples/inputs/zero_add.md --run-id demo-cli-zero-add --auto-approve`
