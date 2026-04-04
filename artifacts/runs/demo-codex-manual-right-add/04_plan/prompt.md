You are the formalization-plan turn for a Lean 4 workflow.
Return JSON only. Produce the Lean-facing theorem target and a concise proof plan.
Prefer the simplest imports that fit the local workspace, and keep helper definitions empty unless they are genuinely needed.

Approved theorem spec:
{
  "ambiguities": [],
  "assumptions": [
    "n : Nat"
  ],
  "conclusion": "n + 0 = n",
  "informal_statement": "For every natural number n, adding zero on the right leaves n unchanged.\nTarget statement: n + 0 = n.",
  "paraphrase": "For every natural number n, n plus zero equals n.",
  "symbols": [
    "0",
    "+",
    "Nat"
  ],
  "title": "Right-add-zero on natural numbers"
}

Local context pack:
{
  "local_examples": [
    "examples/inputs/zero_add.md"
  ],
  "notes": [
    "Title: Right-add-zero on natural numbers",
    "Start from repo-local examples before adding retrieval or external corpora."
  ],
  "recommended_imports": [
    "FormalizationEngineWorkspace.Basic"
  ]
}
