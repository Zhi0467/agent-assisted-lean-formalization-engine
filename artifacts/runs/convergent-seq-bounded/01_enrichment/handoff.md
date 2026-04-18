# Enrichment Handoff

## Source Summary

- Title: `Convergent real sequence is bounded`
- Provenance: extracted from `convergent_sequence_bounded.md` via plain-text normalization
- Informal claim: if `u : ℕ → ℝ` converges to `a : ℝ`, then there exists `M > 0` such that `|u n| ≤ M` for all `n`.

## Recommended Lean Target

Use the standard filter-based notion of convergence:

```lean
import Mathlib

theorem convergent_sequence_bounded
    {u : ℕ → ℝ} {a : ℝ}
    (h : Tendsto u atTop (𝓝 a)) :
    ∃ M > 0, ∀ n : ℕ, |u n| ≤ M := by
  ...
```

This matches the request to keep assumptions explicit and to use the standard mathlib notion for sequence convergence in `ℝ`.

## Proof Strategy

Avoid finite maxima. The cleanest proof is:

1. Use convergence with `ε = 1` to get `N : ℕ` such that for all `n ≥ N`,
   `|u n - a| < 1`.
2. Define the finite prefix bound
   `S := ∑ k in Finset.range N, |u k|`.
3. Set
   `M := S + (|a| + 1)`.
4. Show `M > 0`.
   This is immediate from `S ≥ 0` and `|a| + 1 > 0`.
5. For `n < N`, use membership in `Finset.range N` and `Finset.single_le_sum`
   to prove `|u n| ≤ S`, hence `|u n| ≤ M`.
6. For `n ≥ N`, use the tail estimate and the triangle inequality:
   `|u n| = |(u n - a) + a| ≤ |u n - a| + |a| < 1 + |a| ≤ M`.

This yields the required global bound.

## Lean-Level Notes

- The only nontrivial split is `by_cases hn : n < N`.
- In the `hn : n < N` branch:
  - convert `hn` to `n ∈ Finset.range N` using `Finset.mem_range.mpr hn`;
  - use nonnegativity of absolute values to apply `Finset.single_le_sum`.
- In the tail branch, obtain `N ≤ n` from `Nat.le_of_not_gt hn`.
- For the triangle inequality, rewrite `u n` as `(u n - a) + a`, then use
  `abs_add`.
- When turning the convergence hypothesis into the `ε = 1` tail estimate, use
  the standard metric/`dist` specialization of `Tendsto` at `atTop`; the exact
  helper lemma name can vary across mathlib versions, but the intended result is:
  `∃ N, ∀ n ≥ N, |u n - a| < 1`.

## Likely Useful Facts

- `zero_lt_one`
- `abs_nonneg`
- `abs_add`
- `Nat.le_of_not_gt`
- `Finset.mem_range`
- `Finset.single_le_sum`
- `Finset.sum_nonneg`

## Suggested Skeleton

```lean
import Mathlib

theorem convergent_sequence_bounded
    {u : ℕ → ℝ} {a : ℝ}
    (h : Tendsto u atTop (𝓝 a)) :
    ∃ M > 0, ∀ n : ℕ, |u n| ≤ M := by
  obtain ⟨N, hN⟩ := -- from convergence with ε = 1
  let S : ℝ := ∑ k in Finset.range N, |u k|
  refine ⟨S + (|a| + 1), ?_, ?_⟩
  · -- positivity
  · intro n
    by_cases hn : n < N
    · -- prefix case: |u n| ≤ S ≤ M
    · -- tail case: N ≤ n, use hN and triangle inequality
```

## Main Implementation Choice

Prefer the `Finset.range`/sum proof over a proof using a finite maximum. It is
usually shorter, requires less bookkeeping about nonempty finite sets, and is
stable across mathlib versions.
