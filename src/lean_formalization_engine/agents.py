from __future__ import annotations

from typing import Protocol, Tuple

from .models import (
    AgentTurn,
    ContextPack,
    EnrichmentReport,
    FormalizationPlan,
    LeanDraft,
    RepairContext,
    SourceRef,
    TheoremExtraction,
)


class FormalizationAgent(Protocol):
    name: str

    def draft_theorem_extraction(
        self,
        source_ref: SourceRef,
        source_text: str,
        normalized_text: str,
    ) -> Tuple[TheoremExtraction, AgentTurn]:
        ...

    def draft_theorem_enrichment(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        extraction_markdown: str,
    ) -> Tuple[EnrichmentReport, AgentTurn]:
        ...

    def draft_formalization_plan(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        enrichment: EnrichmentReport,
        context_pack: ContextPack,
    ) -> Tuple[FormalizationPlan, AgentTurn]:
        ...

    def draft_lean_file(
        self,
        plan: FormalizationPlan,
        repair_context: RepairContext,
    ) -> Tuple[LeanDraft, AgentTurn]:
        ...
