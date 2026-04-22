The downstream proof should reuse existing mathlib objects for series manipulation, matrix-vector algebra, and differentiation rather than introducing custom definitions.

- `HasSum.zero_add` and `HasSum.sum_range_add`:
  These are the standard shift lemmas for series over `ℕ`. They are the right tools for splitting off the `k = 0` term and rewriting the tail as a shifted series.

- `HasSum.unique`:
  After mapping a convergent series through a linear functional, this gives equality of the two resulting sums. It is the clean way to conclude `J t = dotProduct (d t) r` and `J t = dotProduct p0 (q t)`.

- `HasSum.mapL`:
  This is the standard lemma for pushing a convergent series through a continuous linear map. It should be used with the dot-product functionals from `d`-space and `q`-space to derive the scalar identities for `J`.

- `Matrix.vecMul_vecMul`:
  Reassociates row-vector/matrix/matrix multiplication:
  `Matrix.vecMul (Matrix.vecMul v M) N = Matrix.vecMul v (M * N)`.
  This is the key algebraic lemma for identifying the shifted tail in the `d`-series.

- `Matrix.mulVec_mulVec`:
  Reassociates matrix/matrix/column-vector multiplication:
  `M.mulVec (N.mulVec v) = (M * N).mulVec v`.
  This is the analogous lemma for the `q`-series.

- `Matrix.vecMul_one` and `Matrix.one_mulVec`:
  These discharge the `k = 0` terms after splitting the series.

- `Matrix.vecMul_sub` and `Matrix.sub_mulVec`:
  These rewrite multiplication by `1 - Pi t` into the difference of the two simpler terms needed for the Bellman identities.

- `Matrix.dotProduct_mulVec`:
  This is exactly the reassociation identity used in the last line of the proof:
  `dotProduct x (Matrix.mulVec A y) = dotProduct (Matrix.vecMul x A) y`.

- `Matrix.vecMulLinear`, `Matrix.mulVecLin`, and `dotProductBilin`:
  These provide the linear or bilinear packaging of the matrix operations. They are the natural mathlib entry points for differentiating identities involving `Matrix.vecMul`, `Matrix.mulVec`, and `dotProduct`.

Likely proof shape in Lean:

- First derive local Bellman identities from `hd_series` and `hq_series`.
- Then derive the local scalar identity `J t = dotProduct (d t) r` from `hd_series` and `hJ_series` using `HasSum.mapL`.
- Differentiate those local identities at `theta`.
- Finish with `Matrix.dotProduct_mulVec` and the evaluated Bellman identity for `q theta`.

Important gap:

- No policy-gradient-specific lemma or theorem is present in the provided context. The proof worker will need to assemble these standard mathlib pieces into a custom theorem for this run.
