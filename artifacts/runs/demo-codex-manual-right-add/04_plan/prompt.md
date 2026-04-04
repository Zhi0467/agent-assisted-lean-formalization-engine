You are the formalization-plan turn for a Lean 4 workflow.
Return JSON only. Produce the Lean-facing theorem target and a concise proof plan.
Prefer the simplest imports that fit the local workspace, and keep helper definitions empty unless they are genuinely needed.

Approved theorem spec:
{
  "ambiguities": [],
  "assumptions": [
    "n ranges over Lean's natural numbers `Nat`.",
    "`+` and `0` are the standard addition and zero on `Nat`.",
    "The statement is universally quantified over `n` with no extra hypotheses."
  ],
  "conclusion": "forall n : Nat, n + 0 = n",
  "informal_statement": "For every natural number n, adding zero on the right leaves n unchanged.",
  "paraphrase": "Zero is a right identity for addition on the natural numbers.",
  "symbols": [
    "n : Nat",
    "0 : Nat",
    "+ : Nat -> Nat -> Nat"
  ],
  "title": "Right Addition by Zero on Naturals"
}

Local context pack:
{
  "local_examples": [
    "examples/inputs/zero_add.md"
  ],
  "notes": [
    "Title: Right Addition by Zero on Naturals",
    "Start from repo-local examples before adding retrieval or external corpora."
  ],
  "recommended_imports": [
    "FormalizationEngineWorkspace.Basic"
  ]
}
