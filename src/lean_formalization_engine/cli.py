from __future__ import annotations

import argparse
import json
import shlex
from dataclasses import asdict
from pathlib import Path

from .codex_agent import CodexCliFormalizationAgent
from .demo_agent import DemoFormalizationAgent
from .lean_runner import LeanRunner
from .subprocess_agent import SubprocessFormalizationAgent
from .workflow import FormalizationWorkflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Lean formalization scaffold.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root that contains artifacts/, examples/, and lean_workspace_template/.",
    )
    parser.add_argument(
        "--agent-command",
        help=(
            "Optional command that implements extraction, enrichment, theorem-spec, plan, "
            "and Lean-draft turns over stdin/stdout. If omitted, the CLI uses the default "
            "built-in backend."
        ),
    )
    parser.add_argument(
        "--agent-backend",
        choices=["demo", "command", "codex"],
        help=(
            "Choose the agent backend explicitly. Defaults to `command` when "
            "`--agent-command` is set and `codex` otherwise. Use `demo` explicitly "
            "for deterministic example runs."
        ),
    )
    parser.add_argument(
        "--codex-model",
        help="Optional Codex model override when `--agent-backend codex` is used.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Start a new run.")
    run_parser.add_argument("--source", required=True, type=Path)
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--auto-approve", action="store_true")

    resume_parser = subparsers.add_parser("resume", help="Resume an existing run.")
    resume_parser.add_argument("--run-id", required=True)
    resume_parser.add_argument("--auto-approve", action="store_true")

    approve_enrichment_parser = subparsers.add_parser(
        "approve-enrichment",
        help="Approve the saved enrichment handoff.",
    )
    approve_enrichment_parser.add_argument("--run-id", required=True)
    approve_enrichment_parser.add_argument("--notes", default="Approved by CLI.")

    approve_spec_parser = subparsers.add_parser("approve-spec", help="Approve the saved theorem spec.")
    approve_spec_parser.add_argument("--run-id", required=True)
    approve_spec_parser.add_argument("--notes", default="Approved by CLI.")

    approve_plan_parser = subparsers.add_parser("approve-plan", help="Approve the saved formalization plan.")
    approve_plan_parser.add_argument("--run-id", required=True)
    approve_plan_parser.add_argument("--notes", default="Approved by CLI.")

    approve_final_parser = subparsers.add_parser("approve-final", help="Approve the final Lean candidate.")
    approve_final_parser.add_argument("--run-id", required=True)
    approve_final_parser.add_argument("--notes", default="Approved by CLI.")

    approve_stall_parser = subparsers.add_parser(
        "approve-stall",
        help="Approve one more repair attempt after a stalled run.",
    )
    approve_stall_parser.add_argument("--run-id", required=True)
    approve_stall_parser.add_argument(
        "--notes",
        default="Approved one more repair attempt.",
    )

    status_parser = subparsers.add_parser("status", help="Show manifest state for a run.")
    status_parser.add_argument("--run-id", required=True)

    return parser


def build_agent(args: argparse.Namespace, repo_root: Path):
    backend = getattr(args, "agent_backend", None)
    agent_command = getattr(args, "agent_command", None)
    codex_model = getattr(args, "codex_model", None)
    if backend is None:
        if agent_command:
            backend = "command"
        else:
            backend = "codex"

    if backend == "demo":
        return DemoFormalizationAgent()
    if backend == "codex":
        return CodexCliFormalizationAgent(repo_root=repo_root, model=codex_model)
    if not agent_command:
        raise ValueError("`--agent-command` is required when `--agent-backend command` is used.")
    command = _resolve_agent_command(shlex.split(agent_command), repo_root)
    return SubprocessFormalizationAgent(command, working_directory=repo_root)


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


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    template_root = repo_root / "lean_workspace_template"
    if not template_root.exists():
        template_root = Path(__file__).resolve().parent / "workspace_template"

    workflow = FormalizationWorkflow(
        repo_root=repo_root,
        agent=build_agent(args, repo_root),
        lean_runner=LeanRunner(template_dir=template_root),
    )

    if args.command == "run":
        manifest = workflow.run(
            _resolve_source_path(args.source, repo_root),
            args.run_id,
            auto_approve=args.auto_approve,
        )
    elif args.command == "resume":
        manifest = workflow.resume(args.run_id, auto_approve=args.auto_approve)
    elif args.command == "approve-enrichment":
        workflow.approve_enrichment(args.run_id, notes=args.notes)
        manifest = workflow.status(args.run_id)
    elif args.command == "approve-spec":
        workflow.approve_spec(args.run_id, notes=args.notes)
        manifest = workflow.status(args.run_id)
    elif args.command == "approve-plan":
        workflow.approve_plan(args.run_id, notes=args.notes)
        manifest = workflow.status(args.run_id)
    elif args.command == "approve-final":
        workflow.approve_final(args.run_id, notes=args.notes)
        manifest = workflow.status(args.run_id)
    elif args.command == "approve-stall":
        workflow.approve_stall(args.run_id, notes=args.notes)
        manifest = workflow.status(args.run_id)
    else:
        manifest = workflow.status(args.run_id)

    print(json.dumps(asdict(manifest), indent=2, default=str))


if __name__ == "__main__":
    main()
