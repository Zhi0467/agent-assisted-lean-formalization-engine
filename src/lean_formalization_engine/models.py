from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class SourceKind(str, Enum):
    MARKDOWN = "markdown"
    LATEX = "latex"
    PDF = "pdf"


class RunStage(str, Enum):
    CREATED = "created"
    INGESTED = "ingested"
    SPEC_DRAFTED = "spec_drafted"
    WAITING_FOR_SPEC_APPROVAL = "waiting_for_spec_approval"
    SPEC_APPROVED = "spec_approved"
    PLAN_DRAFTED = "plan_drafted"
    WAITING_FOR_PLAN_APPROVAL = "waiting_for_plan_approval"
    PLAN_APPROVED = "plan_approved"
    DRAFT_GENERATED = "draft_generated"
    COMPILE_PASSED = "compile_passed"
    COMPILE_FAILED = "compile_failed"
    WAITING_FOR_FINAL_APPROVAL = "waiting_for_final_approval"
    COMPLETED = "completed"


class RunStatus(str, Enum):
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    FAILED = "failed"
    COMPLETED = "completed"


@dataclass
class SourceRef:
    path: str
    kind: SourceKind
    label: str


@dataclass
class IngestedSource:
    raw_text: str
    normalized_text: str
    provenance: Dict[str, Any]


@dataclass
class TheoremSpec:
    title: str
    informal_statement: str
    assumptions: List[str]
    conclusion: str
    symbols: List[str]
    ambiguities: List[str]


@dataclass
class FormalizationPlan:
    theorem_name: str
    imports: List[str]
    helper_definitions: List[str]
    proof_strategy: List[str]
    target_statement: str


@dataclass
class LeanDraft:
    theorem_name: str
    code: str
    rationale: List[str]


@dataclass
class CompileAttempt:
    attempt: int
    command: List[str]
    returncode: int
    passed: bool
    stdout: str
    stderr: str
    diagnostics: List[str]
    missing_toolchain: bool = False
    quality_gate_passed: bool = False


@dataclass
class AgentTurn:
    prompt: str
    request_payload: Dict[str, Any]
    raw_response: str
    parsed_output: Any


@dataclass
class RunManifest:
    run_id: str
    source: SourceRef
    current_stage: RunStage
    status: RunStatus
    created_at: str
    updated_at: str
    attempt_count: int = 0
    notes: List[str] = field(default_factory=list)
    final_output_path: Optional[str] = None


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {key: to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    return value
