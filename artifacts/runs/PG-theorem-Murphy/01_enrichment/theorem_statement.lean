import Mathlib

theorem policy_gradient_theorem_of_local_bellman_identities
    {ι : Type} [Fintype ι] [DecidableEq ι]
    (p0 r : ι → ℝ)
    (PiM : ℝ → Matrix ι ι ℝ)
    (d q : ℝ → ι → ℝ)
    (J : ℝ → ℝ)
    {theta J' : ℝ} {PiM' : Matrix ι ι ℝ} {d' q' : ι → ℝ}
    (hPiM : HasDerivAt PiM PiM' theta)
    (hd : HasDerivAt d d' theta)
    (hq : HasDerivAt q q' theta)
    (hJ : HasDerivAt J J' theta)
    (hJ_left : J =ᶠ[nhds theta] fun x => (d x) ⬝ᵥ r)
    (hJ_right : J =ᶠ[nhds theta] fun x => p0 ⬝ᵥ (q x))
    (hBellman_d : (fun x => Matrix.vecMul (d x) (1 - PiM x)) =ᶠ[nhds theta] fun _ => p0)
    (hBellman_q : (fun x => Matrix.mulVec (1 - PiM x) (q x)) =ᶠ[nhds theta] fun _ => r) :
    J' = (((Matrix.vecMul (d theta) PiM') ⬝ᵥ (q theta))) := by
  sorry
