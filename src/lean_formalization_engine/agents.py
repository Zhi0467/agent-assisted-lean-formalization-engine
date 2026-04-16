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
    TheoremSpec,
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

    def draft_theorem_spec(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        enrichment: EnrichmentReport,
    ) -> Tuple[TheoremSpec, AgentTurn]:
        ...

    def draft_formalization_plan(
        self,
        theorem_spec: TheoremSpec,
        context_pack: ContextPack,
        enrichment: EnrichmentReport,
    ) -> Tuple[FormalizationPlan, AgentTurn]:
        ...

    def draft_lean_file(
        self,
        plan: FormalizationPlan,
        repair_context: RepairContext,
    ) -> Tuple[LeanDraft, AgentTurn]:
        ...
