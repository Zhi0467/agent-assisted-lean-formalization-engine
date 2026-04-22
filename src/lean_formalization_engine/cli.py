from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

from .cli_exec_agent import SUPPORTED_CLI_BACKENDS, CliExecFormalizationAgent
from .lean_runner import LeanRunner
from .models import AgentConfig, ReviewDecision, RunManifest, RunStage, to_jsonable, utc_now
from .storage import RunStore, validate_run_id
from .subprocess_agent import SubprocessFormalizationAgent
from .template_manager import discover_workspace_template
from .workflow import FormalizationWorkflow

_DEFAULT_BACKEND = "codex"
_AGENT_BACKEND_CHOICES = ["command", *sorted(SUPPORTED_CLI_BACKENDS)]

_STATUS_SURFACE_CANDIDATES = {
    RunStage.AWAITING_ENRICHMENT_APPROVAL: [
        ("01_enrichment/checkpoint.md", "01_enrichment/review.md"),
    ],
    RunStage.LEGACY_AWAITING_ENRICHMENT_REVIEW: [
        ("03_enrichment/checkpoint.md", "03_enrichment/review.md"),
        ("03_enrichment/handoff.md", "03_enrichment/decision.json"),
    ],
    RunStage.AWAITING_PLAN_APPROVAL: [
        ("02_plan/checkpoint.md", "02_plan/review.md"),
    ],
    RunStage.LEGACY_AWAITING_SPEC_REVIEW: [
        ("04_spec/checkpoint.md", "04_spec/review.md"),
        ("04_spec/theorem_spec.json", "04_spec/decision.json"),
    ],
    RunStage.LEGACY_AWAITING_PLAN_REVIEW: [
        ("06_plan/checkpoint.md", "06_plan/review.md"),
        ("06_plan/formalization_plan.json", "06_plan/decision.json"),
    ],
    RunStage.PROOF_BLOCKED: [
        ("03_proof/checkpoint.md", "03_proof/review.md"),
    ],
    RunStage.LEGACY_AWAITING_STALL_REVIEW: [
        ("09_review/checkpoint.md", "09_review/review.md"),
        ("09_review/stall_report.md", "09_review/decision.json"),
    ],
    RunStage.AWAITING_FINAL_APPROVAL: [
        ("04_final/checkpoint.md", "04_final/review.md"),
    ],
    RunStage.LEGACY_AWAITING_FINAL_REVIEW: [
        ("10_final/checkpoint.md", "10_final/review.md"),
        ("10_final/final_report.md", "10_final/decision.json"),
    ],
}

_TURN_COUNT_LABELS = {
    RunStage.AWAITING_ENRICHMENT_APPROVAL: ("enrichment", "Enrichment turns"),
    RunStage.LEGACY_AWAITING_ENRICHMENT_REVIEW: ("enrichment", "Enrichment turns"),
    RunStage.AWAITING_PLAN_APPROVAL: ("plan", "Plan turns"),
    RunStage.LEGACY_AWAITING_SPEC_REVIEW: ("plan", "Plan turns"),
    RunStage.LEGACY_AWAITING_PLAN_REVIEW: ("plan", "Plan turns"),
}

_PROOF_ATTEMPT_SUMMARY_STAGES = {
    RunStage.PROVING,
    RunStage.PROOF_BLOCKED,
    RunStage.AWAITING_FINAL_APPROVAL,
    RunStage.LEGACY_REPAIRING,
    RunStage.LEGACY_AWAITING_STALL_REVIEW,
    RunStage.LEGACY_AWAITING_FINAL_REVIEW,
    RunStage.COMPLETED,
}

_LEGACY_STAGE_BY_CURRENT = {
    RunStage.CREATED: RunStage.CREATED.value,
    RunStage.AWAITING_ENRICHMENT_APPROVAL: RunStage.LEGACY_AWAITING_ENRICHMENT_REVIEW.value,
    RunStage.AWAITING_PLAN_APPROVAL: RunStage.LEGACY_AWAITING_SPEC_REVIEW.value,
    RunStage.PROVING: RunStage.LEGACY_REPAIRING.value,
    RunStage.PROOF_BLOCKED: RunStage.LEGACY_AWAITING_STALL_REVIEW.value,
    RunStage.AWAITING_FINAL_APPROVAL: RunStage.LEGACY_AWAITING_FINAL_REVIEW.value,
    RunStage.LEGACY_AWAITING_ENRICHMENT_REVIEW: RunStage.LEGACY_AWAITING_ENRICHMENT_REVIEW.value,
    RunStage.LEGACY_AWAITING_SPEC_REVIEW: RunStage.LEGACY_AWAITING_SPEC_REVIEW.value,
    RunStage.LEGACY_AWAITING_PLAN_REVIEW: RunStage.LEGACY_AWAITING_PLAN_REVIEW.value,
    RunStage.LEGACY_REPAIRING: RunStage.LEGACY_REPAIRING.value,
    RunStage.LEGACY_AWAITING_STALL_REVIEW: RunStage.LEGACY_AWAITING_STALL_REVIEW.value,
    RunStage.LEGACY_AWAITING_FINAL_REVIEW: RunStage.LEGACY_AWAITING_FINAL_REVIEW.value,
    RunStage.COMPLETED: RunStage.COMPLETED.value,
    RunStage.FAILED: RunStage.FAILED.value,
}

