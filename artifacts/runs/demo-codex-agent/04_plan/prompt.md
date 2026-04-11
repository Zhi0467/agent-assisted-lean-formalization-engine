You are the formalization-plan turn for a Lean 4 workflow.
Return JSON only. Produce the Lean-facing theorem target and a concise proof plan.
Prefer the simplest imports that fit the local workspace, and keep helper definitions empty unless they are genuinely needed.

Approved theorem spec:
{
  "ambiguities": [],
  "assumptions": [
    "n : Nat"
  ],
  "conclusion": "0 + n = n",
  "informal_statement": "For every natural number `n`, adding zero on the left gives back `n`.\n\nTarget statement: `0 + n = n`.",
  "paraphrase": "For every natural number n, adding zero on the left returns n.",
  "symbols": [
    "0",
    "+",
    "Nat"
  ],
  "title": "Zero-add on natural numbers"
}

Local context pack:
{
  "local_examples": [
    "examples/inputs/zero_add.md"
  ],
  "notes": [
    "Title: Zero-add on natural numbers",
    "Start from repo-local examples before adding retrieval or external corpora."
  ],
  "recommended_imports": [
    "FormalizationEngineWorkspace.Basic"
  ]
}
