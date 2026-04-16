from __future__ import annotations

import json
import sys


def _extraction_response(request: dict[str, object]) -> dict[str, object]:
    normalized_text = str(request["normalized_text"]).strip()
    parsed_output = {
        "title": "Zero-add on natural numbers",
        "informal_statement": normalized_text,
        "definitions": [
            "Nat: the variable ranges over natural numbers.",
            "Left addition by zero: the target expression is `0 + n`.",
        ],
        "lemmas": ["Nat.zero_add: proves the target theorem directly."],
        "propositions": [],
        "dependencies": [
            "definition: Nat -- needed to type the quantified variable.",
            "notation: `0 + n` -- needed to state the theorem.",
            "lemma: Nat.zero_add -- sufficient to complete the proof.",
        ],
        "notes": ["The example already fits standard natural-number infrastructure."],
    }
    return {
        "prompt": "Extract the theorem package and prerequisite dependency chain from the theorem source.",
        "raw_response": json.dumps(parsed_output, indent=2, sort_keys=True),
        "parsed_output": parsed_output,
    }


def _enrichment_response(_: dict[str, object]) -> dict[str, object]:
    parsed_output = {
        "self_contained": True,
        "satisfied_prerequisites": [
            "Natural numbers and addition are already available in Lean/mathlib.",
            "`Nat.zero_add` is already available for the proof.",
        ],
        "missing_prerequisites": [],
        "required_plan_additions": [],
        "recommended_scope": "Keep the theorem over `Nat` and reuse the existing core lemma.",
        "difficulty_assessment": "easy",
        "open_questions": [],
        "next_steps": [
            "Approve the enrichment handoff.",
            "Approve the merged plan checkpoint.",
            "Let Terry enter the prove-and-repair loop.",
        ],
        "human_handoff": (
            "The extracted theorem is already self-contained for Lean. "
            "All required prerequisites are present in the standard natural-number API, "
            "so the plan can stay focused on the theorem itself."
        ),
    }
    return {
        "prompt": "Check whether the extracted theorem package is self-contained and summarize what is missing.",
        "raw_response": json.dumps(parsed_output, indent=2, sort_keys=True),
        "parsed_output": parsed_output,
    }


def _plan_response(request: dict[str, object]) -> dict[str, object]:
    extraction = request["extraction"]
    enrichment = request["enrichment"]
    parsed_output = {
        "title": extraction["title"],
        "informal_statement": extraction["informal_statement"],
        "assumptions": ["n : Nat"],
        "conclusion": "0 + n = n",
        "symbols": ["0", "+", "Nat"],
        "ambiguities": [],
        "paraphrase": "For every natural number n, adding zero on the left returns n.",
        "theorem_name": "zero_add_provider_demo",
        "imports": ["FormalizationEngineWorkspace.Basic"],
        "prerequisites_to_formalize": enrichment["required_plan_additions"],
        "helper_definitions": [],
        "target_statement": "theorem zero_add_provider_demo (n : Nat) : 0 + n = n",
        "proof_sketch": [
            "Formalize the approved theorem inside the local workspace.",
            "Use the local basic workspace module.",
            "Repair once compiler or quality feedback arrives.",
        ],
        "human_summary": (
            "This plan keeps the theorem over `Nat`, names it `zero_add_provider_demo`, "
            "and proves it with `Nat.zero_add` after the proof loop sees compiler feedback."
        ),
    }
    return {
        "prompt": "Produce the merged mathematical-meaning and Lean-plan checkpoint.",
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

    if stage == "draft_theorem_extraction":
        response = _extraction_response(request)
    elif stage == "draft_theorem_enrichment":
        response = _enrichment_response(request)
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
