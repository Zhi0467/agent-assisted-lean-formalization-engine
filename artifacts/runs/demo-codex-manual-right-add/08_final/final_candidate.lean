import FormalizationEngineWorkspace.Basic

theorem right_add_zero_nat (n : Nat) : n + 0 = n := by
  exact Nat.add_zero n
