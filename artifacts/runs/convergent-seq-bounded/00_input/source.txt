Title: Convergent real sequence is bounded

We work with a sequence `u : ℕ → ℝ` and a real number `a`.

Formalize the following theorem in Lean 4 with mathlib:

If `u` converges to `a`, then there exists a real constant `M > 0` such that
for every natural number `n`, `|u n| ≤ M`.

Use the standard mathlib notion of convergence for sequences in `ℝ`, make the
assumptions explicit in the theorem statement, and produce Lean code that
compiles without `sorry`.
