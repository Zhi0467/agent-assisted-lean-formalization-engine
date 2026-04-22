# Review Walkthrough

## Context

- Reviewed against the provided theorem statement, natural-language statement, natural-language proof, relevant Lean object inventory, enrichment review note, source PDF, and the current attempt plus its compile result.
- No `plan_handoff` pointer was supplied in the listed context surface, so this walkthrough does not assume any additional hidden proof plan.
- The current attempt compiled successfully, so this walkthrough explains why the Lean proof matches the intended mathematics rather than diagnosing a broken proof.

## What the Lean file is proving

The theorem is the local-series formulation of the policy gradient theorem:

- `d t = Σ_k p0 (Π t)^k`
- `q t = Σ_k (Π t)^k r`
- `J t = Σ_k p0 (Π t)^k r`

under differentiability of `Π` and `d` at `theta`, the proof shows

- `J'(theta) = d(theta) Π'(theta) q(theta)`

written in Lean as

- `dotProduct (Matrix.vecMul (d theta) Pi') (q theta)`.

This matches the source PDF's "The Correct Proof" route and the enrichment-side natural-language proof.

## Proof map from Lean to mathematics

### 1. Continuous-linear wrappers for differentiation

`dotProductCLM` and `vecMulCLM` package the bilinear operations

- `dotProduct`
- `Matrix.vecMul`

as continuous linear maps in the form expected by `hasFDerivAt_of_bilinear`. These are infrastructure only; they do not add mathematical content.

### 2. `rowBellman` derives `p0 = d (1 - A)`

`rowBellman` starts from

- `HasSum (fun k => Matrix.vecMul p0 (A ^ k)) d`.

It then:

1. names the summand `f k = p0 A^k`;
2. maps the series through right-multiplication by `A`;
3. rewrites the mapped series as the shifted tail `f (k + 1)` using `Matrix.vecMul_vecMul` and `pow_succ`;
4. uses `HasSum.zero_add` to split off the `k = 0` term;
5. identifies the sum uniquely to get `d = p0 + d A`;
6. rearranges to `p0 = d - d A = d (1 - A)`.

This is exactly the row Bellman identity from step 1 of the natural-language proof.

### 3. `colBellman` derives `r = (1 - A) q`

`colBellman` is the column-vector analogue:

- start from `HasSum (fun k => Matrix.mulVec (A ^ k) r) q`,
- shift the tail via left-multiplication by `A`,
- use `Matrix.mulVec_mulVec` and `pow_succ'`,
- split off the `k = 0` term,
- conclude `q = r + A q`,
- rearrange to `r = q - A q = (1 - A) q`.

This is step 2 of the natural-language proof.

### 4. `jEqDot` derives `J = d ⋅ r`

`jEqDot` uses the occupancy series and the `J` series:

- it maps the `d`-series through the continuous linear functional `x ↦ dotProduct x r`;
- after a `dotProduct_comm` rewrite, the mapped sum is exactly the scalar series defining `J`;
- `HasSum.unique` then yields `J = dotProduct d r`.

This is step 3 of the natural-language proof, specialized to the `J = d ⋅ r` branch.

### 5. The main theorem first turns local series hypotheses into local identities

Inside `policy_gradient_theorem_of_local_series`, the eventual `HasSum` hypotheses near `theta` are turned into eventual equalities:

- `hrow : p0 = d(t) (1 - Π(t))` eventually, via `rowBellman`;
- `hcol : r = (1 - Π(t)) q(t)` eventually, via `colBellman`;
- `hJdot : J(t) = d(t) ⋅ r` eventually, via `jEqDot`.

This matches step 4 of the natural-language proof: the identities are proved pointwise for every nearby `t`, then promoted to statements valid eventually on `𝓝 theta`.

### 6. Differentiate `J(t) = d(t) ⋅ r`

`hJ_deriv` differentiates the eventual identity

- `J(t) = dotProduct (d t) r`

using the derivative of `d` and the fact that `r` is constant. The continuous-bilinear packaging in `dotProductCLM` supplies the product rule, yielding

- `J'(theta) = dotProduct d' r`.

This is step 5 of the natural-language proof.

### 7. Differentiate `p0 = d(t) (1 - Π(t))`

The proof next differentiates the row Bellman identity:

- `hrow_zero` says the derivative of `t ↦ d(t) (1 - Π(t))` is `0`, because this function is eventually equal to the constant `p0`;
- `hrow_formula` computes the same derivative by the bilinear product rule:
  `d'(1 - Π(theta)) - d(theta) Π'`;
- `HasDerivAt.unique` forces these derivatives to agree, giving
  `d'(1 - Π(theta)) = d(theta) Π'`.

In Lean this is

- `Matrix.vecMul d' (1 - Pi theta) = Matrix.vecMul (d theta) Pi'`.

This is step 6 of the natural-language proof.

### 8. Evaluate the column Bellman identity at `theta`

`hcol_theta` converts the eventual equality

- `r = (1 - Π(t)) q(t)`

into the pointwise identity at the base point

- `r = (1 - Π(theta)) q(theta)`.

This is step 7's substitution input.

### 9. Finish by substitution and reassociation

`hfinal` performs the last chain of equalities:

1. replace `r` by `(1 - Π(theta)) q(theta)`;
2. reassociate `dotProduct d' ((1 - Π(theta)) q(theta))` into
   `dotProduct (d'(1 - Π(theta))) q(theta)` using `Matrix.dotProduct_mulVec`;
3. replace `d'(1 - Π(theta))` by `d(theta) Π'` using the differentiated row Bellman identity.

The result is exactly

- `dotProduct d' r = dotProduct (Matrix.vecMul (d theta) Pi') (q theta)`.

Combined with `hJ_deriv`, this yields the theorem.

## Review conclusion

- The Lean proof follows the intended mathematics closely.
- It uses only the generic ingredients anticipated in `relevant_lean_objects.md`: `HasSum` manipulations, matrix reassociation lemmas, and bilinear differentiation.
- The proof takes the `J = d ⋅ r` route and does not use the symmetric `J = p0 ⋅ q` route from the source PDF, but that is a legitimate specialization of the same argument.
- Since the attempt compiled cleanly, the main value of this review is readability and trust, not repair of a failing proof.