_GLOBAL_OPTIONS_WITH_VALUES = (
    "--repo-root",
    "--workdir",
    "--lake-path",
    "--backend-heartbeat-seconds",
)

_DEFAULT_BACKEND_HEARTBEAT_SECONDS = 180.0


class _MissingCommandAgent:
    name = "command-backend-missing-command"

    def _raise(self) -> None:
        raise ValueError(
            "This command-backed Terry run needs a provider command before Terry can continue. "
            "Resume it with `--agent-command \"python3 path/to/provider.py\"`."
        )

    def run_stage(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self._raise()


class _MissingCliBackendAgent:
    def __init__(self, backend: str, executable: str) -> None:
        self.backend = backend
        self.executable = executable
        self.name = f"{backend}-backend-missing-cli"

    def _raise(self) -> None:
        raise ValueError(
            f"The `{self.executable}` CLI is not available. "
            f"Install it before using the {self.backend} backend, "
            "or pass `--agent-backend command --agent-command ...`."
        )

    def run_stage(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        self._raise()


def _cli_backend_executable(backend: str) -> str:
    return {"codex": "codex", "claude": "claude"}[backend]


class _StatusOnlyAgent:
    name = "status-only-agent"

    def run_stage(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("Status-only agent cannot execute Terry backend turns.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=Path(sys.argv[0]).name or "terry",
        description="Human-reviewed Lean formalization workflow with a bounded prove-and-repair loop.",
    )
    parser.add_argument(
        "--repo-root",
        "--workdir",
        type=Path,
        default=Path.cwd(),
        help=(
            "Terry working directory. This repo root owns artifacts/, optional "
            "lean_workspace_template/, and the shared .terry/lean_workspace cache."
        ),
    )
    parser.add_argument(
        "--lake-path",
        help="Optional `lake` executable override for template initialization and compile checks.",
    )
    parser.add_argument(
        "--backend-heartbeat-seconds",
        type=float,
        default=_DEFAULT_BACKEND_HEARTBEAT_SECONDS,
        help=(
            "How many seconds Terry waits before printing another live backend heartbeat "
            f"(default: {_DEFAULT_BACKEND_HEARTBEAT_SECONDS:g})."
        ),
    )
    _add_backend_arguments(parser, suppress_help=True, prefix="legacy_")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prove_parser = subparsers.add_parser("prove", help="Start a new Terry run.")
    _add_prove_arguments(prove_parser)

    formalize_parser = subparsers.add_parser(
        "formalize",
        help="Alias for `prove`.",
    )
    _add_prove_arguments(formalize_parser)

    run_parser = subparsers.add_parser("run", help=argparse.SUPPRESS)
    run_parser.add_argument("--source", required=True, type=Path, help=argparse.SUPPRESS)
    run_parser.add_argument("--run-id", required=True, help=argparse.SUPPRESS)
    run_parser.add_argument("--auto-approve", action="store_true", help=argparse.SUPPRESS)
    run_mode_group = run_parser.add_mutually_exclusive_group()
    run_mode_group.add_argument("--divide-and-conquer", action="store_true", help=argparse.SUPPRESS)
    run_mode_group.add_argument("--yolo", action="store_true", help=argparse.SUPPRESS)
    _add_backend_arguments(run_parser)

    resume_parser = subparsers.add_parser(
        "resume",
        help=(
            "Resume a paused Terry run. Use `--approve` to approve the current "
            "handoff without editing review.md; only edit the review file when "
            "you need to leave notes or reject the handoff."
        ),
    )
    resume_parser.add_argument("run_id", nargs="?")
    resume_parser.add_argument("--run-id", dest="legacy_run_id", help=argparse.SUPPRESS)
    resume_parser.add_argument(
        "--approve",
        action="store_true",
        help=(
            "Approve the current handoff with no reviewer notes. "
            "Equivalent to setting `decision: approve` in the current stage's review.md "
            "and resuming. Not valid when the run is proof-blocked."
        ),
    )
    resume_parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve every remaining handoff for the rest of the run.",
    )
    _add_backend_arguments(
        resume_parser,
        command_help=(
            "Provider command for legacy command-backed runs that predate Terry's "
            "persisted backend config."
        ),
    )

    review_parser = subparsers.add_parser(
        "review",
        help="Generate Terry review artifacts for a completed proof attempt.",
    )
    review_parser.add_argument("run_id", nargs="?")
    review_parser.add_argument("--run-id", dest="legacy_run_id", help=argparse.SUPPRESS)
    review_parser.add_argument(
        "--attempt",
        type=int,
        help="Attempt number to review. Defaults to the latest completed attempt.",
    )
    _add_backend_arguments(
        review_parser,
        command_help=(
            "Provider command for command-backed Terry runs when generating review artifacts."
        ),
    )

    retry_parser = subparsers.add_parser(
        "retry",
        help="Grant more prove-and-repair attempts to a proof-blocked run.",
    )
    retry_parser.add_argument("run_id", nargs="?")
    retry_parser.add_argument("--run-id", dest="legacy_run_id", help=argparse.SUPPRESS)
    retry_parser.add_argument(
        "--attempts",
        type=int,
        default=3,
        help="Number of additional prove-and-repair attempts to grant (default: 3).",
    )
    retry_parser.add_argument("--auto-approve", action="store_true")
    _add_backend_arguments(
        retry_parser,
        command_help=(
            "Provider command for command-backed runs."
        ),
    )

    status_parser = subparsers.add_parser("status", help="Show the current Terry run summary.")
    status_parser.add_argument("run_id", nargs="?")
    status_parser.add_argument("--run-id", dest="legacy_run_id", help=argparse.SUPPRESS)
    status_parser.add_argument("--json", action="store_true")

    _add_legacy_approve_parser(subparsers, "approve-enrichment", "Approved by CLI.")
    _add_legacy_approve_parser(subparsers, "approve-spec", "Approved by CLI.")
    _add_legacy_approve_parser(subparsers, "approve-plan", "Approved by CLI.")
    _add_legacy_approve_parser(subparsers, "approve-final", "Approved by CLI.")
    _add_legacy_approve_parser(subparsers, "approve-stall", "Approved one more repair attempt.")

    return parser


def _normalize_global_options(argv: list[str]) -> list[str]:
    extracted: list[str] = []
    remaining: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        matched_option = None
        for option in _GLOBAL_OPTIONS_WITH_VALUES:
            if token == option:
                matched_option = option
                extracted.append(token)
                if index + 1 < len(argv):
                    extracted.append(argv[index + 1])
                    index += 2
                else:
                    index += 1
                break
            if token.startswith(f"{option}="):
                matched_option = option
                extracted.append(token)
                index += 1
                break
        if matched_option is not None:
            continue
        remaining.append(token)
        index += 1
    return extracted + remaining


def _add_prove_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--auto-approve", action="store_true")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--divide-and-conquer",
        action="store_true",
        help=(
            "Use the divide-and-conquer workflow variant: enrichment must write "
            "`01_enrichment/prerequisites/`, plan must write `02_plan/dependency_graph.md`, "
            "and proof turns are prompted to decompose work from that dependency graph."
        ),
    )
    mode_group.add_argument(
        "--yolo",
        action="store_true",
        help=(
            "Skip the plan stage entirely. Enrichment produces the natural-language "
            "proof, theorem statement, and formal statement in one pass, then the "
            "proof loop starts immediately."
        ),
    )
    _add_backend_arguments(parser)


def _add_backend_arguments(
    parser: argparse.ArgumentParser,
    *,
    suppress_help: bool = False,
    prefix: str = "",
    command_help: str | None = None,
) -> None:
    help_text = argparse.SUPPRESS if suppress_help else None
    parser.add_argument(
        "--agent-command",
        dest=f"{prefix}agent_command",
        help=help_text
        or command_help
        or (
            "Optional command that implements Terry turns over stdin/stdout. "
            "If omitted, Terry uses the default built-in backend."
        ),
    )
    parser.add_argument(
        "--agent-backend",
        dest=f"{prefix}agent_backend",
        choices=_AGENT_BACKEND_CHOICES,
        help=help_text
        or (
            "Choose the backend explicitly. Defaults to `command` when `--agent-command` "
            f"is set and `{_DEFAULT_BACKEND}` otherwise."
        ),
    )
    parser.add_argument(
        "--model",
        dest=f"{prefix}model",
        help=help_text
        or "Optional model override when a CLI backend (codex or claude) is used.",
    )
    # Legacy alias retained so existing invocations keep working.
    parser.add_argument(
        "--codex-model",
        dest=f"{prefix}codex_model",
        help=argparse.SUPPRESS,
    )


def _add_legacy_approve_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    command: str,
    default_notes: str,
) -> None:
    parser = subparsers.add_parser(command, help=argparse.SUPPRESS)
    parser.add_argument("--run-id", required=True, help=argparse.SUPPRESS)
    parser.add_argument("--notes", default=default_notes, help=argparse.SUPPRESS)


