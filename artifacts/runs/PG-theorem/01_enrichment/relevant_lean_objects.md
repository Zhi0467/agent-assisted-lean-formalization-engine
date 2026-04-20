# Relevant Lean Objects

## Summary

I did not locate an existing reinforcement-learning theorem or MDP API in mathlib for the policy gradient theorem. The promising reuse path is to model the theorem with generic finite-dimensional matrix and calculus infrastructure.

## Core Matrix and Vector Operations

- Module: `Mathlib.Data.Matrix.Mul`
- Key objects:
  - `Matrix.mulVec`
  - `Matrix.vecMul`
  - `dotProduct` with notation `⬝ᵥ`
  - `Matrix.dotProduct_mulVec`
  - `Matrix.vecMul_sub`
  - `Matrix.mulVec_sub`
  - `Matrix.vecMul_vecMul`
  - `Matrix.mulVec_mulVec`
  - `Matrix.vecMulVec`
- Why they fit:
  - They match the reviewer/source presentation almost directly: `d` and `p₀` are row vectors, `q` and `r` are column vectors, `Π` is a square matrix, and `J` is a dot product.
  - `Matrix.dotProduct_mulVec` is especially useful for switching between `J = d ⬝ᵥ r` and `J = (d ᵥ* Π) ⬝ᵥ q`.
- Notes:
  - A clean encoding is `Π : Matrix SA SA ℝ` and `d p₀ q r : SA → ℝ` for a finite type `SA` of state-action pairs.
  - `Matrix.vecMul_vecMul` and `Matrix.mulVec_mulVec` are the basic associativity lemmas for repeated vector/matrix actions.
  - `Matrix.vecMulVec` is the rank-one matrix constructor if a proof chooses a matrix-only encoding.

## Bundled Linear Maps

- Module: `Mathlib.LinearAlgebra.Matrix.ToLin`
- Key objects:
  - `Matrix.mulVecLin`
  - `Matrix.vecMulLinear`
  - `dotProductBilin`
  - `Matrix.mulVecLin_mul`
- Why they fit:
  - If later stages want a Fréchet-derivative proof, these packaged linear maps are a more natural target than rewriting everything by hand on functions.
  - `Matrix.mulVecLin_mul` packages composition of matrix actions as composition of linear maps.
- Notes:
  - These objects are also useful for translating between matrix inversion and inversion of continuous linear maps if that route is taken.

## Matrix Inverses and Cancellation

- Module: `Mathlib.LinearAlgebra.Matrix.NonsingularInverse`
- Key objects:
  - `Matrix.mul_inv_of_invertible`
  - `Matrix.inv_mul_of_invertible`
  - `Matrix.mul_inv_cancel_left_of_invertible`
  - `Matrix.inv_mul_cancel_right_of_invertible`
  - `Matrix.inv_mul_eq_iff_eq_mul_of_invertible`
  - `Matrix.mul_inv_eq_iff_eq_mul_of_invertible`
- Why they fit:
  - The theorem surface defines `q` and `d` through `(I - Π)⁻¹`.
  - These lemmas are the obvious tools for deriving or simplifying the fixed-point identities from the inverse formulas.
- Notes:
  - The exact later hypothesis may be either an `Invertible (1 - Π)` instance or an `IsUnit (1 - Π)` assumption converted into such an instance.

## Calculus on Products and Inverses

- Modules:
  - `Mathlib.Analysis.Calculus.FDeriv.Mul`
  - `Mathlib.Analysis.Calculus.ContDiff.Operations`
- Key objects:
  - `HasFDerivAt.mul`
  - `hasFDerivAt_ringInverse`
  - `contDiffAt_ringInverse`
- Why they fit:
  - The reviewer notes justify that `q(θ)` and `d(θ)` are `C^1` because matrix inversion is smooth on invertible matrices.
  - If later stages want to prove that smoothness in Lean instead of postulating it, these are the relevant reuse points.
- Important gap:
  - `hasFDerivAt_ringInverse` is stated for normed rings with summable geometric series and is phrased using `Ring.inverse`.
  - Working with matrices requires choosing a concrete normed-ring structure first; mathlib deliberately does not install one by default for matrices.

## Matrix Norms for Calculus

- Module: `Mathlib.Analysis.Matrix.Normed`
- Relevant scopes:
  - `open scoped Matrix.Norms.Elementwise`
  - `open scoped Matrix.Norms.Frobenius`
  - `open scoped Matrix.Norms.Operator`
- Why they fit:
  - Any calculus proof over matrix-valued functions needs a normed additive group / normed ring instance on matrices.
- Important gap:
  - This is likely the first technical decision later stages must make.
  - The `Matrix.Norms.Operator` scope is a plausible fit if one wants a normed-ring structure compatible with the usual operator viewpoint.

## Geometric-Series / Neumann-Series Infrastructure

- Modules:
  - `Mathlib.Analysis.Normed.Ring.Units`
  - `Mathlib.Topology.Algebra.InfiniteSum.Ring`
- Key objects:
  - `NormedRing.inverse_one_sub`
  - `NormedRing.inverse_add`
  - generic `tsum` / geometric-series lemmas in the infinite-sum ring library
- Why they fit:
  - These are relevant if later stages want to formalize the infinite-series definitions of `q` and `d`, or prove invertibility from a small-norm assumption.
- Important gap:
  - The reviewer notes use the stronger spectral-radius or invertibility assumption. I did not find a ready-made mathlib lemma during this scan that directly turns `spectralRadius Π < 1` into invertibility of `1 - Π` in the matrix setting.
  - Because of that, the safest first formalization pass is probably to assume `I - Π(θ)` is invertible, rather than trying to discharge A1 from spectral-radius facts.

## Spectrum-Related Infrastructure

- Module: `Mathlib.Analysis.Matrix.Spectrum`
- Key objects:
  - `Matrix.spectrum_toEuclideanLin`
- Why it might fit:
  - This is the obvious entry point if later stages insist on formalizing A1 in spectral language.
- Important gap:
  - The scan surfaced spectrum support, but not a ready-to-use bridge theorem from spectral-radius bounds to the exact inverse/summability facts needed here.

## Recommended Formalization Shape

- Use a finite type `SA` for state-action pairs.
- Keep the theorem generic over `SA` and real-valued matrices/vectors.
- Reuse `Matrix.vecMul`, `Matrix.mulVec`, `dotProduct`, and inverse lemmas to prove the fixed-point identities.
- Prefer the fixed-point differentiation proof over a direct derivative-of-the-inverse proof unless smoothness of inversion is needed elsewhere; it matches the source more closely and avoids unnecessary analytic overhead.
