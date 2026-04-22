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
  dsimp

  -- Work on the one-coordinate slice `x ↦ update theta i x`.
  let A : ℝ → Matrix SA SA ℝ := fun x =>
    (1 : Matrix SA SA ℝ) - Pi (Function.update theta i x)
  let qS : ℝ → SA → ℝ := fun x =>
    Matrix.mulVec ((A x)⁻¹) r
  let dS : ℝ → SA → ℝ := fun x =>
    Matrix.vecMul p0 ((A x)⁻¹)

  -- The determinant hypothesis guarantees that each `A x` is nonsingular.
  have hA_unit : ∀ x : ℝ, IsUnit (Matrix.det (A x)) := by
    intro x
    exact isUnit_iff_ne_zero.mpr (hInv (Function.update theta i x))

  -- This is the fixed-point identity `r = A x * qS x`.
  have hqS_fixed : ∀ x : ℝ, Matrix.mulVec (A x) (qS x) = r := by
    intro x
    have hx : IsUnit (Matrix.det (A x)) := hA_unit x
    dsimp [qS]
    calc
      Matrix.mulVec (A x) (Matrix.mulVec ((A x)⁻¹) r)
          = Matrix.mulVec ((A x) * (A x)⁻¹) r := by
              rw [← Matrix.mulVec_mulVec]
      _ = Matrix.mulVec (1 : Matrix SA SA ℝ) r := by
            rw [Matrix.mul_nonsing_inv (A := A x) hx]
      _ = r := by
            simp

  -- This is the fixed-point identity `p0 = dS x * A x`.
  have hdS_fixed : ∀ x : ℝ, Matrix.vecMul (dS x) (A x) = p0 := by
    intro x
    have hx : IsUnit (Matrix.det (A x)) := hA_unit x
    dsimp [dS]
    calc
      Matrix.vecMul (Matrix.vecMul p0 ((A x)⁻¹)) (A x)
          = Matrix.vecMul p0 (((A x)⁻¹) * (A x)) := by
              rw [Matrix.vecMul_vecMul]
      _ = Matrix.vecMul p0 (1 : Matrix SA SA ℝ) := by
            rw [Matrix.nonsing_inv_mul (A := A x) hx]
      _ = p0 := by
            simp

  -- Entrywise derivative of `A = 1 - Pi` along the chosen coordinate slice.
  have hA_entry :
      ∀ a b : SA,
        HasDerivAt
          (fun x : ℝ => A x a b)
          (-Pi_i' a b)
          (theta i) := by
    intro a b
    simpa [A] using (hPi_i' a b).const_sub (1 : ℝ)

  /-
  Remaining gap in the current attempt:

  The intended proof now differentiates the fixed-point identities for `qS` and `dS`.
  On the provided context surface, that requires matrix-valued inverse differentiability
  infrastructure together with an explicit matrix `NormedRing` choice. The handoff and
  `relevant_lean_objects.md` note that this normed-matrix setup has not been fixed in
  the locked theorem/import surface.

  So the algebraic slice setup is present, but the derivative-of-inverse step has not been
  formalized in this attempt.
  -/
  sorry
