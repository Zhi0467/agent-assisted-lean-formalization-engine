# Plan Handoff

## Context Used

- Read `01_enrichment/handoff.md`, `natural_language_statement.md`, `natural_language_proof.md`, `proof_status.json`, `relevant_lean_objects.md`, `00_input/provenance.json`, `00_input/source.pdf`, and the reviewer note at `02_plan/review.md`.
- No `enrichment_review` pointer was provided in the stage inputs.
- `source.pdf` confirms that the intended proof route is Andy Jones's fixed-point argument from the section headed "The Correct Proof".

## Locked Imports

```lean
import Mathlib.Analysis.Calculus.Deriv.Basic
import Mathlib.Data.Matrix.Mul
import Mathlib.LinearAlgebra.Matrix.Determinant
import Mathlib.LinearAlgebra.Matrix.NonsingularInverse
```

## Locked Theorem Surface

```lean
import Mathlib.Analysis.Calculus.Deriv.Basic
import Mathlib.Data.Matrix.Mul
import Mathlib.LinearAlgebra.Matrix.Determinant
import Mathlib.LinearAlgebra.Matrix.NonsingularInverse

theorem policyGradient_matrix_coordinate
    {Idx SA : Type*}
    [DecidableEq Idx]
    [Fintype SA]
    [DecidableEq SA]
    (Pi : (Idx → ℝ) → Matrix SA SA ℝ)
    (p0 r : SA → ℝ)
    (theta : Idx → ℝ)
    (i : Idx)
    (Pi_i' : Matrix SA SA ℝ)
    (hInv : ∀ theta0 : Idx → ℝ, Matrix.det ((1 : Matrix SA SA ℝ) - Pi theta0) ≠ 0)
    (hPi_i' :
      ∀ a b : SA,
        HasDerivAt
          (fun x : ℝ => Pi (Function.update theta i x) a b)
          (Pi_i' a b)
          (theta i)) :
    let q : SA → ℝ :=
      Matrix.mulVec (((1 : Matrix SA SA ℝ) - Pi theta)⁻¹) r
    let d : SA → ℝ :=
      Matrix.vecMul p0 (((1 : Matrix SA SA ℝ) - Pi theta)⁻¹)
    let J : (Idx → ℝ) → ℝ :=
      fun theta0 =>
        dotProduct
          (Matrix.vecMul p0 (((1 : Matrix SA SA ℝ) - Pi theta0)⁻¹))
          r
    HasDerivAt
      (fun x : ℝ => J (Function.update theta i x))
      (dotProduct d (Matrix.mulVec Pi_i' q))
      (theta i) := by
  sorry
```

## Locked Proof Route

1. Work on the one-variable slice `x ↦ Function.update theta i x` and define
   - `A x := (1 : Matrix SA SA ℝ) - Pi (Function.update theta i x)`
   - `qS x := Matrix.mulVec (A x)⁻¹ r`
   - `dS x := Matrix.vecMul p0 (A x)⁻¹`
   - `JS x := dotProduct (dS x) r`
2. Use `hInv` and the nonsingular-inverse cancellation lemmas from `Mathlib.LinearAlgebra.Matrix.NonsingularInverse` to derive, for every `x`,
   - `r = Matrix.mulVec (A x) (qS x)`
   - `p0 = Matrix.vecMul (dS x) (A x)`
   These are the formal fixed-point identities behind the natural-language proof.
3. Keep the theorem surface entrywise: `hPi_i'` is intentionally scalar-on-entries, not matrix-valued `HasDerivAt`. `relevant_lean_objects.md` explicitly says the current context does not fix a default matrix norm scope, so the plan must not assume hidden normed-matrix infrastructure in the statement.
4. Prove the needed differentiability of `A`, `qS`, and `dS` on the slice. This may use an auxiliary inverse-smoothness lemma, but only as support for the fixed-point proof. The main proof spine is still Jones's differentiated fixed-point argument, not a direct derivative-of-resolvent proof.
5. Differentiate the two fixed-point identities at `x = theta i` and obtain the Lean versions of
   - `dS'(theta i) * A(theta i) = d * Pi_i'`
   - `A(theta i) * qS'(theta i) = Pi_i' * q`
   expressed with `Matrix.vecMul` and `Matrix.mulVec`.
6. Differentiate `JS x = dotProduct (dS x) r`, substitute `r = Matrix.mulVec (A (theta i)) q`, and use the differentiated visitation identity to rewrite the derivative to `dotProduct d (Matrix.mulVec Pi_i' q)`.
7. Do not switch the proof to the symmetric `p0 · q` branch or a direct closed-form inverse derivative unless needed as a local auxiliary lemma. The locked route is the `d · r` branch from `natural_language_proof.md` and the Jones source.

## Explicit Gaps

- The provided context does not fix a matrix norm scope, so a later proof worker must make that proof-engineering choice only if it is needed for an auxiliary inverse-differentiability lemma.
- This run directory is not a Lean project and does not contain a local mathlib checkout, so the statement was locked from the supplied context surface and reuse inventory rather than from local compilation.
