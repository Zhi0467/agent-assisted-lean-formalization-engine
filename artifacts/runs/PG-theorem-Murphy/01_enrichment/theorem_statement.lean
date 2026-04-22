import Mathlib

open scoped Topology

theorem policy_gradient_theorem_of_local_series
    {ι : Type} [Fintype ι] [DecidableEq ι]
    (p0 r : ι → ℝ)
    (Pi : ℝ → Matrix ι ι ℝ)
    (d q : ℝ → ι → ℝ)
    (J : ℝ → ℝ)
    (theta : ℝ)
    (d' : ι → ℝ)
    (Pi' : Matrix ι ι ℝ)
    (hPi : HasDerivAt Pi Pi' theta)
    (hd : HasDerivAt d d' theta)
    (hd_series : ∀ᶠ t in 𝓝 theta, HasSum (fun k : ℕ => Matrix.vecMul p0 ((Pi t) ^ k)) (d t))
    (hq_series : ∀ᶠ t in 𝓝 theta, HasSum (fun k : ℕ => Matrix.mulVec ((Pi t) ^ k) r) (q t))
    (hJ_series : ∀ᶠ t in 𝓝 theta,
      HasSum (fun k : ℕ => dotProduct (Matrix.vecMul p0 ((Pi t) ^ k)) r) (J t)) :
    HasDerivAt J (dotProduct (Matrix.vecMul (d theta) Pi') (q theta)) theta := by
  sorry
