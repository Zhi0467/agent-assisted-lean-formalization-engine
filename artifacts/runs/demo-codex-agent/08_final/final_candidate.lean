import FormalizationEngineWorkspace.Basic

theorem zero_add_nat (n : Nat) : 0 + n = n := by
  simpa using Nat.zero_add n
