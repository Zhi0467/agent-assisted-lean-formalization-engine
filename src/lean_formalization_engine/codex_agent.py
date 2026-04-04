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
    FormalizationPlan,
    LeanDraft,
    RepairContext,
    SourceRef,
    TheoremSpec,
)

ParsedOutput = TypeVar("ParsedOutput", TheoremSpec, FormalizationPlan, LeanDraft)

_SCHEMA_URL = "https://json-schema.org/draft/2020-12/schema"
_STRING_ARRAY = {"type": "array", "items": {"type": "string"}}


class CodexCliFormalizationAgent:
    """Use `codex exec` as a live theorem-spec, plan, and Lean-draft backend."""

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

    def draft_theorem_spec(
        self,
        source_ref: SourceRef,
        normalized_text: str,
    ) -> tuple[TheoremSpec, AgentTurn]:
        request_payload = {
            "stage": "draft_theorem_spec",
            "model": self.model,
            "source_ref": asdict(source_ref),
            "normalized_text": normalized_text,
        }
        prompt = (
            "You are the theorem-spec turn for a Lean 4 formalization workflow.\n"
            "Return JSON only. Stay faithful to the source theorem and call out real ambiguities.\n\n"
            f"Source reference:\n{json.dumps(request_payload['source_ref'], indent=2, sort_keys=True)}\n\n"
            f"Normalized theorem source:\n{normalized_text.strip()}\n"
        )
        return self._invoke(
            request_payload=request_payload,
            prompt=prompt,
            response_type=TheoremSpec,
            schema=_theorem_spec_schema(),
        )

    def draft_formalization_plan(
        self,
        theorem_spec: TheoremSpec,
        context_pack: ContextPack,
    ) -> tuple[FormalizationPlan, AgentTurn]:
        request_payload = {
            "stage": "draft_formalization_plan",
            "model": self.model,
            "theorem_spec": asdict(theorem_spec),
            "context_pack": asdict(context_pack),
        }
        prompt = (
            "You are the formalization-plan turn for a Lean 4 workflow.\n"
            "Return JSON only. Produce the Lean-facing theorem target and a concise proof plan.\n"
            "Prefer the simplest imports that fit the local workspace, and keep helper definitions "
            "empty unless they are genuinely needed.\n\n"
            f"Approved theorem spec:\n{json.dumps(request_payload['theorem_spec'], indent=2, sort_keys=True)}\n\n"
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
            "You are the Lean-draft turn in a bounded compile-repair loop.\n"
            "Return JSON only. Produce Lean 4 code for "
            "`FormalizationEngineWorkspace/Generated.lean`.\n"
            "The `content` field must contain the full file contents, including imports.\n"
            "Do not use `sorry`. If there is prior compiler feedback, fix that exact failure first.\n\n"
            f"Approved formalization plan:\n{json.dumps(request_payload['plan'], indent=2, sort_keys=True)}\n\n"
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

            response = subprocess.run(
                command,
                input=prompt,
                capture_output=True,
                text=True,
                check=False,
            )
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


def _theorem_spec_schema() -> dict[str, Any]:
    return _base_schema(
        properties={
            "title": {"type": "string"},
            "informal_statement": {"type": "string"},
            "assumptions": _STRING_ARRAY,
            "conclusion": {"type": "string"},
            "symbols": _STRING_ARRAY,
            "ambiguities": _STRING_ARRAY,
            "paraphrase": {"type": "string"},
        },
        required=[
            "title",
            "informal_statement",
            "assumptions",
            "conclusion",
            "symbols",
            "ambiguities",
            "paraphrase",
        ],
    )


def _formalization_plan_schema() -> dict[str, Any]:
    return _base_schema(
        properties={
            "theorem_name": {"type": "string"},
            "imports": _STRING_ARRAY,
            "helper_definitions": _STRING_ARRAY,
            "target_statement": {"type": "string"},
            "proof_sketch": _STRING_ARRAY,
        },
        required=[
            "theorem_name",
            "imports",
            "helper_definitions",
            "target_statement",
            "proof_sketch",
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
