from __future__ import annotations

from typing import Protocol

from .models import AgentTurn, FormalizationPlan, LeanDraft, TheoremSpec


class FormalizationAgent(Protocol):
    def draft_spec(self, normalized_text: str) -> AgentTurn:
        ...

    def draft_plan(self, theorem_spec: TheoremSpec) -> AgentTurn:
        ...

    def draft_lean(self, theorem_spec: TheoremSpec, plan: FormalizationPlan) -> AgentTurn:
        ...

    def repair_lean(
        self,
        theorem_spec: TheoremSpec,
        plan: FormalizationPlan,
        previous_draft: LeanDraft,
        diagnostics: str,
        attempt: int,
    ) -> AgentTurn:
        ...
