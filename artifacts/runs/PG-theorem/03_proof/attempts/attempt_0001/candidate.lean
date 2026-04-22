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
  let A : ℝ → Matrix SA SA ℝ := fun x =>
    (1 : Matrix SA SA ℝ) - Pi (Function.update theta i x)
  let qS : ℝ → SA → ℝ := fun x =>
    Matrix.mulVec ((A x)⁻¹) r
  let dS : ℝ → SA → ℝ := fun x =>
    Matrix.vecMul p0 ((A x)⁻¹)
  have hA_unit : ∀ x : ℝ, IsUnit (Matrix.det (A x)) := by
    intro x
    exact isUnit_iff_ne_zero.mpr (hInv (Function.update theta i x))
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
  have hA_entry :
      ∀ a b : SA,
        HasDerivAt
          (fun x : ℝ => A x a b)
          (-Pi_i' a b)
          (theta i) := by
    intro a b
    simpa [A] using (hPi_i' a b).const_sub (1 : ℝ)
  /-
  Context gap on the provided surface:

  The remaining approved proof route differentiates the fixed-point identities for `qS` and `dS`.
  To do that in mathlib, one needs a matrix `NormedRing` instance together with the inverse
  differentiability lemmas for `Ring.inverse` (or an equivalent matrix-specific wrapper). Those
  instances live behind `Mathlib.Analysis.Matrix.Normed` / scoped matrix norms, but that module is
  not among the locked imports, and the plan handoff explicitly warned not to assume hidden
  normed-matrix infrastructure.

  So, with the current theorem surface and import surface alone, the slice identities above can be
  formalized, but the final differentiability step for `x ↦ ((A x)⁻¹)` is not available without
  extending the approved context.
  -/
  sorry
