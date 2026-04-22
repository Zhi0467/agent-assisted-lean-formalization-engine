# Walkthrough

This review used only the provided context surface: the plan handoff, natural-language statement and proof, enrichment notes, the current `candidate.lean`, the compile result, and the source PDF excerpted from Andy Jones's "The Correct Proof".

## What theorem the file is trying to prove

The theorem statement in `candidate.lean` matches the matrix-coordinate form fixed in the plan handoff:

- `q = (I - Π(theta))⁻¹ r`
- `d = p0 (I - Π(theta))⁻¹`
- `J(theta0) = dotProduct (p0 (I - Π(theta0))⁻¹) r`
- target derivative: `∂/∂theta_i J = d · (Pi_i' q)`

This is the same route described in the natural-language proof and in the source PDF section "The Correct Proof", where the proof proceeds by differentiating the fixed-point identities

- `p0 = d (I - Π)`
- `r = (I - Π) q`.

## How the Lean proof body maps to the paper proof

### 1. Reduce to the one-variable slice

After `dsimp` on line 36, the attempt introduces the slice variable `x` and defines:

- lines 37-38: `A x = 1 - Pi (update theta i x)`
- lines 39-40: `qS x = (A x)⁻¹ r`
- lines 41-42: `dS x = p0 (A x)⁻¹`

This is exactly plan step 1. It rewrites the multivariate coordinate derivative into the single-variable curve `x ↦ update theta i x`.

### 2. Turn determinant nonvanishing into inverse-cancellation data

Lines 43-45 prove `hA_unit`, namely that `det (A x)` is a unit for every `x`. This comes directly from the theorem hypothesis

- `hInv : det (1 - Pi theta0) ≠ 0`.

That witness is then fed to the nonsingular-inverse lemmas from `Mathlib.LinearAlgebra.Matrix.NonsingularInverse`.

### 3. Recover the fixed-point identity for `q`

Lines 46-57 prove

- `Matrix.mulVec (A x) (qS x) = r`.

This is the Lean form of `r = (I - Π) q`. The calculation is:

1. expand `qS x` as `(A x)⁻¹ r`;
2. reassociate matrix-vector multiplication with `Matrix.mulVec_mulVec`;
3. replace `A x * (A x)⁻¹` by `1` using the nonsingular-inverse lemma;
4. simplify `1 * r = r`.

This matches plan step 2 and the natural-language proof's second fixed-point identity.

### 4. Recover the fixed-point identity for `d`

Lines 58-69 prove

- `Matrix.vecMul (dS x) (A x) = p0`.

This is the Lean form of `p0 = d (I - Π)`. The proof is the row-vector analogue of the previous calculation:

1. expand `dS x` as `p0 (A x)⁻¹`;
2. reassociate with `Matrix.vecMul_vecMul`;
3. replace `(A x)⁻¹ * A x` by `1`;
4. simplify `p0 * 1 = p0`.

This matches the other fixed-point identity from the source proof.

### 5. Compute the entrywise derivative of `A`

Lines 70-77 prove that every entry of `A` has derivative `-Pi_i' a b` at `x = theta i`.

This is the coordinatewise version of differentiating

- `A(x) = I - Π(update theta i x)`.

So far the attempt stays faithful to the locked theorem surface: it uses only the entrywise derivative hypothesis `hPi_i'`, not any stronger matrix-valued differentiability theorem.

## Where the attempt stops

The proof ends with a comment block at lines 78-91 and a final `sorry` on line 92.

That means the attempt never carries out the remaining proof steps from the handoff:

1. differentiate the fixed-point identities for `dS` and `qS`;
2. extract the derivative identities
   - `dS'(theta i) * A(theta i) = d * Pi_i'`
   - `A(theta i) * qS'(theta i) = Pi_i' * q`;
3. differentiate `J`;
4. substitute `r = A(theta i) q` and conclude `dotProduct d (Matrix.mulVec Pi_i' q)`.

## Repair-facing conclusion

The current attempt gets the algebraic setup right. It successfully formalizes the slice definitions and both fixed-point identities, and it computes the derivative of `A` entrywise. The missing part is the analytic bridge from those entrywise facts to derivatives of the inverse-dependent functions `qS` and `dS`.

The provided context explicitly flags that gap: the plan handoff and `relevant_lean_objects.md` both say that no matrix norm scope has been fixed on the locked surface, so inverse differentiability for matrix-valued functions is not yet available as a ready-to-use tool from the given imports alone. The review therefore should treat the attempt as structurally aligned with the intended proof, but still incomplete.
