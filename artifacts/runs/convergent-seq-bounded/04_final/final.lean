import Mathlib

theorem convergent_sequence_bounded
    {u : ℕ → ℝ} {a : ℝ}
    (h : Filter.Tendsto u Filter.atTop (nhds a)) :
    ∃ M > 0, ∀ n : ℕ, |u n| ≤ M := by
  have h_event : ∀ᶠ n in Filter.atTop, |u n - a| < (1 : ℝ) := by
    exact (LinearOrderedAddCommGroup.tendsto_nhds.mp h) 1 zero_lt_one
  obtain ⟨N, hN⟩ := Filter.eventually_atTop.mp h_event
  let S : ℝ := Finset.sum (Finset.range N) fun k => |u k|
  have hS_nonneg : 0 ≤ S := by
    dsimp [S]
    exact Finset.sum_nonneg fun k _ => abs_nonneg (u k)
  refine ⟨S + (|a| + 1), ?_, ?_⟩
  · linarith [hS_nonneg, abs_nonneg a]
  · intro n
    by_cases hn : n < N
    · have hmem : n ∈ Finset.range N := Finset.mem_range.mpr hn
      have hsingle : |u n| ≤ S := by
        dsimp [S]
        simpa using
            (Finset.single_le_sum
            (fun i _ => abs_nonneg (u i))
            hmem :
            |u n| ≤ Finset.sum (Finset.range N) (fun k => |u k|))
      linarith [hsingle, hS_nonneg, abs_nonneg a]
    · have hn' : N ≤ n := Nat.le_of_not_gt hn
      have htail' : |u n - a| < (1 : ℝ) := hN n hn'
      have hlt_left : -(1 : ℝ) < u n - a := (abs_lt.mp htail').1
      have hlt_right : u n - a < (1 : ℝ) := (abs_lt.mp htail').2
      have h_lower : a - 1 < u n := by
        linarith
      have h_upper : u n < a + 1 := by
        linarith
      have hneg_abs_le : -|a| ≤ a := by
        by_cases ha : 0 ≤ a
        · rw [abs_of_nonneg ha]
          linarith
        · have ha' : a < 0 := lt_of_not_ge ha
          rw [abs_of_neg ha']
          linarith
      have hle_abs : a ≤ |a| := by
        by_cases ha : 0 ≤ a
        · rw [abs_of_nonneg ha]
        · have ha' : a < 0 := lt_of_not_ge ha
          rw [abs_of_neg ha']
          linarith
      have htail : |u n| < |a| + 1 := by
        refine abs_lt.mpr ?_
        constructor
        · linarith
        · linarith
      linarith [le_of_lt htail, hS_nonneg]
