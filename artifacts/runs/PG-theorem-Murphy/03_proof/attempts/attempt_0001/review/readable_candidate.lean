import Mathlib

open scoped Topology Matrix.Norms.Operator

section

variable {ι : Type} [Fintype ι] [DecidableEq ι]

/-- A continuous-linear packaging of `dotProduct`, used for differentiation. -/
noncomputable def dotProductCLM :
    (ι → ℝ) →L[ℝ] (ι → ℝ) →L[ℝ] ℝ :=
  LinearMap.toContinuousLinearMap
    (((LinearMap.toContinuousLinearMap :
        ((ι → ℝ) →ₗ[ℝ] ℝ) ≃ₗ[ℝ] ((ι → ℝ) →L[ℝ] ℝ)).toLinearMap).comp
      (dotProductBilin ℝ ℝ))

/--
A continuous-linear packaging of row-vector times matrix, used for
bilinear differentiation.
-/
noncomputable def vecMulCLM :
    (ι → ℝ) →L[ℝ] Matrix ι ι ℝ →L[ℝ] (ι → ℝ) :=
  LinearMap.toContinuousLinearMap
    (((LinearMap.toContinuousLinearMap :
        (Matrix ι ι ℝ →ₗ[ℝ] (ι → ℝ)) ≃ₗ[ℝ]
          (Matrix ι ι ℝ →L[ℝ] (ι → ℝ))).toLinearMap).comp
      (Matrix.vecMulBilin ℝ ℝ))

/--
Derive the row Bellman identity `p0 = d (1 - A)` from the convergent
occupancy series `d = Σ_k p0 A^k`.
-/
lemma rowBellman {p0 d : ι → ℝ} {A : Matrix ι ι ℝ}
    (hd : HasSum (fun k : ℕ => Matrix.vecMul p0 (A ^ k)) d) :
    p0 = Matrix.vecMul d (1 - A) := by
  let f : ℕ → ι → ℝ := fun k => Matrix.vecMul p0 (A ^ k)

  have hshift_map :
      HasSum (fun k : ℕ => Matrix.vecMul (f k) A) (Matrix.vecMul d A) := by
    simpa [f] using
      hd.mapL (LinearMap.toContinuousLinearMap (Matrix.vecMulLinear A))

  have hshift : HasSum (fun k : ℕ => f (k + 1)) (Matrix.vecMul d A) := by
    simpa [f, Matrix.vecMul_vecMul, pow_succ] using hshift_map

  have hdecomp : HasSum f (f 0 + Matrix.vecMul d A) := by
    simpa using hshift.zero_add

  have hd_eq : d = p0 + Matrix.vecMul d A := by
    simpa [f, pow_zero, Matrix.vecMul_one] using hd.unique hdecomp

  have hp0 : p0 = d - Matrix.vecMul d A := by
    have h := congrArg (fun x => x - Matrix.vecMul d A) hd_eq
    simpa [sub_eq_add_neg, add_assoc, add_left_comm, add_comm] using h.symm

  calc
    p0 = d - Matrix.vecMul d A := hp0
    _ = Matrix.vecMul d (1 - A) := by
      simp [Matrix.vecMul_sub]