def _requested_model(args: argparse.Namespace) -> str | None:
    for attr in ("model", "legacy_model", "codex_model", "legacy_codex_model"):
        value = getattr(args, attr, None)
        if value:
            return value
    return None


def build_agent_config(args: argparse.Namespace, repo_root: Path) -> AgentConfig:
    backend = getattr(args, "agent_backend", None) or getattr(args, "legacy_agent_backend", None)
    agent_command = getattr(args, "agent_command", None) or getattr(args, "legacy_agent_command", None)
    model = _requested_model(args)

    if backend is None:
        backend = "command" if agent_command else _DEFAULT_BACKEND

    if backend == "command":
        if not agent_command:
            raise ValueError("`--agent-command` is required when `--agent-backend command` is used.")
        if model is not None:
            raise ValueError("`--model` is only valid with a CLI backend (codex or claude).")
        return AgentConfig(
            backend="command",
            command=_resolve_agent_command(shlex.split(agent_command), repo_root),
            model=None,
        )

    if backend in SUPPORTED_CLI_BACKENDS:
        if agent_command:
            raise ValueError("`--agent-command` is only valid with the command backend.")
        return AgentConfig(backend=backend, model=model)

    raise ValueError(f"Unknown agent backend `{backend}`.")


def build_agent(agent_config: AgentConfig, repo_root: Path):
    return build_agent_with_options(agent_config, repo_root, heartbeat_interval_seconds=_DEFAULT_BACKEND_HEARTBEAT_SECONDS)


