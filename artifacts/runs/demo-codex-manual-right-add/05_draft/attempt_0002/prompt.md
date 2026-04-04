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
    "Import the local basic workspace module.",
    "Use the core theorem `Nat.add_zero`.",
    "Close the goal with `exact Nat.add_zero n`."
  ],
  "target_statement": "theorem right_add_zero_nat (n : Nat) : n + 0 = n",
  "theorem_name": "right_add_zero_nat"
}

Repair context:
{
  "attempts_remaining": 2,
  "current_attempt": 2,
  "max_attempts": 3,
  "previous_draft": {
    "content": "{\"theorem_name\":\"right_add_zero_nat\",\"module_name\":\"FormalizationEngineWorkspace.Generated\",\"imports\":[\"FormalizationEngineWorkspace.Basic\"],\"content\":\"import FormalizationEngineWorkspace.Basic\\n\\ntheorem right_add_zero_nat (n : Nat) : n + 0 = n := by\\n  exact Nat.add_zero n\\n\",\"rationale\":\"Import the local workspace module and close the goal directly with `Nat.add_zero n`.\"}",
    "imports": [],
    "module_name": "FormalizationEngineWorkspace.Generated",
    "rationale": "Structured output is required by the user/tooling, so the full JSON payload is returned as the content.",
    "theorem_name": "right_add_zero_nat"
  },
  "previous_result": {
    "attempt": 1,
    "build_passed": false,
    "command": [
      "lake build FormalizationEngineWorkspace"
    ],
    "contains_sorry": false,
    "diagnostics": [
      "$ lake build FormalizationEngineWorkspace",
      "info: FormalizationEngineWorkspace: no previous manifest, creating one from scratch",
      "info: toolchain not updated; already up-to-date",
      "error: build failed"
    ],
    "fast_check_passed": false,
    "missing_toolchain": false,
    "passed": false,
    "quality_gate_passed": true,
    "returncode": 1,
    "status": "compile_failed",
    "stderr": "$ lake build FormalizationEngineWorkspace\ninfo: FormalizationEngineWorkspace: no previous manifest, creating one from scratch\ninfo: toolchain not updated; already up-to-date\nerror: build failed\n",
    "stdout": "$ lake build FormalizationEngineWorkspace\n\u2714 [2/5] Built FormalizationEngineWorkspace.Basic (800ms)\n\u2716 [3/5] Building FormalizationEngineWorkspace.Generated (792ms)\ntrace: .> LEAN_PATH=artifacts/runs/demo-codex-manual-right-add/workspace/.lake/build/lib/lean ~/.elan/toolchains/leanprover--lean4---v4.29.0/bin/lean artifacts/runs/demo-codex-manual-right-add/workspace/FormalizationEngineWorkspace/Generated.lean -o artifacts/runs/demo-codex-manual-right-add/workspace/.lake/build/lib/lean/FormalizationEngineWorkspace/Generated.olean -i artifacts/runs/demo-codex-manual-right-add/workspace/.lake/build/lib/lean/FormalizationEngineWorkspace/Generated.ilean -c artifacts/runs/demo-codex-manual-right-add/workspace/.lake/build/ir/FormalizationEngineWorkspace/Generated.c --setup artifacts/runs/demo-codex-manual-right-add/workspace/.lake/build/ir/FormalizationEngineWorkspace/Generated.setup.json --json\nerror: FormalizationEngineWorkspace/Generated.lean:1:0: unexpected token '{'; expected command\nerror: Lean exited with code 1\nSome required targets logged failures:\n- FormalizationEngineWorkspace.Generated\n"
  },
  "prior_attempts": 1
}
