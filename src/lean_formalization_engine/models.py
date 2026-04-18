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
    LEGACY_AWAITING_ENRICHMENT_REVIEW = "awaiting_enrichment_review"
    LEGACY_AWAITING_SPEC_REVIEW = "awaiting_spec_review"
    LEGACY_AWAITING_PLAN_REVIEW = "awaiting_plan_review"
    LEGACY_REPAIRING = "repairing"
    LEGACY_AWAITING_STALL_REVIEW = "awaiting_stall_review"
    LEGACY_AWAITING_FINAL_REVIEW = "awaiting_final_review"
    COMPLETED = "completed"
    FAILED = "failed"


class BackendStage(str, Enum):
    ENRICHMENT = "enrichment"
    PLAN = "plan"
    PROOF = "proof"
    REVIEW = "review"


DEFAULT_WORKFLOW_VERSION = "0.5.0"
DEFAULT_WORKFLOW_TAGS = [
    "three-checkpoint",
    "review-files",
    "terry-cli",
    "bounded-prove-loop",
    "backend-owned-stage-files",
    "proof-gated-plan",
    "attempt-review",
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
class StageRequest:
    stage: BackendStage
    run_id: str
    repo_root: str
    run_dir: str
    output_dir: str
    input_paths: dict[str, str]
    required_outputs: list[str]
    review_notes_path: str | None = None
    latest_compile_result_path: str | None = None
    previous_attempt_dir: str | None = None
    attempt: int | None = None
    max_attempts: int | None = None


@dataclass
class AgentTurn:
    request_payload: dict[str, object]
    prompt: str
    raw_response: str


@dataclass
class NaturalLanguageProofStatus:
    obtained: bool
    source: str
    notes: str = ""


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
    lake_path: str | None = None
    workflow_version: str = DEFAULT_WORKFLOW_VERSION
    workflow_tags: list[str] = field(default_factory=lambda: list(DEFAULT_WORKFLOW_TAGS))
    attempt_count: int = 0
    latest_error: str | None = None
    final_output_path: str | None = None
