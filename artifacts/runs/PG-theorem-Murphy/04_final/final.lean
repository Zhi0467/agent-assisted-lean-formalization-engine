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
  let _ := hJ_right
  have hd_apply (i : ι) : HasDerivAt (fun x => d x i) (d' i) theta := by
    simpa using
      (HasDerivAt.clm_apply
        (hc := hasDerivAt_const theta (ContinuousLinearMap.proj i))
        (hu := hd))
  have hq_apply (i : ι) : HasDerivAt (fun x => q x i) (q' i) theta := by
    simpa using
      (HasDerivAt.clm_apply
        (hc := hasDerivAt_const theta (ContinuousLinearMap.proj i))
        (hu := hq))
  have hPiM_apply (i j : ι) : HasDerivAt (fun x => PiM x i j) (PiM' i j) theta := by
    have hPiM_row (i : ι) : HasDerivAt (fun x => PiM x i) (PiM' i) theta := by
      simpa using
        (HasDerivAt.clm_apply
          (hc := hasDerivAt_const theta
            (ContinuousLinearMap.proj i : Matrix ι ι ℝ →L[ℝ] ι → ℝ))
          (hu := hPiM))
    simpa using
      (HasDerivAt.clm_apply
        (hc := hasDerivAt_const theta
          (ContinuousLinearMap.proj j : (ι → ℝ) →L[ℝ] ℝ))
        (hu := hPiM_row i))
  have hJ_model : HasDerivAt (fun x => (d x) ⬝ᵥ r) J' theta := by
    exact hJ.congr_of_eventuallyEq hJ_left.symm
  have hJ_model' : HasDerivAt (fun x => (d x) ⬝ᵥ r) (d' ⬝ᵥ r) theta := by
    convert
      (HasDerivAt.sum (u := Finset.univ)
        (A := fun i x => d x i * r i)
        (A' := fun i => d' i * r i)
        (fun i _ => (hd_apply i).mul_const (r i))) using 1
    · funext x
      simp [dotProduct]
  have hJ_eq : J' = d' ⬝ᵥ r := HasDerivAt.unique hJ_model hJ_model'
  have hBellman_q_theta : Matrix.mulVec (1 - PiM theta) (q theta) = r := by
    simpa using Filter.EventuallyEq.eq_of_nhds hBellman_q
  have hBellman_d_coord_eventually (j : ι) :
      (fun x => (Matrix.vecMul (d x) (1 - PiM x)) j) =ᶠ[nhds theta] fun _ => p0 j := by
    filter_upwards [hBellman_d] with x hx
    exact congrArg (fun v => v j) hx
  have hBellman_d_coord_deriv (j : ι) :
      HasDerivAt (fun x => (Matrix.vecMul (d x) (1 - PiM x)) j)
        (((Matrix.vecMul d' (1 - PiM theta)) j) - ((Matrix.vecMul (d theta) PiM') j)) theta := by
    have hRaw :
        HasDerivAt (fun x => (Matrix.vecMul (d x) (1 - PiM x)) j)
          (∑ i, (d' i * (((1 : Matrix ι ι ℝ) - PiM theta) i j) + d theta i * (-(PiM' i j)))) theta := by
      convert
        (HasDerivAt.sum (u := Finset.univ)
          (A := fun i x => d x i * (((1 : Matrix ι ι ℝ) - PiM x) i j))
          (A' := fun i => d' i * (((1 : Matrix ι ι ℝ) - PiM theta) i j) + d theta i * (-(PiM' i j)))
          (fun i _ => by
            have hOneMinus : HasDerivAt (fun x => (((1 : Matrix ι ι ℝ) - PiM x) i j))
                (-(PiM' i j)) theta := by
              simpa using ((hasDerivAt_const theta ((1 : Matrix ι ι ℝ) i j)).sub (hPiM_apply i j))
            simpa using (hd_apply i).mul hOneMinus)) using 1
      · funext x
        simp [Matrix.vecMul, dotProduct]
    simpa [Matrix.vecMul, dotProduct, sub_eq_add_neg, Finset.sum_add_distrib, add_comm, add_left_comm,
      add_assoc, left_distrib, right_distrib, mul_add, add_mul] using hRaw
  have hBellman_d_eq :
      Matrix.vecMul d' (1 - PiM theta) = Matrix.vecMul (d theta) PiM' := by
    ext j
    have hBellman_d_const : HasDerivAt (fun x => (Matrix.vecMul (d x) (1 - PiM x)) j) 0 theta := by
      exact (hasDerivAt_const theta (p0 j)).congr_of_eventuallyEq (hBellman_d_coord_eventually j)
    have hEq0 :
        ((Matrix.vecMul d' (1 - PiM theta)) j) - ((Matrix.vecMul (d theta) PiM') j) = 0 :=
      HasDerivAt.unique (hBellman_d_coord_deriv j) hBellman_d_const
    exact sub_eq_zero.mp hEq0
  calc
    J' = d' ⬝ᵥ r := hJ_eq
    _ = d' ⬝ᵥ Matrix.mulVec (1 - PiM theta) (q theta) := by rw [← hBellman_q_theta]
    _ = Matrix.vecMul d' (1 - PiM theta) ⬝ᵥ q theta := by
      rw [Matrix.dotProduct_mulVec]
    _ = Matrix.vecMul (d theta) PiM' ⬝ᵥ q theta := by
      rw [hBellman_d_eq]