def build_agent_with_options(
    agent_config: AgentConfig,
    repo_root: Path,
    *,
    heartbeat_interval_seconds: float,
):
    if agent_config.backend == "demo":
        raise ValueError(
            "Legacy `demo` backend runs can no longer continue. "
            "Start a new Terry run from the source with `codex`, `claude`, or "
            "`--agent-backend command --agent-command ...`."
        )
    if agent_config.backend in SUPPORTED_CLI_BACKENDS:
        executable = _cli_backend_executable(agent_config.backend)
        if shutil.which(executable) is None:
            return _MissingCliBackendAgent(agent_config.backend, executable)
        return CliExecFormalizationAgent(
            repo_root=repo_root,
            backend=agent_config.backend,
            model=agent_config.model,
            heartbeat_interval_seconds=heartbeat_interval_seconds,
        )
    if not agent_config.command:
        return _MissingCommandAgent()
    return SubprocessFormalizationAgent(
        agent_config.command,
        working_directory=repo_root,
        heartbeat_interval_seconds=heartbeat_interval_seconds,
    )


def _resolve_agent_command(command: list[str], repo_root: Path) -> list[str]:
    resolved_command: list[str] = []
    preserve_next_part = False
    for index, part in enumerate(command):
        if preserve_next_part:
            resolved_command.append(part)
            preserve_next_part = False
            continue

        if Path(part).is_absolute() or part.startswith("-"):
            resolved_command.append(part)
            if part in {"-m", "-c"}:
                preserve_next_part = True
            continue

        candidate = repo_root / part
        if index == 0 and "/" not in part:
            resolved_command.append(part)
            continue
        if candidate.exists():
            resolved_command.append(str(candidate))
            continue
        resolved_command.append(part)
    return resolved_command


def _resolve_source_path(source_path: Path, repo_root: Path) -> Path:
    if source_path.is_absolute():
        return source_path
    return repo_root / source_path


def _resolve_lake_path(lake_path: str | None, repo_root: Path) -> str | None:
    if not lake_path:
        return None
    configured = Path(lake_path).expanduser()
    if configured.is_absolute():
        return str(configured)
    if "/" in lake_path:
        return str((repo_root / configured).resolve())
    return lake_path


def _default_run_id(source_path: Path) -> str:
    stem = source_path.stem.lower().replace(" ", "-")
    cleaned = "".join(character if character.isalnum() or character in "-._" else "-" for character in stem)
    cleaned = cleaned.strip("-._") or "formalization"
    return validate_run_id(cleaned)


def _validate_prove_request(repo_root: Path, source_path: Path, run_id: str) -> None:
    store = RunStore(repo_root / "artifacts", run_id)
    if store.run_root.exists():
        raise FileExistsError(f"Run ID `{run_id}` already exists under artifacts/runs.")
    if not source_path.exists():
        raise FileNotFoundError(source_path)


def _resolve_run_id_argument(args: argparse.Namespace) -> str:
    positional = getattr(args, "run_id", None)
    legacy = getattr(args, "legacy_run_id", None)
    if positional and legacy and positional != legacy:
        raise ValueError("Conflicting run IDs supplied; use either the positional value or `--run-id`.")
    resolved = positional or legacy
    if not resolved:
        raise ValueError("`run_id` is required.")
    return resolved


def _load_manifest(repo_root: Path, run_id: str) -> RunManifest:
    store = RunStore(repo_root / "artifacts", run_id)
    payload = store.read_json("manifest.json")
    template_dir = Path(payload.get("template_dir") or _default_template_dir(repo_root))
    workflow = FormalizationWorkflow(
        repo_root=repo_root,
        agent=_StatusOnlyAgent(),
        agent_config=AgentConfig(backend="codex"),
        lean_runner=LeanRunner(
            template_dir=template_dir,
            lake_path=_resolve_lake_path(payload.get("lake_path"), repo_root),
        ),
    )
    return workflow.status(run_id)


def _resolve_backend_heartbeat_seconds(args: argparse.Namespace) -> float:
    value = float(getattr(args, "backend_heartbeat_seconds", _DEFAULT_BACKEND_HEARTBEAT_SECONDS))
    if value <= 0:
        raise ValueError("`--backend-heartbeat-seconds` must be greater than 0.")
    return value


def _supports_color(stream) -> bool:  # type: ignore[no-untyped-def]
    if os.environ.get("NO_COLOR") is not None:
        return False
    if getattr(stream, "isatty", None) is None or not stream.isatty():
        return False
    term = os.environ.get("TERM", "")
    return term not in {"", "dumb"}


def _colorize(text: str, code: str, *, enabled: bool) -> str:
    if not enabled:
        return text
    return f"\033[{code}m{text}\033[0m"


def _display_stage_label(stage: str | None) -> str:
    if not stage:
        return ""
    labels = {
        "awaiting_enrichment_approval": "enrichment review",
        "awaiting_plan_approval": "plan review",
        "awaiting_final_approval": "final review",
        "proof_blocked": "proof blocked",
    }
    return labels.get(stage, stage.replace("_", " "))


def _review_decision_guidance(stage: str | None) -> list[str]:
    if stage == RunStage.AWAITING_ENRICHMENT_APPROVAL.value:
        return [
            "decision: approve -> continue once the enrichment proof gate is satisfied",
            "decision: reject -> rerun enrichment with your notes",
        ]
    if stage == RunStage.AWAITING_PLAN_APPROVAL.value:
        return [
            "decision: approve -> enter the prove-and-repair loop",
            "decision: reject -> rerun the plan stage with your notes",
        ]
    if stage == RunStage.AWAITING_FINAL_APPROVAL.value:
        return [
            "decision: approve -> write 04_final/final.lean and complete the run",
            "decision: reject -> keep the run paused at final",
        ]
    if stage == RunStage.PROOF_BLOCKED.value:
        return [
            "decision: retry -> attach these notes to the next terry retry turn",
            "decision: reject -> ignored here; proof-blocked runs continue only through terry retry",
        ]
    return []


