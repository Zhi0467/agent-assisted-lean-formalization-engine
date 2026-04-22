Key Mathlib objects to reuse for the downstream proof:

- `Matrix.dotProduct` in `Mathlib/Data/Matrix/Mul.lean:72`. This is the scalar pairing for vectors indexed by a finite type, and it matches the source's `d · r`, `p0 · q`, and the final scalar `d Pi' q`.
- `Matrix.dotProduct_assoc` in `Mathlib/Data/Matrix/Mul.lean:80`. This is the basic reassociation lemma for converting between `u · (M v)` and `(u M) · v`.
- `Matrix.mulVec` in `Mathlib/Data/Matrix/Mul.lean:698` and `Matrix.vecMul` in `Mathlib/Data/Matrix/Mul.lean:711`. These are the right and left matrix-vector actions needed for the Bellman identities `r = (I - Pi) q` and `p0 = d (I - Pi)`.
- `Matrix.dotProduct_mulVec` in `Mathlib/Data/Matrix/Mul.lean:749` and `Matrix.vecMul_mulVec` in `Mathlib/Data/Matrix/Mul.lean:1080`. These are likely the most direct lemmas for turning the scalar expression in the conclusion into a form compatible with the Bellman identities.
- `HasDerivAt` for Pi-valued functions is supported by Mathlib's calculus stack; see `Mathlib/Analysis/Calculus/Deriv/Pi.lean`. This is the relevant derivative interface for `d`, `q`, and matrix-valued `PiM` when the parameter space is `R`.
- `Matrix.mulVecLin` and the operator-norm material in `Mathlib/Analysis/Matrix/Normed.lean` are useful if the proof worker chooses to package matrix multiplication as continuous linear maps before applying derivative rules.

Visible gaps in the current context:

- No existing policy-gradient theorem or reinforcement-learning-specific library objects were found in the visible Lean surface.
- The provided source PDF does not state a formal theorem that justifies differentiating the infinite matrix series directly. The downstream proof should therefore work from the explicit local Bellman hypotheses in `theorem_statement.lean`, not assume a hidden summability or matrix-geometric-series theorem.
