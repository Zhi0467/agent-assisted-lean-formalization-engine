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
