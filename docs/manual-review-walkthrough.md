# Manual Review Walkthrough

This is the literal Terry path for a human-reviewed Codex run on
`examples/inputs/right_add_zero.md`, which states `n + 0 = n`.

Run from the repo root after Lean and the Codex CLI are available:

1. Install Terry:
   `python3 -m pip install . --user`
2. Ensure the Terry script is on `PATH`:
   `export PATH="$(python3 -m site --user-base)/bin:$PATH"`
3. Start the run:
   `terry prove examples/inputs/right_add_zero.md --run-id right-add-zero`
4. Read the first checkpoint:
   `cat artifacts/runs/right-add-zero/01_enrichment/checkpoint.md`
5. Review the backend-written enrichment handoff:
   `cat artifacts/runs/right-add-zero/01_enrichment/handoff.md`
   If the backend wrote extra support files inside `01_enrichment/`, inspect those too.
6. Edit the enrichment review file so it begins with:
   `decision: approve`
7. Resume:
   `terry resume right-add-zero`
8. Read the plan checkpoint:
   `cat artifacts/runs/right-add-zero/02_plan/checkpoint.md`
9. Review the backend-written plan handoff:
   `cat artifacts/runs/right-add-zero/02_plan/handoff.md`
   If the backend wrote extra support files inside `02_plan/`, inspect those too.
10. Edit the plan review file so it begins with:
    `decision: approve`
11. Resume into the prove-and-repair loop:
    `terry resume right-add-zero`
12. If Terry reaches final approval directly, inspect:
    `cat artifacts/runs/right-add-zero/04_final/checkpoint.md`
    `cat artifacts/runs/right-add-zero/04_final/final_candidate.lean`
    `cat artifacts/runs/right-add-zero/04_final/compile_result.json`
13. If Terry blocks inside the proof loop instead, inspect:
    `cat artifacts/runs/right-add-zero/03_proof/checkpoint.md`
    `cat artifacts/runs/right-add-zero/03_proof/blocker.md`
    `cat artifacts/runs/right-add-zero/03_proof/loop.md`
    Then set `decision: retry` in `artifacts/runs/right-add-zero/03_proof/review.md`
    and run `terry resume right-add-zero`.
14. When the final checkpoint is open, set `decision: approve` in:
    `artifacts/runs/right-add-zero/04_final/review.md`
15. Finish the run:
    `terry resume right-add-zero`

At the end, the canonical output is:

- `artifacts/runs/right-add-zero/04_final/final.lean`

Useful status command:

- `terry status right-add-zero`

The example scripts under `examples/` still exist for deterministic or backend-specific
demo runs, but the intended human path is the Terry CLI plus the review files Terry
writes into the run directory. The important contract is no longer Terry-owned stage
JSON; it is the backend-owned handoff or candidate files that Terry points you at.
