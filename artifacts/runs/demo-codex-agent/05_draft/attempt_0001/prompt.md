You are the Lean-draft turn in a bounded compile-repair loop.
Return JSON only. Produce Lean 4 code for `FormalizationEngineWorkspace/Generated.lean`.
The `content` field must contain the full file contents, including imports.
Do not use `sorry`. If there is prior compiler feedback, fix that exact failure first.

Approved formalization plan:
{
  "helper_definitions": [],
  "imports": [
    "FormalizationEngineWorkspace.Basic"
  ],
  "proof_sketch": [
    "Import the local workspace basics module.",
    "State `theorem zero_add_nat (n : Nat) : 0 + n = n`.",
    "Use the standard lemma `Nat.zero_add` and finish with `simpa using Nat.zero_add n`."
  ],
  "target_statement": "theorem zero_add_nat (n : Nat) : 0 + n = n",
  "theorem_name": "zero_add_nat"
}

Repair context:
{
  "attempts_remaining": 3,
  "current_attempt": 1,
  "max_attempts": 3,
  "previous_draft": null,
  "previous_result": null,
  "prior_attempts": 0
}