def _live_event_sink(payload: dict[str, Any]) -> None:
    color_enabled = _supports_color(sys.stderr)
    timestamp = _colorize(str(payload["timestamp"]), "36", enabled=color_enabled)
    details = payload.get("details") or {}
    summary = str(payload["summary"])
    if payload.get("event_type") == "backend_process_heartbeat":
        elapsed_seconds = details.get("elapsed_seconds")
        if isinstance(elapsed_seconds, (int, float)):
            summary = f"Still working. {elapsed_seconds:g}s elapsed."
    stage_label = _display_stage_label(payload.get("stage"))
    prefix = f"[{stage_label}] " if stage_label else ""
    print(f"{timestamp} {prefix}{summary}", file=sys.stderr, flush=True)

    if payload.get("event_type") != "checkpoint_opened":
        return

    review_path = details.get("review_path")
    continue_command = details.get("continue_command")
    quick_approve_command = details.get("quick_approve_command")
    artifact_paths = details.get("artifact_paths") or []
    for artifact_path in artifact_paths:
        print(f"  inspect: {artifact_path}", file=sys.stderr, flush=True)
    if review_path:
        print(f"  review: {review_path}", file=sys.stderr, flush=True)
    for guidance_line in _review_decision_guidance(payload.get("stage")):
        print(f"  {guidance_line}", file=sys.stderr, flush=True)
    if quick_approve_command:
        print(f"  approve: {quick_approve_command}", file=sys.stderr, flush=True)
        print(
            "           (only edit the review file when you need notes or a rejection)",
            file=sys.stderr,
            flush=True,
        )
    if continue_command:
        print(f"  next:    {continue_command}", file=sys.stderr, flush=True)


def _default_template_dir(repo_root: Path) -> str:
    discovered = discover_workspace_template(repo_root)
    if discovered is not None:
        return str(discovered)
    repo_template = repo_root / "lean_workspace_template"
    if repo_template.exists():
        return str(repo_template.resolve())
    return str((Path(__file__).resolve().parent / "workspace_template").resolve())


def _preferred_prove_template_dir(repo_root: Path) -> Path:
    discovered = discover_workspace_template(repo_root)
    if discovered is not None:
        return discovered
    return repo_root / "lean_workspace_template"


def _resume_agent_config(
    manifest: RunManifest,
    args: argparse.Namespace,
    repo_root: Path,
) -> AgentConfig:
    if manifest.agent_config.backend == "demo":
        raise ValueError(
            "Legacy `demo` backend runs can no longer continue. "
            "Start a new Terry run from the source with `codex`, `claude`, or "
            "`--agent-backend command --agent-command ...`."
        )
    agent_command = getattr(args, "agent_command", None) or getattr(args, "legacy_agent_command", None)
    requested_backend = getattr(args, "agent_backend", None) or getattr(args, "legacy_agent_backend", None)
    requested_model = _requested_model(args)
    if not agent_command and requested_backend is None and requested_model is None:
        return manifest.agent_config

    backend = requested_backend or ("command" if agent_command else manifest.agent_config.backend)
    if backend != manifest.agent_config.backend:
        raise ValueError(
            "Paused Terry runs keep the backend recorded in the manifest. "
            f"This run uses `{manifest.agent_config.backend}`."
        )

    if backend == "command":
        command = manifest.agent_config.command
        if agent_command:
            command = _resolve_agent_command(shlex.split(agent_command), repo_root)
        if not command:
            raise ValueError(
                "Resuming with the command backend requires `--agent-command` or a persisted command."
            )
        if requested_model is not None:
            raise ValueError("`--model` is only valid with a CLI backend (codex or claude).")
        return AgentConfig(
            backend="command",
            command=command,
            model=None,
        )

    if agent_command:
        raise ValueError("`--agent-command` is only valid with the command backend.")

    if requested_model is not None and requested_model != manifest.agent_config.model:
        raise ValueError(
            "Paused Terry runs keep the backend model recorded in the manifest."
        )
    return AgentConfig(
        backend=backend,
        model=(
            manifest.agent_config.model
            if manifest.agent_config.backend == backend
            else None
        ),
    )


def render_resume_command(
    run_id: str,
    repo_root: Path,
    lake_path: str | None,
    agent_config: AgentConfig | None = None,
    *,
    approve: bool = False,
) -> str:
    command = [
        "terry",
        "resume",
        run_id,
        "--workdir",
        str(repo_root.resolve()),
    ]
    if lake_path:
        command.extend(["--lake-path", lake_path])
    if approve:
        command.append("--approve")
    if agent_config is not None and agent_config.backend == "command":
        provider_command = (
            shlex.join(agent_config.command)
            if agent_config.command
            else "python3 path/to/provider.py"
        )
        command.extend(["--agent-command", provider_command])
    return " ".join(shlex.quote(part) for part in command)


