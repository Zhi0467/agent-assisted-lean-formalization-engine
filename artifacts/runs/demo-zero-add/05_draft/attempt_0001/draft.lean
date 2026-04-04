import FormalizationEngineWorkspace.Basic

theorem zero_add_demo (n : Nat) : 0 + n = n := by
  exact Nat.zero_add n
