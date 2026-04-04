from __future__ import annotations

import json
import sys


def _spec_response(request: dict[str, object]) -> dict[str, object]:
    normalized_text = str(request["normalized_text"]).strip()
    parsed_output = {
        "title": "Zero-add on natural numbers",
        "informal_statement": normalized_text,
        "assumptions": ["n : Nat"],
        "conclusion": "0 + n = n",
        "symbols": ["0", "+", "Nat"],
        "ambiguities": [],
        "paraphrase": "For every natural number n, adding zero on the left returns n.",
    }
    return {
        "prompt": "Extract a theorem specification from the normalized theorem source.",
        "raw_response": json.dumps(parsed_output, indent=2, sort_keys=True),
        "parsed_output": parsed_output,
    }


def _plan_response(request: dict[str, object]) -> dict[str, object]:
    theorem_spec = request["theorem_spec"]
    parsed_output = {
        "theorem_name": "zero_add_provider_demo",
        "imports": ["FormalizationEngineWorkspace.Basic"],
        "helper_definitions": [],
        "target_statement": "theorem zero_add_provider_demo (n : Nat) : 0 + n = n",
        "proof_sketch": [
            f"Formalize the approved theorem titled {theorem_spec['title']}.",
            "Use the local basic workspace module.",
            "Repair once compiler or quality feedback arrives.",
        ],
    }
    return {
        "prompt": "Produce a Lean-facing plan for the approved theorem specification.",
        "raw_response": json.dumps(parsed_output, indent=2, sort_keys=True),
        "parsed_output": parsed_output,
    }


def _draft_response(request: dict[str, object]) -> dict[str, object]:
    plan = request["plan"]
    repair_context = request["repair_context"]
    previous_result = repair_context["previous_result"]

    if previous_result is None:
        content = "\n".join(
            [
                "import FormalizationEngineWorkspace.Basic",
                "",
                "theorem zero_add_provider_demo (n : Nat) : 0 + n = n := by",
                "  sorry",
                "",
            ]
        )
        rationale = "Start with a skeletal proof so the repair path has concrete feedback."
    else:
        diagnostics = previous_result.get("diagnostics", [])
        if not previous_result.get("contains_sorry"):
            raise RuntimeError(
                "The scripted repair provider expected the first failure to come from `sorry`."
            )
        content = "\n".join(
            [
                "import FormalizationEngineWorkspace.Basic",
                "",
                "theorem zero_add_provider_demo (n : Nat) : 0 + n = n := by",
                "  simpa using Nat.zero_add n",
                "",
            ]
        )
        rationale = (
            "Repair the draft using the previous compile result. "
            f"Observed diagnostics: {diagnostics}"
        )

    parsed_output = {
        "theorem_name": plan["theorem_name"],
        "module_name": "FormalizationEngineWorkspace.Generated",
        "imports": plan["imports"],
        "content": content,
        "rationale": rationale,
    }
    return {
        "prompt": (
            "Generate a Lean file from the approved plan.\n"
            f"Attempt: {repair_context['current_attempt']}/{repair_context['max_attempts']}\n"
            f"Attempts remaining: {repair_context['attempts_remaining']}\n"
        ),
        "raw_response": content,
        "parsed_output": parsed_output,
    }


def main() -> int:
    request = json.load(sys.stdin)
    stage = request.get("stage")

    if stage == "draft_theorem_spec":
        response = _spec_response(request)
    elif stage == "draft_formalization_plan":
        response = _plan_response(request)
    elif stage == "draft_lean_file":
        response = _draft_response(request)
    else:
        raise RuntimeError(f"Unsupported stage: {stage}")

    json.dump(response, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
