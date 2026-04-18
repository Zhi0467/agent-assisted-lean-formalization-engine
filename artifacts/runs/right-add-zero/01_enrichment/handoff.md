# Enrichment Handoff

## Source Summary

Natural-language claim: for every natural number `n`, adding zero on the right leaves `n` unchanged.

Original normalized target: `n + 0 = n`.

Provenance:

- extraction method: `plain_text`
- source kind: `markdown`
- source path: `examples/inputs/right_add_zero.md`

## Formalization Target

Interpret the variable as universally quantified over natural numbers:

```lean
theorem right_add_zero (n : Nat) : n + 0 = n
```

Equivalent proposition form:

```lean
forall n : Nat, n + 0 = n
```

## Lean Notes

- Domain is `Nat`.
- There are no side conditions or hidden assumptions.
- This is the standard right-identity law for natural-number addition.
- In Lean, the target is already available as `Nat.add_zero`.

Direct proof sketch:

```lean
theorem right_add_zero (n : Nat) : n + 0 = n := by
  simpa using Nat.add_zero n
```

If a standalone proof is preferred instead of reusing the library theorem, induction on `n` is the natural fallback strategy.

## Suggested Handoff To Formalization

- Introduce one variable: `n : Nat`.
- State the theorem exactly as `n + 0 = n`.
- Prefer discharging it via `Nat.add_zero`.
- If library reuse is disallowed, prove by induction on `n`.
