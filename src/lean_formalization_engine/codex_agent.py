from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, TypeVar

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

ParsedOutput = TypeVar(
    "ParsedOutput",
    TheoremExtraction,
    EnrichmentReport,
    FormalizationPlan,
    LeanDraft,
)

_SCHEMA_URL = "https://json-schema.org/draft/2020-12/schema"
_STRING_ARRAY = {"type": "array", "items": {"type": "string"}}


class CodexCliFormalizationAgent:
    """Use `codex exec` as a live Terry backend."""

    def __init__(
        self,
        repo_root: Path,
        model: str | None = None,
        executable: str = "codex",
    ):
        self.repo_root = repo_root
        self.model = model
        self.executable = executable
        self.name = f"codex_cli:{model or 'default'}"

    def draft_theorem_extraction(
        self,
        source_ref: SourceRef,
        source_text: str,
        normalized_text: str,
    ) -> tuple[TheoremExtraction, AgentTurn]:
        request_payload = {
            "stage": "draft_theorem_extraction",
            "model": self.model,
            "source_ref": asdict(source_ref),
            "source_text": source_text,
            "normalized_text": normalized_text,
        }
        prompt = (
            "You are the extraction turn for Terry, a Lean 4 formalization workflow.\n"
            "Return JSON only. Extract the theorem statement, required definitions, "
            "lemmas, propositions, and an explicit dependency chain.\n\n"
            f"Source reference:\n{json.dumps(request_payload['source_ref'], indent=2, sort_keys=True)}\n\n"
            f"Original source statement:\n{source_text.strip()}\n\n"
            f"Normalized theorem source:\n{normalized_text.strip()}\n"
        )
        return self._invoke(
            request_payload=request_payload,
            prompt=prompt,
            response_type=TheoremExtraction,
            schema=_theorem_extraction_schema(),
        )

    def draft_theorem_enrichment(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        extraction_markdown: str,
    ) -> tuple[EnrichmentReport, AgentTurn]:
        request_payload = {
            "stage": "draft_theorem_enrichment",
            "model": self.model,
            "source_ref": asdict(source_ref),
            "source_text": source_text,
            "extraction": asdict(extraction),
            "extraction_markdown": extraction_markdown,
        }
        prompt = (
            "You are the enrichment turn for Terry, a Lean 4 formalization workflow.\n"
            "Return JSON only. Decide whether the theorem is self-contained, what "
            "standard Lean/mathlib prerequisites are already satisfied, what is missing, "
            "and what must remain explicit before the plan checkpoint. The `human_handoff` "
            "field should read like a concise note to the reviewer.\n\n"
            f"Source reference:\n{json.dumps(request_payload['source_ref'], indent=2, sort_keys=True)}\n\n"
            f"Original source statement:\n{source_text.strip()}\n\n"
            f"Extraction JSON:\n{json.dumps(request_payload['extraction'], indent=2, sort_keys=True)}\n\n"
            f"Extraction markdown:\n{extraction_markdown.strip()}\n"
        )
        return self._invoke(
            request_payload=request_payload,
            prompt=prompt,
            response_type=EnrichmentReport,
            schema=_enrichment_report_schema(),
        )

    def draft_formalization_plan(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        enrichment: EnrichmentReport,
        context_pack: ContextPack,
    ) -> tuple[FormalizationPlan, AgentTurn]:
        request_payload = {
            "stage": "draft_formalization_plan",
            "model": self.model,
            "source_ref": asdict(source_ref),
            "source_text": source_text,
            "extraction": asdict(extraction),
            "enrichment": asdict(enrichment),
            "context_pack": asdict(context_pack),
        }
        prompt = (
            "You are the merged plan turn for Terry, a Lean 4 formalization workflow.\n"
            "Return JSON only. This one checkpoint must lock the mathematical meaning and "
            "the Lean plan together. Include the informal theorem meaning, assumptions, "
            "conclusion, symbols, ambiguities, theorem name, imports, target statement, "
            "helper definitions, and proof sketch. Keep helper definitions empty unless "
            "they are genuinely needed.\n\n"
            f"Source reference:\n{json.dumps(request_payload['source_ref'], indent=2, sort_keys=True)}\n\n"
            f"Original source statement:\n{source_text.strip()}\n\n"
            f"Extraction JSON:\n{json.dumps(request_payload['extraction'], indent=2, sort_keys=True)}\n\n"
            f"Approved enrichment:\n{json.dumps(request_payload['enrichment'], indent=2, sort_keys=True)}\n\n"
            f"Local context pack:\n{json.dumps(request_payload['context_pack'], indent=2, sort_keys=True)}\n"
        )
        return self._invoke(
            request_payload=request_payload,
            prompt=prompt,
            response_type=FormalizationPlan,
            schema=_formalization_plan_schema(),
        )

    def draft_lean_file(
        self,
        plan: FormalizationPlan,
        repair_context: RepairContext,
    ) -> tuple[LeanDraft, AgentTurn]:
        request_payload = {
            "stage": "draft_lean_file",
            "model": self.model,
            "plan": asdict(plan),
            "repair_context": asdict(repair_context),
        }
        prompt = (
            "You are the Lean proving turn in Terry's bounded prove-and-repair loop.\n"
            "Return JSON only. Produce Lean 4 code for "
            "`FormalizationEngineWorkspace/Generated.lean`.\n"
            "The `content` field must contain the full file contents, including imports.\n"
            "Do not use `sorry`. If there is prior compiler feedback, fix that exact "
            "failure first. The theorem statement is locked by the approved plan.\n\n"
            f"Approved plan:\n{json.dumps(request_payload['plan'], indent=2, sort_keys=True)}\n\n"
            f"Repair context:\n{json.dumps(request_payload['repair_context'], indent=2, sort_keys=True)}\n"
        )
        return self._invoke(
            request_payload=request_payload,
            prompt=prompt,
            response_type=LeanDraft,
            schema=_lean_draft_schema(),
        )

    def _invoke(
        self,
        request_payload: dict[str, Any],
        prompt: str,
        response_type: type[ParsedOutput],
        schema: dict[str, Any],
    ) -> tuple[ParsedOutput, AgentTurn]:
        with tempfile.TemporaryDirectory(prefix="codex_formalization_") as temp_dir:
            temp_root = Path(temp_dir)
            schema_path = temp_root / "schema.json"
            output_path = temp_root / "response.json"
            schema_path.write_text(json.dumps(schema, indent=2, sort_keys=True), encoding="utf-8")

            command = [
                self.executable,
                "exec",
                "--ephemeral",
                "--skip-git-repo-check",
                "-C",
                str(self.repo_root),
                "-s",
                "read-only",
                "--output-schema",
                str(schema_path),
                "-o",
                str(output_path),
            ]
            if self.model:
                command.extend(["-m", self.model])

            try:
                response = subprocess.run(
                    command,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "The `codex` CLI is not available. Install it before running the Codex backend."
                ) from exc

            if response.returncode != 0:
                stderr = response.stderr.strip()
                stdout = response.stdout.strip()
                details = "\n".join(part for part in [stderr, stdout] if part)
                raise RuntimeError(
                    f"Codex exec failed during {request_payload['stage']}."
                    + (f"\n{details}" if details else "")
                )

            if not output_path.exists():
                raise ValueError(
                    f"Codex exec did not write a structured response for {request_payload['stage']}."
                )

            raw_response = output_path.read_text(encoding="utf-8").strip()
            try:
                parsed_payload = json.loads(raw_response)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Codex exec returned invalid JSON for {request_payload['stage']}."
                ) from exc

        return response_type(**parsed_payload), AgentTurn(
            request_payload=request_payload,
            prompt=prompt,
            raw_response=raw_response,
        )


