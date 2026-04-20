# Plan Handoff

## Scope Locked From Supplied Pointers

This plan was prepared only from the supplied stage inputs:

- `enrichment_handoff`
- `natural_language_statement`
- `natural_language_proof`
- `proof_status`
- `provenance`
- `relevant_lean_objects`
- `source`

No direct `enrichment_review` pointer was supplied for this turn. References to `review.md` inside the supplied files were treated as second-hand context only.

## Status Gate

`proof_status.json` says the theorem surface was obtained, but the referenced review outcome is still `reject`. The proof worker should not widen scope, replace the proof, or import unstated assumptions. The job here is to formalize the already-pinned statement/proof route once approval exists.

## Locked Formalization Shape

Use one finite type `SA` for state-action pairs. If a later stage wants separate state and action types, instantiate `SA := S × A`; do not build a custom reinforcement-learning API first.

Use the matrix/vector conventions that match the supplied proof:

- row vectors: `SA → ℝ`
- column vectors: `SA → ℝ`
- transition matrix: `Matrix SA SA ℝ`
- row-vector action on a matrix: `Matrix.vecMul`
- matrix action on a column vector: `Matrix.mulVec`
- scalar return: `dotProduct d r`

Preserve the theorem surface from the natural-language statement:

- `Π(θ)[x,y]` is the state-action transition matrix
- `q(θ) = (1 - Π(θ))⁻¹ * r` in column-vector form
- `d(θ) = p₀ * (1 - Π(θ))⁻¹` in row-vector form
- `J(θ) = d(θ) ⬝ᵥ r = p₀ ⬝ᵥ q(θ)`
- the target conclusion is the coordinate/scalar-line derivative formula

In Lean terms, the first proof target should be the algebraic core of the Jones argument, with derivative objects supplied as data rather than derived from matrix inverse calculus.

## Locked Theorem Target

Prove this core theorem first:

```lean
theorem policyGradient_core
    {SA : Type*} [Fintype SA] [DecidableEq SA]
    (Π Π' : Matrix SA SA ℝ)
    (p₀ d d' q r : SA → ℝ)
    (hd_fix : p₀ = Matrix.vecMul d (1 - Π))
    (hq_fix : r = Matrix.mulVec (1 - Π) q)
    (hd_diff : Matrix.vecMul d' (1 - Π) = Matrix.vecMul d Π') :
    dotProduct d' r = dotProduct d (Matrix.mulVec Π' q)
```

This is the supplied proof route in exact Lean-friendly form:

- `hd_fix` is `p₀ = d (I - Π)`
- `hq_fix` is `r = (I - Π) q`
- `hd_diff` is the differentiated first fixed-point identity
- the conclusion is the policy-gradient scalar identity

After that core theorem exists, the proof worker may add a thin wrapper theorem for a scalar parameter line `θ : ℝ`, or for one coordinate line through a multivariate parameter space, but that wrapper is secondary. Do not make the first proof depend on differentiating `(1 - Π)⁻¹` directly.

## Imports Locked For The Worker

Minimal imports for the core theorem:

```lean
import Mathlib.Data.Matrix.Mul
import Mathlib.LinearAlgebra.Matrix.NonsingularInverse
```

Only add the following if the worker also builds the scalar-derivative wrapper in the same file:

```lean
import Mathlib.LinearAlgebra.Matrix.ToLin
import Mathlib.Analysis.Calculus.FDeriv.Mul
import Mathlib.Analysis.Calculus.ContDiff.Operations
import Mathlib.Analysis.Matrix.Normed
```

The supplied context does not pin a default matrix norm instance. If the wrapper theorem needs matrix-valued calculus, the worker must explicitly choose a matrix norm scope in that file instead of assuming one exists by default.

## Proof Route Locked

Follow this route and do not replace it with a different argument:

1. Work over a generic finite type `SA` with real matrices/vectors.
2. Define `d` and `q` from inverse formulas under an explicit invertibility hypothesis on `1 - Π`.
3. Derive the fixed-point identities
   - `p₀ = Matrix.vecMul d (1 - Π)`
   - `r = Matrix.mulVec (1 - Π) q`
   using inverse cancellation lemmas from `Mathlib.LinearAlgebra.Matrix.NonsingularInverse`.
4. Prove `policyGradient_core` by the same substitutions as in the natural-language proof:
   - start from `dotProduct d' r`
   - rewrite `r` using `hq_fix`
   - use `Matrix.dotProduct_mulVec` and vector/matrix associativity
   - replace `Matrix.vecMul d' (1 - Π)` with `Matrix.vecMul d Π'` via `hd_diff`
   - conclude `dotProduct d (Matrix.mulVec Π' q)`
5. Only after the algebraic core is done, add the scalar derivative shell if needed:
   - differentiate `p₀ = d(t) (1 - Π(t))` to obtain `hd_diff`
   - optionally differentiate `r = (1 - Π(t)) q(t)` for the symmetric route, but it is not needed for the main proof
   - combine with `J(t) = dotProduct (d(t)) r`

The worker should stay with the fixed-point proof from the supplied Jones article / natural-language proof. Do not switch to a direct proof by differentiating the inverse formula for `d` or `q`.

## Reuse Surface To Prefer

The supplied reuse inventory points to these objects first:

- `Matrix.vecMul`
- `Matrix.mulVec`
- `dotProduct`
- `Matrix.dotProduct_mulVec`
- `Matrix.vecMul_sub`
- `Matrix.mulVec_sub`
- inverse cancellation lemmas in `Mathlib.LinearAlgebra.Matrix.NonsingularInverse`

Use those before introducing bespoke linear-algebra abstractions.

## Explicit Limits From The Visible Context

- No direct `enrichment_review` pointer was supplied, so assumptions from `review.md` are only available indirectly through `enrichment_handoff.md` and `proof_status.json`.
- No Lean project files or toolchain files are present under the repo root in this stage workspace, so the import list above is locked from `relevant_lean_objects.md`, not from local compilation.
- No reinforcement-learning theorem/object library was supplied. Build the theorem over generic finite matrices/vectors, not over hidden MDP definitions.
- The supplied context supports taking invertibility/transience of `1 - Π(θ)` as an assumption, but it does not supply a ready-made bridge from spectral-radius facts to invertibility in Lean. The first formalization should therefore assume invertibility explicitly.
