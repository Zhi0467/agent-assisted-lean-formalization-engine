# Enrichment Handoff

## Outcome

The theorem surface is pinned. The usable statement is the finite-state, finite-action matrix form of the policy gradient theorem:

- `Π(θ)[(s,a),(s',a')] = P(s' | s, a) * π_θ(a' | s')`
- `q(θ) = (I - Π(θ))⁻¹ r`
- `d(θ) = p₀ (I - Π(θ))⁻¹`
- `J(θ) = d(θ) · r = p₀ · q(θ)`
- for each parameter coordinate `θ_i`, `∂_i J(θ) = d(θ) (∂_i Π(θ)) q(θ)`

`natural_language_statement.md` restates the theorem in prose, and `natural_language_proof.md` contains an honest natural-language proof.

## Provenance

- `artifacts/runs/PG-theorem/00_input/source.pdf` contains Andy L. Jones, "A Clearer Proof of the Policy Gradient Theorem" at the front of the PDF. The fixed-point proof appears in the first embedded article, especially the pages headed "The Correct Proof".
- `artifacts/runs/PG-theorem/01_enrichment/review.md` restates the theorem in a cleaner finite-state/action form and adds explicit assumptions A1-A3, including the invertibility or spectral-radius hypothesis for `I - Π(θ)`.
- The same `source.pdf` later includes unrelated policy-gradient background material. That later material was not needed once the Jones proof was identified.

## Key Lean Reuse

The most important reusable Lean objects are summarized in `relevant_lean_objects.md`. The main ones are:

- `Matrix.mulVec`, `Matrix.vecMul`, and `dotProduct` / `⬝ᵥ` for the row-vector / matrix / column-vector algebra.
- `Matrix.dotProduct_mulVec`, `Matrix.vecMul_sub`, `Matrix.mulVec_sub`, and the bundled linear maps `Matrix.mulVecLin` and `Matrix.vecMulLinear`.
- Matrix inverse and cancellation lemmas from `Mathlib.LinearAlgebra.Matrix.NonsingularInverse`, such as `Matrix.mul_inv_of_invertible`, `Matrix.inv_mul_of_invertible`, `Matrix.mul_inv_cancel_left_of_invertible`, and `Matrix.inv_mul_cancel_right_of_invertible`.
- `HasFDerivAt.mul` and the inverse-derivative lemmas around `Ring.inverse` if later stages formalize differentiability of `(I - Π(θ))⁻¹` directly rather than taking it as a hypothesis.

## Important Caveats

- The reviewer file currently says `decision: reject`. The theorem/proof surface is present, but Terry should still wait for human approval before advancing the run.
- I did not find any RL-specific theorem or policy/MDP API in mathlib during the library scan. Later stages should build the reinforcement-learning objects locally and reuse generic matrix and calculus infrastructure.
- If later stages formalize matrix-valued calculus, they will need to choose an explicit matrix norm scope, since mathlib does not declare one default normed-ring structure for matrices.
