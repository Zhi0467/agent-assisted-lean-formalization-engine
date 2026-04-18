import Mathlib

theorem convergent_sequence_bounded
    {u : ℕ → ℝ} {a : ℝ}
    (h : Filter.Tendsto u Filter.atTop (nhds a)) :
    ∃ M > 0, ∀ n : ℕ, |u n| ≤ M := by
  have h_event : ∀ᶠ n in Filter.atTop, |u n - a| < 1 := by
    exact (LinearOrderedAddCommGroup.tendsto_nhds.mp h) 1 zero_lt_one
  obtain ⟨N, hN⟩ := Filter.eventually_atTop.mp h_event
  let S : ℝ := Finset.sum (Finset.range N) fun k => |u k|
  have hS_nonneg : 0 ≤ S := by
    dsimp [S]
    exact Finset.sum_nonneg fun k _ => abs_nonneg (u k)
  refine ⟨S + (|a| + 1), by linarith [hS_nonneg, abs_nonneg a], ?_⟩
  intro n
  by_cases hn : n < N
  · have hmem : n ∈ Finset.range N := Finset.mem_range.mpr hn
    have hsingle : |u n| ≤ S := by
      dsimp [S]
      simpa using
        (Finset.single_le_sum (fun i _ => abs_nonneg (u i)) hmem :
          |u n| ≤ Finset.sum (Finset.range N) (fun k => |u k|))
    linarith [hsingle, hS_nonneg, abs_nonneg a]
  · have hn' : N ≤ n := Nat.le_of_not_gt hn
    have htail : |u n| < |a| + 1 := by
      have hrewrite : u n = (u n - a) + a := by ring
      rw [hrewrite]
      calc
        |(u n - a) + a| ≤ |u n - a| + |a| := abs_add _ _
        _ < 1 + |a| := by
          exact add_lt_add_right (hN n hn') |a|
        _ = |a| + 1 := by ring
    linarith [le_of_lt htail, hS_nonneg]