/--
Derive the column Bellman identity `r = (1 - A) q` from the convergent
value series `q = Σ_k A^k r`.
-/
lemma colBellman {q r : ι → ℝ} {A : Matrix ι ι ℝ}
    (hq : HasSum (fun k : ℕ => Matrix.mulVec (A ^ k) r) q) :
    r = Matrix.mulVec (1 - A) q := by
  let f : ℕ → ι → ℝ := fun k => Matrix.mulVec (A ^ k) r

  have hshift_map :
      HasSum (fun k : ℕ => Matrix.mulVec A (f k)) (Matrix.mulVec A q) := by
    simpa [f] using
      hq.mapL (LinearMap.toContinuousLinearMap (Matrix.mulVecLin A))

  have hshift : HasSum (fun k : ℕ => f (k + 1)) (Matrix.mulVec A q) := by
    simpa [f, Matrix.mulVec_mulVec, pow_succ'] using hshift_map

  have hdecomp : HasSum f (f 0 + Matrix.mulVec A q) := by
    simpa using hshift.zero_add

  have hq_eq : q = r + Matrix.mulVec A q := by
    simpa [f, pow_zero, Matrix.one_mulVec] using hq.unique hdecomp

  have hr : r = q - Matrix.mulVec A q := by
    have h := congrArg (fun x => x - Matrix.mulVec A q) hq_eq
    simpa [sub_eq_add_neg, add_assoc, add_left_comm, add_comm] using h.symm

  calc
    r = q - Matrix.mulVec A q := hr
    _ = Matrix.mulVec (1 - A) q := by
      simp [Matrix.sub_mulVec]

/--
Recover the scalar identity `J = d ⋅ r` from the series for `d` and the
series defining `J`.
-/
lemma jEqDot {p0 d r : ι → ℝ} {A : Matrix ι ι ℝ} {J : ℝ}
    (hd : HasSum (fun k : ℕ => Matrix.vecMul p0 (A ^ k)) d)
    (hJ : HasSum (fun k : ℕ => dotProduct (Matrix.vecMul p0 (A ^ k)) r) J) :
    J = dotProduct d r := by
  have hd_map :
      HasSum
        (fun k : ℕ => dotProduct r (Matrix.vecMul p0 (A ^ k)))
        (dotProduct r d) := by
    simpa using
      hd.mapL (LinearMap.toContinuousLinearMap (dotProductBilin ℝ ℝ r))

  have hd_map' :
      HasSum
        (fun k : ℕ => dotProduct (Matrix.vecMul p0 (A ^ k)) r)
        (dotProduct d r) := by
    simpa [dotProduct_comm] using hd_map

  exact hJ.unique hd_map'

/--
Local-series formulation of the policy gradient theorem.

The proof follows the "correct proof" strategy from the source material:
derive Bellman identities from the local `HasSum` hypotheses, differentiate
`J = d ⋅ r`, differentiate `p0 = d (1 - Π)`, then substitute
`r = (1 - Π) q` and reassociate with `Matrix.dotProduct_mulVec`.
-/
set_option maxHeartbeats 0 in
theorem policy_gradient_theorem_of_local_series
    (p0 r : ι → ℝ)
    (Pi : ℝ → Matrix ι ι ℝ)
    (d q : ℝ → ι → ℝ)
    (J : ℝ → ℝ)
    (theta : ℝ)
    (d' : ι → ℝ)
    (Pi' : Matrix ι ι ℝ)
    (hPi : HasDerivAt Pi Pi' theta)
    (hd : HasDerivAt d d' theta)
    (hd_series :
      ∀ᶠ t in 𝓝 theta, HasSum (fun k : ℕ => Matrix.vecMul p0 ((Pi t) ^ k)) (d t))
    (hq_series :
      ∀ᶠ t in 𝓝 theta, HasSum (fun k : ℕ => Matrix.mulVec ((Pi t) ^ k) r) (q t))
    (hJ_series :
      ∀ᶠ t in 𝓝 theta,
        HasSum (fun k : ℕ => dotProduct (Matrix.vecMul p0 ((Pi t) ^ k)) r) (J t)) :
    HasDerivAt J (dotProduct (Matrix.vecMul (d theta) Pi') (q theta)) theta := by
  have hrow :
      (fun _ : ℝ => p0) =ᶠ[𝓝 theta] fun t => Matrix.vecMul (d t) (1 - Pi t) := by
    filter_upwards [hd_series] with t hdt
    exact rowBellman hdt

  have hcol :
      (fun _ : ℝ => r) =ᶠ[𝓝 theta] fun t => Matrix.mulVec (1 - Pi t) (q t) := by
    filter_upwards [hq_series] with t hqt
    exact colBellman hqt

  have hJdot :
      J =ᶠ[𝓝 theta] fun t => dotProduct (d t) r := by
    filter_upwards [hd_series, hJ_series] with t hdt hJt
    exact jEqDot hdt hJt

  have hJ_deriv : HasDerivAt J (dotProduct d' r) theta := by
    have hdot :
        HasDerivAt (fun t => dotProduct (d t) r) (dotProduct d' r) theta := by
      simpa using
        (dotProductCLM.hasFDerivAt_of_bilinear hd.hasFDerivAt
          ((hasDerivAt_const theta r).hasFDerivAt)).hasDerivAt
    exact hdot.congr_of_eventuallyEq hJdot

  have hrow_zero :
      HasDerivAt (fun t => Matrix.vecMul (d t) (1 - Pi t)) 0 theta := by
    exact (hasDerivAt_const theta p0).congr_of_eventuallyEq hrow.symm

  have hrow_formula :
      HasDerivAt
        (fun t => Matrix.vecMul (d t) (1 - Pi t))
        (Matrix.vecMul d' (1 - Pi theta) - Matrix.vecMul (d theta) Pi')
        theta := by
    simpa [vecMulCLM, sub_eq_add_neg, Matrix.vecMul_add, Matrix.vecMul_one,
        Matrix.vecMul_neg, add_assoc, add_left_comm, add_comm] using
      (vecMulCLM.hasFDerivAt_of_bilinear hd.hasFDerivAt
        ((hasDerivAt_const theta (1 : Matrix ι ι ℝ)).sub hPi).hasFDerivAt).hasDerivAt

  have hrow_eq0 :
      (0 : ι → ℝ) =
        Matrix.vecMul d' (1 - Pi theta) - Matrix.vecMul (d theta) Pi' :=
    hrow_zero.unique hrow_formula

  have hrow_eq :
      Matrix.vecMul d' (1 - Pi theta) = Matrix.vecMul (d theta) Pi' := by
    ext i
    have hi := congrArg (fun v => v i) hrow_eq0
    exact sub_eq_zero.mp <| by simpa using hi.symm

  have hcol_theta :
      r = Matrix.mulVec (1 - Pi theta) (q theta) :=
    Filter.EventuallyEq.eq_of_nhds hcol

  have hfinal :
      dotProduct d' r =
        dotProduct (Matrix.vecMul (d theta) Pi') (q theta) := by
    calc
      dotProduct d' r
          = dotProduct d' (Matrix.mulVec (1 - Pi theta) (q theta)) := by
            rw [hcol_theta]
      _ = dotProduct (Matrix.vecMul d' (1 - Pi theta)) (q theta) := by
            simpa using Matrix.dotProduct_mulVec d' (1 - Pi theta) (q theta)
      _ = dotProduct (Matrix.vecMul (d theta) Pi') (q theta) := by
            rw [hrow_eq]

  convert hJ_deriv using 1
  exact hfinal.symm

end
