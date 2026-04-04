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
    "Import the local workspace baseline module.",
    "State `theorem right_add_zero_nat (n : Nat) : n + 0 = n`.",
    "Use the standard library fact `Nat.add_zero n` to discharge the goal directly, with `exact` or `simpa`."
  ],
  "target_statement": "theorem right_add_zero_nat (n : Nat) : n + 0 = n",
  "theorem_name": "right_add_zero_nat"
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
