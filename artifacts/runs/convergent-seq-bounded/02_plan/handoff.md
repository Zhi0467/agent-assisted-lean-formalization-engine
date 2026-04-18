# Plan Handoff

## Objective

Formalize the theorem that a convergent real sequence is bounded:

```lean
theorem convergent_sequence_bounded
    {u : ℕ → ℝ} {a : ℝ}
    (h : Tendsto u atTop (𝓝 a)) :
    ∃ M > 0, ∀ n : ℕ, |u n| ≤ M := by
  ...
```

The reviewer approved the enrichment plan with no additional constraints beyond
keeping the target statement and proof direction as proposed.

## Locked Proof Shape

Use the `ε = 1` tail estimate from convergence and avoid any finite-maximum
construction.

1. Extract `N : ℕ` such that `∀ n ≥ N, |u n - a| < 1`.
2. Define the finite prefix sum
   `S : ℝ := ∑ k in Finset.range N, |u k|`.
3. Set the global bound
   `M := S + (|a| + 1)`.
4. Prove `M > 0` from:
   - `S ≥ 0` via `Finset.sum_nonneg` and `abs_nonneg`;
   - `|a| + 1 > 0`.
5. For arbitrary `n`, split on `hn : n < N`.
6. In the prefix branch, show `|u n| ≤ S` using `Finset.single_le_sum`, then
   conclude `|u n| ≤ M`.
7. In the tail branch, derive `N ≤ n`, use the tail estimate, rewrite
   `u n = (u n - a) + a`, apply `abs_add`, and conclude
   `|u n| < 1 + |a| ≤ M`.

## Lean Implementation Notes

- Prefer importing only `Mathlib`.
- The convergence extraction should use the standard neighborhood form of
  `Tendsto`; the exact helper lemma may vary, but the needed result is:
  `∃ N, ∀ n ≥ N, |u n - a| < 1`.
- In the prefix case:
  - convert `hn : n < N` into `hmem : n ∈ Finset.range N` using
    `Finset.mem_range.mpr hn`;
  - use `Finset.single_le_sum` with `fun _ _ => abs_nonneg _`.
- In the tail case:
  - get `hn' : N ≤ n` from `Nat.le_of_not_gt hn`;
  - use `hN n hn'` for the strict tail bound;
  - combine `abs_add` with `le_of_lt` to move from a strict inequality to the
    required `≤ M`.

## Expected Lemmas

- `Metric.tendsto_atTop.1` or an equivalent specialization of `Tendsto`
- `Finset.mem_range`
- `Finset.single_le_sum`
- `Finset.sum_nonneg`
- `Nat.le_of_not_gt`
- `abs_nonneg`
- `abs_add`
- `zero_lt_one`
- `lt_of_lt_of_le` or `le_of_lt`
- linear arithmetic via `linarith` if convenient

## Execution Checklist

1. Write the theorem with explicit parameters `{u : ℕ → ℝ} {a : ℝ}`.
2. Extract the `ε = 1` tail bound from `h`.
3. Introduce `S` and `M`.
4. Prove positivity of `M`.
5. Prove the uniform bound by `by_cases hn : n < N`.
6. Keep the proof `sorry`-free and compile against current mathlib.

## Risk Notes

- The only likely source of friction is the exact convergence-to-tail lemma name
  in the local mathlib version.
- If the direct metric lemma is awkward, fall back to unfolding the
  neighborhood definition just enough to obtain the `ε = 1` bound; do not
  change the target statement or overall proof architecture.
