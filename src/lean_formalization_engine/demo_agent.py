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
    TheoremSpec,
)


class DemoFormalizationAgent:
    """Deterministic agent used to exercise the scaffold end to end."""

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
                "Add a real provider adapter for broader theorem coverage."
            )

        extraction = TheoremExtraction(
            title="Zero-add on natural numbers",
            informal_statement=normalized_text.strip(),
            definitions=[
                "Nat: the theorem ranges over natural numbers.",
                "Left addition by zero: the expression `0 + n` is the target term being reduced.",
            ],
            lemmas=["Nat.zero_add: proves that left-addition by zero preserves any natural number."],
            propositions=[],
            dependencies=[
                "definition: Nat -- needed to type the quantified variable `n`.",
                "notation: `0 + n` -- needed to state the theorem.",
                "lemma: Nat.zero_add -- sufficient to close the proof directly in mathlib.",
            ],
            notes=["The example is already self-contained inside the standard natural-number API."],
        )
        turn = AgentTurn(
            request_payload={
                "stage": "draft_theorem_extraction",
                "source_path": source_ref.path,
                "source_text": source_text,
                "normalized_text": normalized_text,
            },
            prompt=(
                "Extract the theorem package and prerequisite dependency chain from the theorem text.\n"
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
                "Natural numbers and addition are already in Lean/mathlib.",
                "`Nat.zero_add` already proves the required statement.",
            ],
            missing_prerequisites=[],
            required_plan_additions=[],
            recommended_scope="Keep the theorem exactly as stated over `Nat`.",
            difficulty_assessment="easy",
            open_questions=[],
            next_steps=[
                "Approve the enrichment handoff.",
                "Draft the theorem spec from the extracted statement.",
                "Use `Nat.zero_add` directly in the Lean plan.",
            ],
            human_handoff=(
                "The extracted theorem is already self-contained for Lean. "
                "All required infrastructure lives in the standard natural-number API, "
                "so the formalization plan does not need extra definitions or external prerequisites."
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

    def draft_theorem_spec(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        enrichment: EnrichmentReport,
    ) -> Tuple[TheoremSpec, AgentTurn]:
        theorem_spec = TheoremSpec(
            title=extraction.title,
            informal_statement=extraction.informal_statement,
            assumptions=["n : Nat"],
            conclusion="0 + n = n",
            symbols=["0", "+", "Nat"],
            ambiguities=[],
            paraphrase="For every natural number n, adding zero on the left returns n.",
        )
        turn = AgentTurn(
            request_payload={
                "stage": "draft_theorem_spec",
                "source_path": source_ref.path,
                "source_text": source_text,
                "extraction": asdict(extraction),
                "enrichment": asdict(enrichment),
            },
            prompt=(
                "Extract a structured theorem specification from the approved extraction and enrichment.\n"
                f"Source: {source_ref.path}\n"
            ),
            raw_response=json.dumps(asdict(theorem_spec), indent=2, sort_keys=True),
        )
        return theorem_spec, turn

    def draft_formalization_plan(
        self,
        theorem_spec: TheoremSpec,
        context_pack: ContextPack,
        enrichment: EnrichmentReport,
    ) -> Tuple[FormalizationPlan, AgentTurn]:
        plan = FormalizationPlan(
            theorem_name="zero_add_demo",
            imports=["FormalizationEngineWorkspace.Basic"],
            prerequisites_to_formalize=enrichment.required_plan_additions,
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
                "enrichment": asdict(enrichment),
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
        repair_context: RepairContext,
    ) -> Tuple[LeanDraft, AgentTurn]:
        diagnostics = ""
        if repair_context.previous_result is not None:
            diagnostics = (
                repair_context.previous_result.stderr
                or repair_context.previous_result.stdout
            )

        content = "\n".join(
            [
                "import FormalizationEngineWorkspace.Basic",
                "",
                "theorem zero_add_demo (n : Nat) : 0 + n = n := by",
                "  exact Nat.zero_add n",
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
        if diagnostics:
            prompt += f"\nPrevious diagnostics:\n{diagnostics}\n"
        turn = AgentTurn(
            request_payload={
                "plan": asdict(plan),
                "repair_context": asdict(repair_context),
            },
            prompt=prompt,
            raw_response=content,
        )
        return draft, turn
