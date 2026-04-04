from __future__ import annotations

from typing import Protocol, Tuple

from .models import (
    AgentTurn,
    ContextPack,
    FormalizationPlan,
    LeanDraft,
    RepairContext,
    SourceRef,
    TheoremSpec,
)


class FormalizationAgent(Protocol):
    name: str

    def draft_theorem_spec(
        self,
        source_ref: SourceRef,
        normalized_text: str,
    ) -> Tuple[TheoremSpec, AgentTurn]:
        ...

    def draft_formalization_plan(
        self,
        theorem_spec: TheoremSpec,
        context_pack: ContextPack,
    ) -> Tuple[FormalizationPlan, AgentTurn]:
        ...

    def draft_lean_file(
        self,
        plan: FormalizationPlan,
        repair_context: RepairContext,
    ) -> Tuple[LeanDraft, AgentTurn]:
        ...