def render_review_summary(run_id: str, attempt: int, repo_root: Path) -> str:
    attempt_dir = repo_root / "artifacts" / "runs" / run_id / "03_proof" / "attempts" / f"attempt_{attempt:04d}"
    review_dir = attempt_dir / "review"
    lines = [
        f"Run: {run_id}",
        f"Working directory: {repo_root.resolve()}",
        f"Reviewed attempt: {attempt}",
        "Artifacts:",
        f"- {review_dir.relative_to(repo_root) / 'walkthrough.md'}",
        f"- {review_dir.relative_to(repo_root) / 'readable_candidate.lean'}",
        f"- {review_dir.relative_to(repo_root) / 'error.md'}",
    ]
    return "\n".join(lines)

def render_retry_command(
    run_id: str,
    repo_root: Path,
    lake_path: str | None,
    agent_config: AgentConfig | None = None,
    attempts: int = 3,
) -> str:
    command = [
        "terry",
        "retry",
        run_id,
        "--attempts",
        str(attempts),
        "--workdir",
        str(repo_root.resolve()),
    ]
    if lake_path:
        command.extend(["--lake-path", lake_path])
    if agent_config is not None and agent_config.backend == "command":
        provider_command = (
            shlex.join(agent_config.command)
            if agent_config.command
            else "python3 path/to/provider.py"
        )
        command.extend(["--agent-command", provider_command])
    return " ".join(shlex.quote(part) for part in command)


def _resolve_status_surface(manifest: RunManifest, repo_root: Path) -> tuple[str, str] | None:
    candidates = _STATUS_SURFACE_CANDIDATES.get(manifest.current_stage)
    if candidates is None:
        return None

    run_root = repo_root / "artifacts" / "runs" / manifest.run_id
    for checkpoint_relative, review_relative in candidates:
        if (run_root / checkpoint_relative).exists() or (run_root / review_relative).exists():
            return checkpoint_relative, review_relative
    return candidates[0]


def _load_workflow_events(repo_root: Path, run_id: str) -> list[dict[str, Any]]:
    log_path = repo_root / "artifacts" / "runs" / run_id / "logs" / "workflow.jsonl"
    if not log_path.exists():
        return []

    events: list[dict[str, Any]] = []
    for raw_line in log_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            events.append(payload)
    return events


def _count_stage_turns(events: list[dict[str, Any]], backend_stage: str) -> int:
    completed = 0
    started = 0
    for event in events:
        if event.get("stage") != backend_stage:
            continue
        event_type = event.get("event_type")
        if event_type == "backend_stage_completed":
            completed += 1
        elif event_type == "backend_stage_started":
            started += 1
    return completed or started


def _mode_review_artifacts(manifest: RunManifest, repo_root: Path) -> list[str]:
    if not manifest.divide_and_conquer:
        return []

    run_root = repo_root / "artifacts" / "runs" / manifest.run_id
    artifact_candidates: list[Path] = []
    if manifest.current_stage == RunStage.AWAITING_ENRICHMENT_APPROVAL:
        artifact_candidates.append(run_root / "01_enrichment" / "prerequisites")
    elif manifest.current_stage == RunStage.AWAITING_PLAN_APPROVAL:
        artifact_candidates.extend(
            [
                run_root / "01_enrichment" / "prerequisites",
                run_root / "02_plan" / "dependency_graph.md",
            ]
        )

    return [
        str(path.relative_to(repo_root))
        for path in artifact_candidates
        if path.exists()
    ]


def render_manifest_summary(manifest: RunManifest, repo_root: Path) -> str:
    status_surface = _resolve_status_surface(manifest, repo_root)
    workflow_events = _load_workflow_events(repo_root, manifest.run_id)
    lines = [
        f"Run: {manifest.run_id}",
        f"Working directory: {repo_root.resolve()}",
        f"Stage: {manifest.current_stage.value}",
        f"Backend: {manifest.agent_config.backend}",
    ]
    if manifest.divide_and_conquer:
        lines.append("Mode: divide-and-conquer")
    turn_count_spec = _TURN_COUNT_LABELS.get(manifest.current_stage)
    if turn_count_spec is not None:
        backend_stage, label = turn_count_spec
        turn_count = _count_stage_turns(workflow_events, backend_stage)
        if turn_count == 0 and status_surface is not None:
            turn_count = 1
        lines.append(f"{label}: {turn_count}")
    elif manifest.current_stage in _PROOF_ATTEMPT_SUMMARY_STAGES or manifest.attempt_count > 0:
        lines.append(f"Proof attempts: {manifest.attempt_count}")
    if manifest.latest_error:
        lines.append(f"Latest error: {manifest.latest_error}")

    proof_blocked_stages = {RunStage.PROOF_BLOCKED, RunStage.LEGACY_AWAITING_STALL_REVIEW}
    approvable_stages = {
        RunStage.AWAITING_ENRICHMENT_APPROVAL,
        RunStage.AWAITING_PLAN_APPROVAL,
        RunStage.AWAITING_FINAL_APPROVAL,
        RunStage.LEGACY_AWAITING_ENRICHMENT_REVIEW,
        RunStage.LEGACY_AWAITING_SPEC_REVIEW,
        RunStage.LEGACY_AWAITING_PLAN_REVIEW,
        RunStage.LEGACY_AWAITING_FINAL_REVIEW,
    }
    if status_surface is not None:
        checkpoint_relative, review_relative = status_surface
        review_path = repo_root / "artifacts" / "runs" / manifest.run_id / review_relative
        checkpoint_path = repo_root / "artifacts" / "runs" / manifest.run_id / checkpoint_relative
        lines.append(f"Checkpoint: {checkpoint_path.relative_to(repo_root)}")
        lines.append(f"Review file: {review_path.relative_to(repo_root)}")
        for artifact_path in _mode_review_artifacts(manifest, repo_root):
            lines.append(f"Inspect: {artifact_path}")
        for guidance_line in _review_decision_guidance(manifest.current_stage.value):
            lines.append(f"Decision guide: {guidance_line}")
        if manifest.current_stage in proof_blocked_stages:
            lines.append(
                f"Retry with: {render_retry_command(manifest.run_id, repo_root, manifest.lake_path, manifest.agent_config)}"
            )
        else:
            if manifest.current_stage in approvable_stages:
                lines.append(
                    "Approve with: "
                    f"{render_resume_command(manifest.run_id, repo_root, manifest.lake_path, manifest.agent_config, approve=True)}"
                )
                lines.append(
                    "  (only edit the review file when you need notes or a rejection)"
                )
            lines.append(
                f"Resume with: {render_resume_command(manifest.run_id, repo_root, manifest.lake_path, manifest.agent_config)}"
            )

    if manifest.final_output_path:
        final_path = repo_root / "artifacts" / "runs" / manifest.run_id / manifest.final_output_path
        lines.append(f"Final output: {final_path.relative_to(repo_root)}")
    return "\n".join(lines)


