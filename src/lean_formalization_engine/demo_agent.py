from __future__ import annotations

from .models import AgentTurn, FormalizationPlan, LeanDraft, TheoremSpec, to_jsonable


class DemoFormalizationAgent:
    """Deterministic agent used to exercise the scaffold end to end."""

    def draft_spec(self, normalized_text: str) -> AgentTurn:
        theorem_spec = TheoremSpec(
            title="Zero Add",
            informal_statement=normalized_text,
            assumptions=["n is a natural number"],
            conclusion="0 + n = n",
            symbols=["0", "+", "n", "Nat"],
            ambiguities=[],
        )
        prompt = (
            "Read the theorem text and produce a structured theorem specification with "
            "assumptions, conclusion, symbols, and ambiguities."
        )
        raw_response = (
            "Structured theorem spec: title=Zero Add, assumptions=[n : Nat], "
            "conclusion=0 + n = n, ambiguities=[]"
        )
        return AgentTurn(
            prompt=prompt,
            request_payload={"normalized_text": normalized_text},
            raw_response=raw_response,
            parsed_output=theorem_spec,
        )

    def draft_plan(self, theorem_spec: TheoremSpec) -> AgentTurn:
        plan = FormalizationPlan(
            theorem_name="zero_add_demo",
            imports=[],
            helper_definitions=[],
            proof_strategy=[
                "Use the core theorem Nat.zero_add.",
                "Finish the goal with simpa.",
            ],
            target_statement="theorem zero_add_demo (n : Nat) : 0 + n = n",
        )
        prompt = (
            "Given the approved theorem specification, choose a theorem name, imports, "
            "target statement, and proof strategy."
        )
        raw_response = (
            "Plan: theorem zero_add_demo (n : Nat) : 0 + n = n := by "
            "simpa using Nat.zero_add n"
        )
        return AgentTurn(
            prompt=prompt,
            request_payload={"theorem_spec": to_jsonable(theorem_spec)},
            raw_response=raw_response,
            parsed_output=plan,
        )

    def draft_lean(self, theorem_spec: TheoremSpec, plan: FormalizationPlan) -> AgentTurn:
        draft = LeanDraft(
            theorem_name=plan.theorem_name,
            code=(
                "theorem zero_add_demo (n : Nat) : 0 + n = n := by\n"
                "  simpa using Nat.zero_add n\n"
            ),
            rationale=[
                "The theorem uses only core Lean naturals.",
                "Nat.zero_add discharges the goal directly.",
            ],
        )
        prompt = "Produce a full Lean file that matches the approved formalization plan."
        raw_response = draft.code
        return AgentTurn(
            prompt=prompt,
            request_payload={
                "theorem_spec": to_jsonable(theorem_spec),
                "plan": to_jsonable(plan),
            },
            raw_response=raw_response,
            parsed_output=draft,
        )

    def repair_lean(
        self,
        theorem_spec: TheoremSpec,
        plan: FormalizationPlan,
        previous_draft: LeanDraft,
        diagnostics: str,
        attempt: int,
    ) -> AgentTurn:
        prompt = "Repair the Lean draft using the compile diagnostics."
        raw_response = previous_draft.code
        return AgentTurn(
            prompt=prompt,
            request_payload={
                "theorem_spec": to_jsonable(theorem_spec),
                "plan": to_jsonable(plan),
                "previous_draft": to_jsonable(previous_draft),
                "diagnostics": diagnostics,
                "attempt": attempt,
            },
            raw_response=raw_response,
            parsed_output=previous_draft,
        )
