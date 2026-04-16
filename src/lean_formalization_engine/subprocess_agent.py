from __future__ import annotations

import json
import re
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

_LEGACY_IDENTIFIER_PATTERN = r"(?:[^\W\d]|_)\w*'*"
_LEGACY_QUALIFIED_TYPE_PATTERN = rf"{_LEGACY_IDENTIFIER_PATTERN}(?:\.{_LEGACY_IDENTIFIER_PATTERN})*"


class ProviderResponseError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        response_text: str = "",
        provider_payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.response_text = response_text
        self.provider_payload = provider_payload


class SubprocessFormalizationAgent:
    """Delegate each Terry turn to an external command over stdin/stdout."""

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

    def draft_formalization_plan(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        enrichment: EnrichmentReport,
        context_pack: ContextPack,
    ) -> tuple[FormalizationPlan, AgentTurn]:
        theorem_spec = self._draft_legacy_theorem_spec(
            source_ref,
            source_text,
            extraction,
            enrichment,
        )
        return self._invoke(
            stage="draft_formalization_plan",
            payload={
                "source_ref": asdict(source_ref),
                "source_text": source_text,
                "extraction": asdict(extraction),
                "theorem_spec": (
                    asdict(theorem_spec)
                    if theorem_spec is not None
                    else _legacy_theorem_spec_payload(extraction)
                ),
                "enrichment": asdict(enrichment),
                "context_pack": asdict(context_pack),
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
        request_payload = {"stage": stage, **payload}
        try:
            response = subprocess.run(
                self.command,
                cwd=self.working_directory,
                input=json.dumps(request_payload),
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Provider command `{self.command[0]}` is not available for `{stage}`."
            ) from exc

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
            raise ProviderResponseError(
                f"Provider returned invalid JSON during {stage}.",
                response_text=response.stdout.strip(),
            ) from exc

        parsed_output_payload = provider_payload.get("parsed_output")
        if not isinstance(parsed_output_payload, dict):
            raise ProviderResponseError(
                f"Provider omitted `parsed_output` for {stage}.",
                provider_payload=provider_payload,
            )

        try:
            parsed_output = _parse_provider_output(
                response_type=response_type,
                parsed_output_payload=parsed_output_payload,
                request_payload=request_payload,
            )
        except TypeError as exc:
            raise ProviderResponseError(
                f"Provider returned invalid `parsed_output` for {stage}.",
                provider_payload=provider_payload,
            ) from exc
        raw_response = provider_payload.get("raw_response")
        if not isinstance(raw_response, str):
            raw_response = json.dumps(parsed_output_payload, indent=2, sort_keys=True)
        prompt = provider_payload.get("prompt")
        if not isinstance(prompt, str):
            raise ProviderResponseError(
                f"Provider omitted `prompt` for {stage}.",
                provider_payload=provider_payload,
            )

        return parsed_output, AgentTurn(
            request_payload=request_payload,
            prompt=prompt,
            raw_response=raw_response,
        )

    def _draft_legacy_theorem_spec(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        enrichment: EnrichmentReport,
    ) -> TheoremSpec | None:
        try:
            theorem_spec, _ = self._invoke(
                stage="draft_theorem_spec",
                payload={
                    "source_ref": asdict(source_ref),
                    "source_text": source_text,
                    "extraction": asdict(extraction),
                    "enrichment": asdict(enrichment),
                },
                response_type=TheoremSpec,
            )
        except RuntimeError as exc:
            if _looks_like_unsupported_optional_stage(str(exc)):
                return None
            raise
        except ProviderResponseError as exc:
            if _looks_like_unsupported_optional_stage(exc.response_text, exc.provider_payload):
                return None
            raise
        return theorem_spec


def _default_agent_name(command: list[str]) -> str:
    executable_name = Path(command[0]).name
    if executable_name.startswith("python") and len(command) > 1:
        if command[1] == "-m" and len(command) > 2:
            return f"subprocess:{command[2]}"
        if command[1] == "-c":
            return "subprocess:python-inline"
        return f"subprocess:{Path(command[1]).name}"
    return f"subprocess:{executable_name}"


def _parse_provider_output(
    *,
    response_type: type[ParsedOutput],
    parsed_output_payload: dict[str, Any],
    request_payload: dict[str, Any],
) -> ParsedOutput:
    if response_type is not FormalizationPlan:
        return response_type(**parsed_output_payload)

    try:
        return response_type(**parsed_output_payload)
    except TypeError:
        if "theorem_name" not in parsed_output_payload or "target_statement" not in parsed_output_payload:
            raise
        return _legacy_formalization_plan_payload(parsed_output_payload, request_payload)  # type: ignore[return-value]


def _legacy_formalization_plan_payload(
    parsed_output_payload: dict[str, Any],
    request_payload: dict[str, Any],
) -> FormalizationPlan:
    theorem_spec = request_payload.get("theorem_spec")
    extraction = request_payload.get("extraction")
    if not isinstance(theorem_spec, dict):
        theorem_spec = {}
    if not isinstance(extraction, dict):
        extraction = {}

    title = theorem_spec.get("title") or extraction.get("title") or parsed_output_payload.get("theorem_name", "Legacy theorem")
    informal_statement = (
        theorem_spec.get("informal_statement")
        or extraction.get("informal_statement")
        or title
    )
    assumptions = theorem_spec.get("assumptions", [])
    conclusion = theorem_spec.get("conclusion", "")
    return FormalizationPlan(
        title=title,
        informal_statement=informal_statement,
        assumptions=assumptions if isinstance(assumptions, list) else [],
        conclusion=conclusion if isinstance(conclusion, str) else "",
        symbols=theorem_spec.get("symbols", []) if isinstance(theorem_spec.get("symbols", []), list) else [],
        ambiguities=(
            theorem_spec.get("ambiguities", [])
            if isinstance(theorem_spec.get("ambiguities", []), list)
            else []
        ),
        paraphrase=theorem_spec.get("paraphrase") or informal_statement,
        theorem_name=parsed_output_payload["theorem_name"],
        imports=parsed_output_payload.get("imports", []),
        prerequisites_to_formalize=parsed_output_payload.get("prerequisites_to_formalize", []),
        helper_definitions=parsed_output_payload.get("helper_definitions", []),
        target_statement=parsed_output_payload.get("target_statement", ""),
        proof_sketch=parsed_output_payload.get("proof_sketch", []),
        human_summary=(
            f"Imported legacy provider plan for `{parsed_output_payload['theorem_name']}`. "
            f"Assumptions: {', '.join(assumptions) if assumptions else 'none'}. "
            f"Conclusion: {conclusion or 'unspecified'}."
        ),
    )


def _looks_like_unsupported_optional_stage(
    error_text: str,
    provider_payload: dict[str, Any] | None = None,
) -> bool:
    fragments = [error_text]
    if provider_payload is not None:
        fragments.append(json.dumps(provider_payload, sort_keys=True))
    haystack = "\n".join(fragment for fragment in fragments if fragment).lower()
    if "draft_theorem_spec" not in haystack:
        return False
    return any(
        marker in haystack
        for marker in ("unsupported stage", "unknown stage", "not implemented")
    )


def _legacy_theorem_spec_payload(extraction: TheoremExtraction) -> dict[str, object]:
    assumptions, conclusion = _infer_assumptions_and_conclusion(extraction.informal_statement)
    return {
        "title": extraction.title,
        "informal_statement": extraction.informal_statement,
        "assumptions": assumptions,
        "conclusion": conclusion,
        "symbols": _infer_symbols(extraction, assumptions, conclusion),
        "ambiguities": [],
        "paraphrase": extraction.informal_statement,
    }


def _infer_assumptions_and_conclusion(statement: str) -> tuple[list[str], str]:
    stripped = statement.strip().rstrip(".")
    target_statement = _extract_target_statement(stripped)
    primary_statement = _strip_target_statement_lines(stripped)
    lowered = primary_statement.lower()
    for prefix in ("for every ", "for each ", "for any ", "for all ", "given "):
        if not lowered.startswith(prefix):
            continue
        remainder = primary_statement[len(prefix) :]
        subject, conclusion = _split_subject_and_conclusion(remainder)
        if subject is None or conclusion is None:
            break
        assumptions = _subject_to_assumptions(subject.strip())
        if assumptions is not None:
            return assumptions, target_statement or conclusion.strip()
        break
    return [], target_statement or stripped


def _extract_target_statement(statement: str) -> str | None:
    for line in statement.splitlines():
        match = re.match(r"target statement\s*:\s*(.+)", line.strip(), flags=re.IGNORECASE)
        if match is None:
            continue
        return match.group(1).strip().strip("`").rstrip(".")
    return None


def _strip_target_statement_lines(statement: str) -> str:
    lines = [
        line
        for line in statement.splitlines()
        if not re.match(r"target statement\s*:", line.strip(), flags=re.IGNORECASE)
    ]
    cleaned = "\n".join(line for line in lines if line.strip()).strip()
    return cleaned or statement


def _subject_to_assumptions(subject: str) -> list[str] | None:
    cleaned = subject.replace("`", "").strip()
    if not cleaned:
        return None
    assumptions = _comma_separated_typed_assumptions(cleaned)
    if assumptions is not None:
        return assumptions
    return _single_subject_to_assumptions(cleaned)


def _single_subject_to_assumptions(subject: str) -> list[str] | None:
    cleaned = subject.replace("`", "").strip()
    if not cleaned:
        return None

    typed_match = re.fullmatch(
        rf"\(?\s*(.+?)\s*:\s*({_LEGACY_QUALIFIED_TYPE_PATTERN})\s*\)?",
        cleaned,
    )
    if typed_match is not None:
        variables_raw, type_name = typed_match.groups()
        assumptions = _descriptor_subject_to_assumptions(variables_raw, explicit_type=type_name)
        if assumptions is not None:
            return assumptions
        if _contains_descriptor_prefix(variables_raw):
            return None
        variables = _split_variable_names(variables_raw)
        if variables:
            return [f"{variable} : {type_name}" for variable in variables]

    assumptions = _descriptor_subject_to_assumptions(cleaned)
    if assumptions is not None:
        return assumptions
    return None


def _comma_separated_typed_assumptions(subject: str) -> list[str] | None:
    segments = [segment.strip() for segment in subject.split(",")]
    if len(segments) < 2 or any(":" not in segment for segment in segments):
        return None
    assumptions: list[str] = []
    for segment in segments:
        segment_assumptions = _single_subject_to_assumptions(segment)
        if segment_assumptions is None:
            return None
        assumptions.extend(segment_assumptions)
    return assumptions


def _split_variable_names(raw_variables: str) -> list[str]:
    variables = [
        variable
        for variable in re.split(r"\s*(?:,|\band\b)\s*|\s+", raw_variables.strip())
        if variable
    ]
    if not variables or any(re.fullmatch(_LEGACY_IDENTIFIER_PATTERN, variable) is None for variable in variables):
        return []
    return variables


def _contains_descriptor_prefix(raw_subject: str) -> bool:
    tokens = raw_subject.split()
    return any(_descriptor_type(" ".join(tokens[:split_index]).lower().strip()) is not None for split_index in range(1, len(tokens)))


def _descriptor_subject_to_assumptions(
    raw_subject: str,
    *,
    explicit_type: str | None = None,
) -> list[str] | None:
    tokens = raw_subject.split()
    for split_index in range(1, len(tokens)):
        descriptor = " ".join(tokens[:split_index]).lower().strip()
        descriptor_type = _descriptor_type(descriptor)
        if descriptor_type is None:
            continue
        if explicit_type is not None and explicit_type != descriptor_type:
            return None
        variables = _split_variable_names(" ".join(tokens[split_index:]))
        if variables:
            return [f"{variable} : {explicit_type or descriptor_type}" for variable in variables]
    return None


def _descriptor_type(descriptor: str) -> str | None:
    if descriptor.endswith("natural number") or descriptor.endswith("natural numbers"):
        return "Nat"
    if descriptor.endswith("integer") or descriptor.endswith("integers"):
        return "Int"
    if descriptor.endswith("real number") or descriptor.endswith("real numbers"):
        return "Real"
    if descriptor.endswith("boolean") or descriptor.endswith("booleans"):
        return "Bool"
    if descriptor.endswith("proposition") or descriptor.endswith("propositions"):
        return "Prop"
    return None


def _split_subject_and_conclusion(remainder: str) -> tuple[str | None, str | None]:
    comma_split = _split_comma_subject_and_conclusion(remainder)
    if comma_split is not None:
        return comma_split

    typed_separator = re.fullmatch(
        r"(\(?\s*.+?\s*:\s*[A-Za-z_][\w.]*\s*\)?)\s*:\s*(.+)",
        remainder,
    )
    if typed_separator is not None:
        return typed_separator.group(1), typed_separator.group(2)

    if ":" in remainder:
        subject, conclusion = remainder.split(":", 1)
        return subject, conclusion

    return None, None


def _split_comma_subject_and_conclusion(remainder: str) -> tuple[str, str] | None:
    best_split: tuple[str, str] | None = None
    for match in re.finditer(",", remainder):
        subject = remainder[: match.start()]
        conclusion = remainder[match.end() :]
        if _subject_to_assumptions(subject.strip()) is None:
            continue
        best_split = (subject, conclusion)
    return best_split


def _infer_symbols(
    extraction: TheoremExtraction,
    assumptions: list[str],
    conclusion: str,
) -> list[str]:
    symbols: list[str] = []
    supporting_text = " ".join(
        [
            extraction.informal_statement,
            conclusion,
            *assumptions,
            *extraction.definitions,
            *extraction.lemmas,
            *extraction.dependencies,
        ]
    )
    if "Nat" in supporting_text or "natural number" in extraction.informal_statement.lower():
        symbols.append("Nat")
    for token in ("0", "1", "+", "-", "*", "/", "="):
        if token in supporting_text and token not in symbols:
            symbols.append(token)
    return symbols