def _compatibility_review(title: str, decision: str, notes: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"decision: {decision}",
        "",
        "Notes:",
    ]
    note_block = notes.strip()
    if note_block:
        lines.extend([note_block, ""])
    else:
        lines.append("")
    return "\n".join(lines)


def _write_compatibility_approval(
    repo_root: Path,
    run_id: str,
    command: str,
    notes: str,
) -> RunManifest:
    store = RunStore(repo_root / "artifacts", run_id)
    manifest = _load_manifest(repo_root, run_id)
    decision_value = "retry" if command == "approve-stall" else "approve"
    decision = ReviewDecision(decision=decision_value, updated_at=utc_now(), notes=notes)

    terry_targets = {
        "approve-enrichment": (
            "03_enrichment"
            if manifest.current_stage == RunStage.LEGACY_AWAITING_ENRICHMENT_REVIEW
            else "01_enrichment"
        ),
        "approve-spec": "02_plan" if manifest.current_stage == RunStage.AWAITING_PLAN_APPROVAL else "04_spec",
        "approve-plan": (
            "06_plan"
            if manifest.current_stage == RunStage.LEGACY_AWAITING_PLAN_REVIEW
            else "02_plan"
        ),
        "approve-final": (
            "10_final"
            if manifest.current_stage == RunStage.LEGACY_AWAITING_FINAL_REVIEW
            else "04_final"
        ),
        "approve-stall": (
            "09_review"
            if manifest.current_stage == RunStage.LEGACY_AWAITING_STALL_REVIEW
            else "03_proof"
        ),
    }
    stage_dir = terry_targets[command]
    review_path = store.path(f"{stage_dir}/review.md")
    if review_path.exists():
        review_path.write_text(
            _compatibility_review(review_path.parent.name.replace("_", " ").title(), decision_value, notes),
            encoding="utf-8",
        )
    if store.path(f"{stage_dir}/decision.json").parent.exists():
        store.write_json(f"{stage_dir}/decision.json", decision)

    legacy_decision_targets = {
        "approve-enrichment": "03_enrichment/decision.json",
        "approve-spec": "04_spec/decision.json",
        "approve-plan": "06_plan/decision.json",
        "approve-final": "10_final/decision.json",
        "approve-stall": "09_review/decision.json",
    }
    legacy_decision_path = legacy_decision_targets[command]
    if store.path(legacy_decision_path).parent.exists():
        store.write_json(legacy_decision_path, decision)

    return manifest


def _legacy_json_output(args: argparse.Namespace) -> bool:
    if args.command in {
        "run",
        "approve-enrichment",
        "approve-spec",
        "approve-plan",
        "approve-final",
        "approve-stall",
    }:
        return True
    return args.command in {"resume", "status"} and getattr(args, "legacy_run_id", None) is not None


