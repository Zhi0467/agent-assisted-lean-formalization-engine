from __future__ import annotations

import json
from dataclasses import asdict
from typing import Tuple

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


class DemoFormalizationAgent:
    """Deterministic agent used to exercise the Terry workflow end to end."""

    name = "demo_zero_add_agent"

    def draft_theorem_extraction(
        self,
        source_ref: SourceRef,
        source_text: str,
        normalized_text: str,
    ) -> Tuple[TheoremExtraction, AgentTurn]:
        lowered = normalized_text.lower()
        if "0 + n = n" not in normalized_text and "zero on the left" not in lowered:
            raise ValueError(
                "The demo agent only supports the shipped zero-add example. "
                "Use the Codex or command backend for broader theorem coverage."
            )

        extraction = TheoremExtraction(
            title="Zero-add on natural numbers",
            informal_statement=normalized_text.strip(),
            definitions=[
                "Nat: the variable ranges over natural numbers.",
                "Left addition by zero: the target expression is `0 + n`.",
            ],
            lemmas=["Nat.zero_add: proves the target theorem directly."],
            propositions=[],
            dependencies=[
                "definition: Nat -- needed to type the quantified variable.",
                "notation: `0 + n` -- needed to state the theorem.",
                "lemma: Nat.zero_add -- sufficient to complete the proof.",
            ],
            notes=["The example already fits standard natural-number infrastructure."],
        )
        turn = AgentTurn(
            request_payload={
                "stage": "draft_theorem_extraction",
                "source_path": source_ref.path,
                "source_text": source_text,
                "normalized_text": normalized_text,
            },
            prompt=(
                "Extract the theorem statement and prerequisite dependency chain from the source.\n"
                f"Source: {source_ref.path}\n"
            ),
            raw_response=json.dumps(asdict(extraction), indent=2, sort_keys=True),
        )
        return extraction, turn

    def draft_theorem_enrichment(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        extraction_markdown: str,
    ) -> Tuple[EnrichmentReport, AgentTurn]:
        enrichment = EnrichmentReport(
            self_contained=True,
            satisfied_prerequisites=[
                "Natural numbers and addition are already available in Lean/mathlib.",
                "`Nat.zero_add` is already available for the proof.",
            ],
            missing_prerequisites=[],
            required_plan_additions=[],
            recommended_scope="Keep the theorem over `Nat` and reuse `Nat.zero_add`.",
            difficulty_assessment="easy",
            open_questions=[],
            next_steps=[
                "Approve the enrichment handoff.",
                "Lock the formal statement and Lean theorem name.",
                "Run the prove-and-repair loop after plan approval.",
            ],
            human_handoff=(
                "The theorem is already self-contained for Lean. "
                "No extra prerequisites are needed before plan approval."
            ),
        )
        turn = AgentTurn(
            request_payload={
                "stage": "draft_theorem_enrichment",
                "source_path": source_ref.path,
                "source_text": source_text,
                "extraction": asdict(extraction),
                "extraction_markdown": extraction_markdown,
            },
            prompt=(
                "Check whether the extracted theorem package is self-contained and note any missing prerequisites.\n"
                f"Source: {source_ref.path}\n"
            ),
            raw_response=json.dumps(asdict(enrichment), indent=2, sort_keys=True),
        )
        return enrichment, turn

    def draft_formalization_plan(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        enrichment: EnrichmentReport,
        context_pack: ContextPack,
    ) -> Tuple[FormalizationPlan, AgentTurn]:
        plan = FormalizationPlan(
            title=extraction.title,
            informal_statement=extraction.informal_statement,
            assumptions=["n : Nat"],
            conclusion="0 + n = n",
            symbols=["0", "+", "Nat"],
            ambiguities=[],
            paraphrase="For every natural number n, adding zero on the left returns n.",
            theorem_name="zero_add_demo",
            imports=["FormalizationEngineWorkspace.Basic"],
            prerequisites_to_formalize=enrichment.required_plan_additions,
            helper_definitions=[],
            target_statement="theorem zero_add_demo (n : Nat) : 0 + n = n",
            proof_sketch=[
                "Import the local basic workspace module.",
                "Use `Nat.zero_add` directly.",
                "Close the theorem with `simpa`.",
            ],
            human_summary=(
                "The plan keeps the theorem exactly over `Nat`, names it `zero_add_demo`, "
                "and proves it with `Nat.zero_add` inside the local workspace scaffold."
            ),
        )
        turn = AgentTurn(
            request_payload={
                "stage": "draft_formalization_plan",
                "source_path": source_ref.path,
                "source_text": source_text,
                "extraction": asdict(extraction),
                "enrichment": asdict(enrichment),
                "context_pack": asdict(context_pack),
            },
            prompt=(
                "Produce the merged plan checkpoint: mathematical meaning, Lean theorem target, "
                "imports, and proof sketch.\n"
                f"Source: {source_ref.path}\n"
            ),
            raw_response=json.dumps(asdict(plan), indent=2, sort_keys=True),
        )
        return plan, turn

    def draft_lean_file(
        self,
        plan: FormalizationPlan,
        repair_context: RepairContext,
    ) -> Tuple[LeanDraft, AgentTurn]:
        diagnostics = ""
        if repair_context.previous_result is not None:
            diagnostics = repair_context.previous_result.stderr or repair_context.previous_result.stdout

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
            f"Attempt: {repair_context.current_attempt}/{repair_context.max_attempts}\n"
            f"Target statement: {plan.target_statement}\n"
        )
        if repair_context.human_feedback:
            prompt += f"\nHuman feedback:\n{repair_context.human_feedback}\n"
        if diagnostics:
            prompt += f"\nPrevious diagnostics:\n{diagnostics}\n"
        turn = AgentTurn(
            request_payload={
                "stage": "draft_lean_file",
                "plan": asdict(plan),
                "repair_context": asdict(repair_context),
            },
            prompt=prompt,
            raw_response=content,
        )
        return draft, turn
