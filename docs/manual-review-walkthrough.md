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
   `cat artifacts/runs/right-add-zero/01_enrichment/natural_language_statement.md`
   `cat artifacts/runs/right-add-zero/01_enrichment/proof_status.json`
   `cat artifacts/runs/right-add-zero/01_enrichment/natural_language_proof.md`
   If the backend wrote extra support files inside `01_enrichment/`, inspect those too.
6. Approve the enrichment handoff and continue:
   `terry resume right-add-zero --approve`
   Only edit `artifacts/runs/right-add-zero/01_enrichment/review.md` (setting
   `decision: approve` or `decision: reject` and filling in notes) if you need to
   leave reviewer comments or reject the handoff; in that case run
   `terry resume right-add-zero` afterwards.
7. Read the plan checkpoint:
   `cat artifacts/runs/right-add-zero/02_plan/checkpoint.md`
8. Review the backend-written plan handoff:
   `cat artifacts/runs/right-add-zero/02_plan/handoff.md`
   If the backend wrote extra support files inside `02_plan/`, inspect those too.
9. Approve the plan and enter the prove-and-repair loop:
   `terry resume right-add-zero --approve`
   Same rule as before: only edit `02_plan/review.md` when you need to leave notes
   or reject the plan.
10. Terry now writes review artifacts for every proof attempt. For the latest one, inspect:
    `cat artifacts/runs/right-add-zero/03_proof/attempts/attempt_0001/review/walkthrough.md`
    `cat artifacts/runs/right-add-zero/03_proof/attempts/attempt_0001/review/error.md`
    `cat artifacts/runs/right-add-zero/03_proof/attempts/attempt_0001/review/readable_candidate.lean`
    You can rerun that worker explicitly with:
    `terry review right-add-zero --attempt 1`
11. If Terry reaches final approval directly, inspect:
    `cat artifacts/runs/right-add-zero/04_final/checkpoint.md`
    `cat artifacts/runs/right-add-zero/04_final/final_candidate.lean`
    `cat artifacts/runs/right-add-zero/04_final/compile_result.json`
12. If Terry blocks inside the proof loop instead, inspect:
    `cat artifacts/runs/right-add-zero/03_proof/checkpoint.md`
    `cat artifacts/runs/right-add-zero/03_proof/blocker.md`
    `cat artifacts/runs/right-add-zero/03_proof/loop.md`
    Then run `terry retry right-add-zero --attempts 1`. (`--approve` is not valid
    here; proof-blocked runs continue only through `terry retry`.)
13. Finish the run by approving the final handoff:
    `terry resume right-add-zero --approve`
    Only edit `04_final/review.md` if you want to leave notes or reject the
    candidate.

If you prefer to launch Terry from elsewhere but keep reusing one warmed local cache,
pass the project directory explicitly on every command:

```bash
terry prove examples/inputs/right_add_zero.md --run-id right-add-zero --workdir /path/to/project
terry resume right-add-zero --workdir /path/to/project
terry review right-add-zero --attempt 1 --workdir /path/to/project
terry retry right-add-zero --attempts 1 --workdir /path/to/project
terry status right-add-zero --workdir /path/to/project
```

`--workdir` is the same knob as `--repo-root`. It tells Terry where to put
`artifacts/`, where to discover or create `lean_workspace_template/`, and where to keep
the shared `.terry/lean_workspace/` cache warm between runs.

At the end, the canonical output is:

- `artifacts/runs/right-add-zero/04_final/final.lean`

Useful status command:

- `terry status right-add-zero`
- `terry review right-add-zero --attempt 1`
- `terry retry right-add-zero --attempts 1`

The intended human path is the Terry CLI plus the review files Terry writes into the run
directory. The important contract is no longer Terry-owned stage JSON; it is the
backend-owned handoff or candidate files that Terry points you at.
