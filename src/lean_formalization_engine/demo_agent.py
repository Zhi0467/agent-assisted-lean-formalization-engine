from __future__ import annotations

import json
from dataclasses import asdict
from typing import Optional, Tuple

from .models import (
    AgentTurn,
    CompileAttempt,
    ContextPack,
    FormalizationPlan,
    LeanDraft,
    SourceRef,
    TheoremSpec,
)


class DemoFormalizationAgent:
    """Deterministic agent used to exercise the scaffold end to end."""

    name = "demo_zero_add_agent"

    def draft_theorem_spec(
        self,
        source_ref: SourceRef,
        normalized_text: str,
    ) -> Tuple[TheoremSpec, AgentTurn]:
        lowered = normalized_text.lower()
        if "0 + n = n" not in normalized_text and "zero on the left" not in lowered:
            raise ValueError(
                "The demo agent only supports the shipped zero-add example. "
                "Add a real provider adapter for broader theorem coverage."
            )

        theorem_spec = TheoremSpec(
            title="Zero-add on natural numbers",
            informal_statement=normalized_text.strip(),
            assumptions=["n : Nat"],
            conclusion="0 + n = n",
            symbols=["0", "+", "Nat"],
            ambiguities=[],
            paraphrase="For every natural number n, adding zero on the left returns n.",
        )
        turn = AgentTurn(
            request_payload={
                "source_path": source_ref.path,
                "normalized_text": normalized_text,
            },
            prompt=(
                "Extract a structured theorem specification from the normalized theorem text.\n"
                f"Source: {source_ref.path}\n"
            ),
            raw_response=json.dumps(asdict(theorem_spec), indent=2, sort_keys=True),
        )
        return theorem_spec, turn

    def draft_formalization_plan(
        self,
        theorem_spec: TheoremSpec,
        context_pack: ContextPack,
    ) -> Tuple[FormalizationPlan, AgentTurn]:
        plan = FormalizationPlan(
            theorem_name="zero_add_demo",
            imports=["FormalizationEngineWorkspace.Basic"],
            helper_definitions=[],
            target_statement="theorem zero_add_demo (n : Nat) : 0 + n = n",
            proof_sketch=[
                "Import the local basic workspace module.",
                "Use the core theorem `Nat.zero_add`.",
                "Close the goal with `simpa`.",
            ],
        )
        turn = AgentTurn(
            request_payload={
                "theorem_spec": asdict(theorem_spec),
                "context_pack": asdict(context_pack),
            },
            prompt=(
                "Produce a Lean-facing plan for the approved theorem spec.\n"
                f"Spec title: {theorem_spec.title}\n"
                f"Imports available: {', '.join(context_pack.recommended_imports)}\n"
            ),
            raw_response=json.dumps(asdict(plan), indent=2, sort_keys=True),
        )
        return plan, turn

    def draft_lean_file(
        self,
        plan: FormalizationPlan,
        attempt: int,
        previous_result: Optional[CompileAttempt],
    ) -> Tuple[LeanDraft, AgentTurn]:
        diagnostics = ""
        if previous_result is not None:
            diagnostics = previous_result.stderr or previous_result.stdout

        content = "\n".join(
            [
                "import FormalizationEngineWorkspace.Basic",
                "",
                "theorem zero_add_demo (n : Nat) : 0 + n = n := by",
                "  simpa using Nat.zero_add n",
                "",
            ]
        )
        draft = LeanDraft(
            theorem_name=plan.theorem_name,
            module_name="FormalizationEngineWorkspace.Generated",
            imports=plan.imports,
            content=content,
            rationale="Use the standard library theorem `Nat.zero_add` directly.",
        )
        prompt = (
            "Generate a full Lean file for the approved plan.\n"
            f"Attempt: {attempt}\n"
            f"Target statement: {plan.target_statement}\n"
        )
        if diagnostics:
            prompt += f"\nPrevious diagnostics:\n{diagnostics}\n"
        turn = AgentTurn(
            request_payload={
                "plan": asdict(plan),
                "attempt": attempt,
                "previous_result": asdict(previous_result) if previous_result else None,
            },
            prompt=prompt,
            raw_response=content,
        )
        return draft, turn
