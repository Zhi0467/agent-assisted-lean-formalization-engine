from __future__ import annotations

import json
import subprocess
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
    TheoremSpec,
)

ParsedOutput = TypeVar(
    "ParsedOutput",
    TheoremExtraction,
    EnrichmentReport,
    TheoremSpec,
    FormalizationPlan,
    LeanDraft,
)


class SubprocessFormalizationAgent:
    """Delegate each agent turn to an external command over stdin/stdout."""

    def __init__(
        self,
        command: list[str],
        name: str | None = None,
        working_directory: Path | None = None,
    ):
        if not command:
            raise ValueError("SubprocessFormalizationAgent requires a non-empty command.")
        self.command = command
        self.name = name or _default_agent_name(command)
        self.working_directory = working_directory

    def draft_theorem_extraction(
        self,
        source_ref: SourceRef,
        source_text: str,
        normalized_text: str,
    ) -> tuple[TheoremExtraction, AgentTurn]:
        return self._invoke(
            stage="draft_theorem_extraction",
            payload={
                "source_ref": asdict(source_ref),
                "source_text": source_text,
                "normalized_text": normalized_text,
            },
            response_type=TheoremExtraction,
        )

    def draft_theorem_enrichment(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        extraction_markdown: str,
    ) -> tuple[EnrichmentReport, AgentTurn]:
        return self._invoke(
            stage="draft_theorem_enrichment",
            payload={
                "source_ref": asdict(source_ref),
                "source_text": source_text,
                "extraction": asdict(extraction),
                "extraction_markdown": extraction_markdown,
            },
            response_type=EnrichmentReport,
        )

    def draft_theorem_spec(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        enrichment: EnrichmentReport,
    ) -> tuple[TheoremSpec, AgentTurn]:
        return self._invoke(
            stage="draft_theorem_spec",
            payload={
                "source_ref": asdict(source_ref),
                "source_text": source_text,
                "extraction": asdict(extraction),
                "enrichment": asdict(enrichment),
            },
            response_type=TheoremSpec,
        )

    def draft_formalization_plan(
        self,
        theorem_spec: TheoremSpec,
        context_pack: ContextPack,
        enrichment: EnrichmentReport,
    ) -> tuple[FormalizationPlan, AgentTurn]:
        return self._invoke(
            stage="draft_formalization_plan",
            payload={
                "theorem_spec": asdict(theorem_spec),
                "context_pack": asdict(context_pack),
                "enrichment": asdict(enrichment),
            },
            response_type=FormalizationPlan,
        )

    def draft_lean_file(
        self,
        plan: FormalizationPlan,
        repair_context: RepairContext,
    ) -> tuple[LeanDraft, AgentTurn]:
        return self._invoke(
            stage="draft_lean_file",
            payload={
                "plan": asdict(plan),
                "repair_context": asdict(repair_context),
            },
            response_type=LeanDraft,
        )

    def _invoke(
        self,
        stage: str,
        payload: dict[str, Any],
        response_type: type[ParsedOutput],
    ) -> tuple[ParsedOutput, AgentTurn]:
        request_payload = {
            "stage": stage,
            **payload,
        }
        response = subprocess.run(
            self.command,
            cwd=self.working_directory,
            input=json.dumps(request_payload),
            capture_output=True,
            text=True,
            check=False,
        )
        if response.returncode != 0:
            stderr = response.stderr.strip()
            stdout = response.stdout.strip()
            details = "\n".join(part for part in [stderr, stdout] if part)
            raise RuntimeError(
                f"Provider command exited with code {response.returncode} during {stage}."
                + (f"\n{details}" if details else "")
            )

        try:
            provider_payload = json.loads(response.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Provider returned invalid JSON during {stage}.") from exc

        parsed_output_payload = provider_payload.get("parsed_output")
        if not isinstance(parsed_output_payload, dict):
            raise ValueError(f"Provider omitted `parsed_output` for {stage}.")

        parsed_output = response_type(**parsed_output_payload)
        raw_response = provider_payload.get("raw_response")
        if not isinstance(raw_response, str):
            raw_response = json.dumps(parsed_output_payload, indent=2, sort_keys=True)
        prompt = provider_payload.get("prompt")
        if not isinstance(prompt, str):
            raise ValueError(f"Provider omitted `prompt` for {stage}.")

        return parsed_output, AgentTurn(
            request_payload=request_payload,
            prompt=prompt,
            raw_response=raw_response,
        )


def _default_agent_name(command: list[str]) -> str:
    executable_name = Path(command[0]).name
    if executable_name.startswith("python") and len(command) > 1:
        if command[1] == "-m" and len(command) > 2:
            return f"subprocess:{command[2]}"
        if command[1] == "-c":
            return "subprocess:python-inline"
        return f"subprocess:{Path(command[1]).name}"
    return f"subprocess:{executable_name}"
