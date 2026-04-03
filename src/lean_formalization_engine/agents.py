from __future__ import annotations

from typing import Optional, Protocol, Tuple

from .models import (
    AgentTurn,
    CompileAttempt,
    ContextPack,
    FormalizationPlan,
    LeanDraft,
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
        attempt: int,
        previous_result: Optional[CompileAttempt],
    ) -> Tuple[LeanDraft, AgentTurn]:
        ...
