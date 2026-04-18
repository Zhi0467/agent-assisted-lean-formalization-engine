import FormalizationEngineWorkspace.Basic

theorem zero_add_provider_demo (n : Nat) : 0 + n = n := by
  simpa using Nat.zero_add n