def _base_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "$schema": _SCHEMA_URL,
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _theorem_extraction_schema() -> dict[str, Any]:
    return _base_schema(
        properties={
            "title": {"type": "string"},
            "informal_statement": {"type": "string"},
            "definitions": _STRING_ARRAY,
            "lemmas": _STRING_ARRAY,
            "propositions": _STRING_ARRAY,
            "dependencies": _STRING_ARRAY,
            "notes": _STRING_ARRAY,
        },
        required=[
            "title",
            "informal_statement",
            "definitions",
            "lemmas",
            "propositions",
            "dependencies",
            "notes",
        ],
    )


def _enrichment_report_schema() -> dict[str, Any]:
    return _base_schema(
        properties={
            "self_contained": {"type": "boolean"},
            "satisfied_prerequisites": _STRING_ARRAY,
            "missing_prerequisites": _STRING_ARRAY,
            "required_plan_additions": _STRING_ARRAY,
            "recommended_scope": {"type": "string"},
            "difficulty_assessment": {"type": "string"},
            "open_questions": _STRING_ARRAY,
            "next_steps": _STRING_ARRAY,
            "human_handoff": {"type": "string"},
        },
        required=[
            "self_contained",
            "satisfied_prerequisites",
            "missing_prerequisites",
            "required_plan_additions",
            "recommended_scope",
            "difficulty_assessment",
            "open_questions",
            "next_steps",
            "human_handoff",
        ],
    )


def _formalization_plan_schema() -> dict[str, Any]:
    return _base_schema(
        properties={
            "title": {"type": "string"},
            "informal_statement": {"type": "string"},
            "assumptions": _STRING_ARRAY,
            "conclusion": {"type": "string"},
            "symbols": _STRING_ARRAY,
            "ambiguities": _STRING_ARRAY,
            "paraphrase": {"type": "string"},
            "theorem_name": {"type": "string"},
            "imports": _STRING_ARRAY,
            "prerequisites_to_formalize": _STRING_ARRAY,
            "helper_definitions": _STRING_ARRAY,
            "target_statement": {"type": "string"},
            "proof_sketch": _STRING_ARRAY,
            "human_summary": {"type": "string"},
        },
        required=[
            "title",
            "informal_statement",
            "assumptions",
            "conclusion",
            "symbols",
            "ambiguities",
            "paraphrase",
            "theorem_name",
            "imports",
            "prerequisites_to_formalize",
            "helper_definitions",
            "target_statement",
            "proof_sketch",
            "human_summary",
        ],
    )


def _lean_draft_schema() -> dict[str, Any]:
    return _base_schema(
        properties={
            "theorem_name": {"type": "string"},
            "module_name": {"type": "string"},
            "imports": _STRING_ARRAY,
            "content": {"type": "string"},
            "rationale": {"type": "string"},
        },
        required=[
            "theorem_name",
            "module_name",
            "imports",
            "content",
            "rationale",
        ],
    )
