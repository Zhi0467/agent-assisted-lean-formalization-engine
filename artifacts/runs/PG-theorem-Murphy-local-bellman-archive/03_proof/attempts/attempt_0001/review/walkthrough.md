# Attempt 0001 Walkthrough

## Context reviewed

This review was written from the following visible inputs only:

- `01_enrichment/theorem_statement.lean`
- `01_enrichment/natural_language_statement.md`
- `01_enrichment/natural_language_proof.md`
- `01_enrichment/relevant_lean_objects.md`
- `01_enrichment/review.md`
- `01_enrichment/proof_status.json`
- `00_input/provenance.json`
- `00_input/source.pdf` (checked via text extraction of pages 1-4)
- `03_proof/attempts/attempt_0001/candidate.lean`
- `03_proof/attempts/attempt_0001/compile_result.json`

The stage instructions also mention `plan_handoff`, but no such file was present in the visible context surface. Nothing below assumes hidden handoff notes.

## Proof idea

The Lean proof implements the left-hand derivation from the natural-language proof and from page 4 of the source PDF:

1. Rewrite `J` locally as `d · r` and differentiate to get `J' = d' · r`.
2. Use the Bellman identity `d (I - Pi) = p0`, differentiate it at `theta`, and conclude
   `d' (I - Pi(theta)) = d(theta) Pi'(theta)`.
3. Use the Bellman identity `r = (I - Pi(theta)) q(theta)`.
4. Substitute to obtain `J' = d(theta) Pi'(theta) q(theta)`.

The proof does not use the symmetric right-hand derivation through `J = p0 · q`; the hypothesis `hJ_right` is retained in the statement but is not mathematically needed by this proof script.

## Code-to-proof mapping

### 1. Scalar derivatives are extracted from the bundled function derivatives

The helpers

- `hd_apply`
- `hq_apply`
- `hPiM_apply`

turn the Pi-valued derivatives `hd`, `hq`, and `hPiM` into coordinatewise scalar derivatives. This is the technical bridge that lets the rest of the proof use finite sums and the scalar product rule.

### 2. The derivative of `J = d · r` is computed explicitly

`hJ_model` rewrites the derivative hypothesis `hJ` along the local identity `hJ_left`, so Lean sees `J` near `theta` as the scalar function `x ↦ (d x) ⬝ᵥ r`.

`hJ_model'` then differentiates that scalar function directly as a finite sum:

- each summand is `d x i * r i`
- `r i` is constant
- the derivative of the summand is `d' i * r i`

From uniqueness of derivatives, `hJ_eq` concludes

`J' = d' ⬝ᵥ r`.

This is exactly the first displayed step in the natural-language proof.

### 3. The Bellman identity for `q` is specialized at the base point

`hBellman_q_theta` uses `Filter.EventuallyEq.eq_of_nhds` to turn the local identity

`(I - Pi x) q x = r`

into the pointwise equality at `theta`

`Matrix.mulVec (1 - PiM theta) (q theta) = r`.

This supplies the substitution for `r` used in the final calculation.

### 4. The Bellman identity for `d` is differentiated coordinatewise

`hBellman_d_coord_eventually` first projects the local vector identity

`d x (I - Pi x) = p0`

onto a fixed coordinate `j`.

`hBellman_d_coord_deriv` differentiates that `j`-th coordinate. The derivative is expanded as a finite sum over `i`, using:

- the scalar derivative of `d x i`
- the scalar derivative of `((1 : Matrix ι ι ℝ) - PiM x) i j`
- the product rule term-by-term

After algebraic simplification, the derivative of the `j`-th coordinate becomes

`((Matrix.vecMul d' (1 - PiM theta)) j) - ((Matrix.vecMul (d theta) PiM') j)`.

Since the original coordinate function is locally constant with value `p0 j`, `hBellman_d_const` gives it derivative `0`. Uniqueness of derivatives then yields the coordinate equation

`((Matrix.vecMul d' (1 - PiM theta)) j) - ((Matrix.vecMul (d theta) PiM') j) = 0`.

Extensionality over `j` produces

`hBellman_d_eq :
  Matrix.vecMul d' (1 - PiM theta) = Matrix.vecMul (d theta) PiM'`.

This is the formal version of the differentiated identity

`d'(I - Pi(theta)) = d(theta) Pi'(theta)`.

### 5. The final calculation is just substitution and reassociation

The closing `calc` block performs the algebra:

1. replace `J'` by `d' ⬝ᵥ r` using `hJ_eq`
2. replace `r` by `(I - Pi(theta)) q(theta)` using `hBellman_q_theta`
3. reassociate with `Matrix.dotProduct_mulVec` to get
   `Matrix.vecMul d' (1 - PiM theta) ⬝ᵥ q theta`
4. replace `Matrix.vecMul d' (1 - PiM theta)` by `Matrix.vecMul (d theta) PiM'` using `hBellman_d_eq`

The result is the claimed theorem:

`J' = Matrix.vecMul (d theta) PiM' ⬝ᵥ q theta`.

## Review notes

- The attempt compiles cleanly; there is no proof failure to repair.
- The argument is faithful to the visible natural-language proof and the source PDF.
- The main readability cost is that the differentiated Bellman identity for `d` is proved by explicit coordinate expansion, because no higher-level matrix calculus lemma is used from the visible context.
- `hJ_right` remains unused except for `let _ := hJ_right`, which suppresses an unused-hypothesis warning while keeping the original theorem statement unchanged.
