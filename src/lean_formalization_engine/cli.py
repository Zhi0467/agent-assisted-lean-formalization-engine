from __future__ import annotations

import argparse
import json
import shlex
from pathlib import Path

from .codex_agent import CodexCliFormalizationAgent
from .demo_agent import DemoFormalizationAgent
from .lean_runner import LeanRunner
from .models import AgentConfig, RunManifest, RunStage, to_jsonable
from .storage import RunStore, validate_run_id
from .subprocess_agent import SubprocessFormalizationAgent
from .template_manager import discover_workspace_template, resolve_workspace_template
from .workflow import FormalizationWorkflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="terry",
        description="Human-reviewed Lean formalization workflow with a bounded prove-and-repair loop.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Project root that contains artifacts/ and, optionally, lean_workspace_template/.",
    )
    parser.add_argument(
        "--lake-path",
        help="Optional `lake` executable override for template initialization and compile checks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prove_parser = subparsers.add_parser("prove", help="Start a new Terry run.")
    _add_prove_arguments(prove_parser)

    formalize_parser = subparsers.add_parser(
        "formalize",
        help="Alias for `prove`.",
    )
    _add_prove_arguments(formalize_parser)

    resume_parser = subparsers.add_parser(
        "resume",
        help="Resume a paused Terry run after updating its review file.",
    )
    resume_parser.add_argument("run_id")
    resume_parser.add_argument("--auto-approve", action="store_true")
    resume_parser.add_argument(
        "--agent-command",
        help=(
            "Provider command for legacy command-backed runs that predate Terry's "
            "persisted backend config."
        ),
    )

    status_parser = subparsers.add_parser("status", help="Show the current Terry run summary.")
    status_parser.add_argument("run_id")
    status_parser.add_argument("--json", action="store_true")

    return parser


def _add_prove_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("source", type=Path)
    parser.add_argument("--run-id")
    parser.add_argument("--auto-approve", action="store_true")
    parser.add_argument(
        "--agent-command",
        help=(
            "Optional command that implements Terry turns over stdin/stdout. "
            "If omitted, Terry uses the default built-in backend."
        ),
    )
    parser.add_argument(
        "--agent-backend",
        choices=["demo", "command", "codex"],
        help=(
            "Choose the backend explicitly. Defaults to `command` when `--agent-command` "
            "is set and `codex` otherwise."
        ),
    )
    parser.add_argument(
        "--codex-model",
        help="Optional Codex model override when the Codex backend is used.",
    )


def build_agent_config(args: argparse.Namespace, repo_root: Path) -> AgentConfig:
    backend = getattr(args, "agent_backend", None)
    agent_command = getattr(args, "agent_command", None)
    codex_model = getattr(args, "codex_model", None)

    if backend is None:
        backend = "command" if agent_command else "codex"

    if backend == "command":
        if not agent_command:
            raise ValueError("`--agent-command` is required when `--agent-backend command` is used.")
        return AgentConfig(
            backend="command",
            command=_resolve_agent_command(shlex.split(agent_command), repo_root),
            codex_model=None,
        )

    if backend == "demo":
        return AgentConfig(backend="demo")

    return AgentConfig(backend="codex", codex_model=codex_model)


def build_agent(agent_config: AgentConfig, repo_root: Path):
    if agent_config.backend == "demo":
        return DemoFormalizationAgent()
    if agent_config.backend == "codex":
        return CodexCliFormalizationAgent(repo_root=repo_root, model=agent_config.codex_model)
    if not agent_config.command:
        raise ValueError(
            "This command-backed run predates Terry's persisted backend config, "
            "so resume it with `--agent-command \"python3 path/to/provider.py\"`."
        )
    return SubprocessFormalizationAgent(agent_config.command, working_directory=repo_root)


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


def _load_manifest(repo_root: Path, run_id: str) -> RunManifest:
    store = RunStore(repo_root / "artifacts", run_id)
    payload = store.read_json("manifest.json")
    template_dir = Path(payload.get("template_dir") or _default_template_dir(repo_root))
    workflow = FormalizationWorkflow(
        repo_root=repo_root,
        agent=DemoFormalizationAgent(),
        agent_config=AgentConfig(backend="demo"),
        lean_runner=LeanRunner(template_dir=template_dir, lake_path=payload.get("lake_path")),
    )
    return workflow.status(run_id)


def _default_template_dir(repo_root: Path) -> str:
    discovered = discover_workspace_template(repo_root)
    if discovered is not None:
        return str(discovered)
    repo_template = repo_root / "lean_workspace_template"
    if repo_template.exists():
        return str(repo_template.resolve())
    return str((Path(__file__).resolve().parent / "workspace_template").resolve())


def _resume_agent_config(
    manifest: RunManifest,
    args: argparse.Namespace,
    repo_root: Path,
) -> AgentConfig:
    agent_command = getattr(args, "agent_command", None)
    if not agent_command:
        return manifest.agent_config

    if manifest.agent_config.backend != "command":
        raise ValueError("`--agent-command` is only valid for command-backed Terry runs.")
    if manifest.agent_config.command is not None:
        raise ValueError("This Terry run already has a persisted provider command. Resume without `--agent-command`.")

    return AgentConfig(
        backend="command",
        command=_resolve_agent_command(shlex.split(agent_command), repo_root),
        codex_model=None,
    )


def render_resume_command(run_id: str, repo_root: Path, lake_path: str | None) -> str:
    command = [
        "terry",
        "--repo-root",
        str(repo_root.resolve()),
    ]
    if lake_path:
        command.extend(["--lake-path", lake_path])
    command.extend(["resume", run_id])
    return " ".join(shlex.quote(part) for part in command)


def render_manifest_summary(manifest: RunManifest, repo_root: Path) -> str:
    lines = [
        f"Run: {manifest.run_id}",
        f"Stage: {manifest.current_stage.value}",
        f"Backend: {manifest.agent_config.backend}",
        f"Attempts: {manifest.attempt_count}",
    ]
    if manifest.latest_error:
        lines.append(f"Latest error: {manifest.latest_error}")

    review_map = {
        RunStage.AWAITING_ENRICHMENT_APPROVAL: "01_enrichment/review.md",
        RunStage.AWAITING_PLAN_APPROVAL: "02_plan/review.md",
        RunStage.PROOF_BLOCKED: "03_proof/review.md",
        RunStage.AWAITING_FINAL_APPROVAL: "04_final/review.md",
    }
    checkpoint_map = {
        RunStage.AWAITING_ENRICHMENT_APPROVAL: "01_enrichment/checkpoint.md",
        RunStage.AWAITING_PLAN_APPROVAL: "02_plan/checkpoint.md",
        RunStage.PROOF_BLOCKED: "03_proof/checkpoint.md",
        RunStage.AWAITING_FINAL_APPROVAL: "04_final/checkpoint.md",
    }
    if manifest.current_stage in review_map:
        review_path = repo_root / "artifacts" / "runs" / manifest.run_id / review_map[manifest.current_stage]
        checkpoint_path = repo_root / "artifacts" / "runs" / manifest.run_id / checkpoint_map[manifest.current_stage]
        lines.append(f"Checkpoint: {checkpoint_path.relative_to(repo_root)}")
        lines.append(f"Review file: {review_path.relative_to(repo_root)}")
        lines.append(
            f"Resume with: {render_resume_command(manifest.run_id, repo_root, manifest.lake_path)}"
        )

    if manifest.final_output_path:
        final_path = repo_root / "artifacts" / "runs" / manifest.run_id / manifest.final_output_path
        lines.append(f"Final output: {final_path.relative_to(repo_root)}")
    return "\n".join(lines)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    package_template_dir = Path(__file__).resolve().parent / "workspace_template"

    try:
        if args.command in {"prove", "formalize"}:
            source_path = _resolve_source_path(args.source, repo_root)
            run_id = args.run_id or _default_run_id(source_path)
            _validate_prove_request(repo_root, source_path, run_id)
            agent_config = build_agent_config(args, repo_root)
            agent = build_agent(agent_config, repo_root)
            template_resolution = resolve_workspace_template(
                repo_root,
                package_template_dir,
                lake_path=args.lake_path,
            )
            workflow = FormalizationWorkflow(
                repo_root=repo_root,
                agent=agent,
                agent_config=agent_config,
                lean_runner=LeanRunner(
                    template_dir=template_resolution.template_dir,
                    lake_path=args.lake_path,
                ),
            )
            manifest = workflow.prove(source_path, run_id, auto_approve=args.auto_approve)
            RunStore(repo_root / "artifacts", run_id).append_log(
                "template_selected",
                f"Using workspace template from `{template_resolution.template_dir}` via {template_resolution.origin}.",
                stage="input",
                details={"command": template_resolution.command or []},
            )

        elif args.command == "resume":
            manifest = _load_manifest(repo_root, args.run_id)
            lake_path = args.lake_path or manifest.lake_path
            agent_config = _resume_agent_config(manifest, args, repo_root)
            workflow = FormalizationWorkflow(
                repo_root=repo_root,
                agent=build_agent(agent_config, repo_root),
                agent_config=agent_config,
                lean_runner=LeanRunner(template_dir=Path(manifest.template_dir), lake_path=lake_path),
            )
            manifest = workflow.resume(args.run_id, auto_approve=args.auto_approve)

        else:
            manifest = _load_manifest(repo_root, args.run_id)
            if args.json:
                print(json.dumps(to_jsonable(manifest), indent=2))
                return

        print(render_manifest_summary(manifest, repo_root))
    except (RuntimeError, ValueError, FileExistsError, FileNotFoundError) as exc:
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()