def _render_legacy_manifest_payload(manifest: RunManifest) -> dict[str, object]:
    return to_jsonable(
        {
            "run_id": manifest.run_id,
            "source": manifest.source,
            "agent_name": manifest.agent_name,
            "created_at": manifest.created_at,
            "updated_at": manifest.updated_at,
            "current_stage": _LEGACY_STAGE_BY_CURRENT[manifest.current_stage],
            "workflow_version": manifest.workflow_version,
            "workflow_tags": manifest.workflow_tags,
            "divide_and_conquer": manifest.divide_and_conquer,
            "attempt_count": manifest.attempt_count,
            "latest_error": manifest.latest_error,
            "final_output_path": manifest.final_output_path,
        }
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args(_normalize_global_options(sys.argv[1:]))
    repo_root = args.repo_root.resolve()
    lake_path = _resolve_lake_path(args.lake_path, repo_root)
    backend_heartbeat_seconds = _resolve_backend_heartbeat_seconds(args)
    review_output: str | None = None

    try:
        if args.command in {"prove", "formalize", "run"}:
            source_path = _resolve_source_path(args.source, repo_root)
            run_id = args.run_id or _default_run_id(source_path)
            _validate_prove_request(repo_root, source_path, run_id)
            agent_config = build_agent_config(args, repo_root)
            if agent_config.backend in SUPPORTED_CLI_BACKENDS:
                executable = _cli_backend_executable(agent_config.backend)
                if shutil.which(executable) is None:
                    raise ValueError(
                        f"The `{executable}` CLI is not available. "
                        f"Install it before using the {agent_config.backend} backend, "
                        "or pass `--agent-backend command --agent-command ...`."
                    )
            agent = build_agent_with_options(
                agent_config,
                repo_root,
                heartbeat_interval_seconds=backend_heartbeat_seconds,
            )
            workflow = FormalizationWorkflow(
                repo_root=repo_root,
                agent=agent,
                agent_config=agent_config,
                lean_runner=LeanRunner(
                    template_dir=_preferred_prove_template_dir(repo_root),
                    repo_root=repo_root,
                    lake_path=lake_path,
                ),
                event_sink=_live_event_sink,
            )
            manifest = workflow.prove(
                source_path,
                run_id,
                auto_approve=args.auto_approve,
                divide_and_conquer=args.divide_and_conquer,
                yolo=args.yolo,
            )

        elif args.command == "resume":
            run_id = _resolve_run_id_argument(args)
            if args.approve and args.auto_approve:
                raise ValueError(
                    "Use either `--approve` (approve only the current handoff) or "
                    "`--auto-approve` (approve every remaining handoff), not both."
                )
            manifest = _load_manifest(repo_root, run_id)
            lake_path = lake_path or _resolve_lake_path(manifest.lake_path, repo_root)
            agent_config = _resume_agent_config(manifest, args, repo_root)
            workflow = FormalizationWorkflow(
                repo_root=repo_root,
                agent=build_agent_with_options(
                    agent_config,
                    repo_root,
                    heartbeat_interval_seconds=backend_heartbeat_seconds,
                ),
                agent_config=agent_config,
                lean_runner=LeanRunner(
                    template_dir=Path(manifest.template_dir),
                    repo_root=repo_root,
                    lake_path=lake_path,
                ),
                event_sink=_live_event_sink,
            )
            if args.approve:
                workflow.approve_current_checkpoint(run_id)
            manifest = workflow.resume(run_id, auto_approve=args.auto_approve)

        elif args.command == "review":
            run_id = _resolve_run_id_argument(args)
            manifest = _load_manifest(repo_root, run_id)
            lake_path = lake_path or _resolve_lake_path(manifest.lake_path, repo_root)
            agent_config = _resume_agent_config(manifest, args, repo_root)
            workflow = FormalizationWorkflow(
                repo_root=repo_root,
                agent=build_agent_with_options(
                    agent_config,
                    repo_root,
                    heartbeat_interval_seconds=backend_heartbeat_seconds,
                ),
                agent_config=agent_config,
                lean_runner=LeanRunner(
                    template_dir=Path(manifest.template_dir),
                    repo_root=repo_root,
                    lake_path=lake_path,
                ),
                event_sink=_live_event_sink,
            )
            reviewed_attempt = workflow.review_attempt(run_id, args.attempt)
            manifest = workflow.status(run_id)
            review_output = render_review_summary(run_id, reviewed_attempt, repo_root)

        elif args.command == "retry":
            run_id = _resolve_run_id_argument(args)
            manifest = _load_manifest(repo_root, run_id)
            lake_path = lake_path or _resolve_lake_path(manifest.lake_path, repo_root)
            agent_config = _resume_agent_config(manifest, args, repo_root)
            workflow = FormalizationWorkflow(
                repo_root=repo_root,
                agent=build_agent_with_options(
                    agent_config,
                    repo_root,
                    heartbeat_interval_seconds=backend_heartbeat_seconds,
                ),
                agent_config=agent_config,
                lean_runner=LeanRunner(
                    template_dir=Path(manifest.template_dir),
                    repo_root=repo_root,
                    lake_path=lake_path,
                ),
                event_sink=_live_event_sink,
            )
            manifest = workflow.retry(run_id, extra_attempts=args.attempts, auto_approve=args.auto_approve)

        elif args.command.startswith("approve-"):
            run_id = args.run_id
            manifest = _write_compatibility_approval(repo_root, run_id, args.command, args.notes)
            lake_path = lake_path or _resolve_lake_path(manifest.lake_path, repo_root)
            agent_config = _resume_agent_config(manifest, args, repo_root)
            workflow = FormalizationWorkflow(
                repo_root=repo_root,
                agent=build_agent_with_options(
                    agent_config,
                    repo_root,
                    heartbeat_interval_seconds=backend_heartbeat_seconds,
                ),
                agent_config=agent_config,
                lean_runner=LeanRunner(
                    template_dir=Path(manifest.template_dir),
                    repo_root=repo_root,
                    lake_path=lake_path,
                ),
                event_sink=_live_event_sink,
            )
            manifest = workflow.resume(run_id, auto_approve=False)

        else:
            run_id = _resolve_run_id_argument(args)
            manifest = _load_manifest(repo_root, run_id)
            if getattr(args, "json", False):
                print(json.dumps(to_jsonable(manifest), indent=2))
                return

        if review_output is not None:
            print(review_output)
        elif _legacy_json_output(args):
            print(json.dumps(_render_legacy_manifest_payload(manifest), indent=2))
        else:
            print(render_manifest_summary(manifest, repo_root))
    except (RuntimeError, ValueError, FileExistsError, FileNotFoundError) as exc:
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()
