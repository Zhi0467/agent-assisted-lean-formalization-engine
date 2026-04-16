from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return to_jsonable(asdict(value))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): to_jsonable(inner) for key, inner in value.items()}
    if isinstance(value, list):
        return [to_jsonable(inner) for inner in value]
    return value


class SourceKind(str, Enum):
    MARKDOWN = "markdown"
    LATEX = "latex"
    PDF = "pdf"
    TEXT = "text"


class RunStage(str, Enum):
    CREATED = "created"
    AWAITING_ENRICHMENT_APPROVAL = "awaiting_enrichment_approval"
    AWAITING_PLAN_APPROVAL = "awaiting_plan_approval"
    PROVING = "proving"
    PROOF_BLOCKED = "proof_blocked"
    AWAITING_FINAL_APPROVAL = "awaiting_final_approval"
    COMPLETED = "completed"
    FAILED = "failed"


DEFAULT_WORKFLOW_VERSION = "0.3.0"
DEFAULT_WORKFLOW_TAGS = [
    "three-checkpoint",
    "review-files",
    "terry-cli",
    "bounded-prove-loop",
]


@dataclass
class SourceRef:
    path: str
    kind: SourceKind


@dataclass
class IngestedSource:
    raw_text: str
    normalized_text: str
    extraction_method: str


@dataclass
class TheoremExtraction:
    title: str
    informal_statement: str
    definitions: list[str]
    lemmas: list[str]
    propositions: list[str]
    dependencies: list[str]
    notes: list[str]


@dataclass
class EnrichmentReport:
    self_contained: bool
    satisfied_prerequisites: list[str]
    missing_prerequisites: list[str]
    required_plan_additions: list[str]
    recommended_scope: str
    difficulty_assessment: str
    open_questions: list[str]
    next_steps: list[str]
    human_handoff: str


@dataclass
class ContextPack:
    recommended_imports: list[str]
    local_examples: list[str]
    notes: list[str]


@dataclass
class FormalizationPlan:
    title: str
    informal_statement: str
    assumptions: list[str]
    conclusion: str
    symbols: list[str]
    ambiguities: list[str]
    paraphrase: str
    theorem_name: str
    imports: list[str]
    prerequisites_to_formalize: list[str]
    helper_definitions: list[str]
    target_statement: str
    proof_sketch: list[str]
    human_summary: str


@dataclass
class LeanDraft:
    theorem_name: str
    module_name: str
    imports: list[str]
    content: str
    rationale: str


@dataclass
class AgentTurn:
    request_payload: dict[str, object]
    prompt: str
    raw_response: str


@dataclass
class CompileAttempt:
    attempt: int
    command: list[str]
    stdout: str
    stderr: str
    returncode: int
    diagnostics: list[str]
    fast_check_passed: bool
    build_passed: bool
    contains_sorry: bool
    missing_toolchain: bool
    quality_gate_passed: bool
    passed: bool
    status: str


@dataclass
class RepairContext:
    current_attempt: int
    max_attempts: int
    prior_attempts: int
    attempts_remaining: int
    previous_draft: LeanDraft | None
    previous_result: CompileAttempt | None
    human_feedback: str | None = None


@dataclass
class ReviewDecision:
    decision: str
    updated_at: str
    notes: str = ""


@dataclass
class AgentConfig:
    backend: str
    command: list[str] | None = None
    codex_model: str | None = None


@dataclass
class RunManifest:
    run_id: str
    source: SourceRef
    agent_name: str
    agent_config: AgentConfig
    template_dir: str
    created_at: str
    updated_at: str
    current_stage: RunStage
    workflow_version: str = DEFAULT_WORKFLOW_VERSION
    workflow_tags: list[str] = field(default_factory=lambda: list(DEFAULT_WORKFLOW_TAGS))
    attempt_count: int = 0
    latest_error: str | None = None
    final_output_path: str | None = None
