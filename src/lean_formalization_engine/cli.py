from __future__ import annotations

import argparse
import json
import shlex
from dataclasses import asdict
from pathlib import Path

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
            "Optional command that implements theorem-spec, plan, and Lean-draft turns "
            "over stdin/stdout. If omitted, the deterministic demo agent is used."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Start a new run.")
    run_parser.add_argument("--source", required=True, type=Path)
    run_parser.add_argument("--run-id", required=True)
    run_parser.add_argument("--auto-approve", action="store_true")

    resume_parser = subparsers.add_parser("resume", help="Resume an existing run.")
    resume_parser.add_argument("--run-id", required=True)
    resume_parser.add_argument("--auto-approve", action="store_true")

    approve_spec_parser = subparsers.add_parser("approve-spec", help="Approve the saved theorem spec.")
    approve_spec_parser.add_argument("--run-id", required=True)
    approve_spec_parser.add_argument("--notes", default="Approved by CLI.")

    approve_plan_parser = subparsers.add_parser("approve-plan", help="Approve the saved formalization plan.")
    approve_plan_parser.add_argument("--run-id", required=True)
    approve_plan_parser.add_argument("--notes", default="Approved by CLI.")

    approve_final_parser = subparsers.add_parser("approve-final", help="Approve the final Lean candidate.")
    approve_final_parser.add_argument("--run-id", required=True)
    approve_final_parser.add_argument("--notes", default="Approved by CLI.")

    status_parser = subparsers.add_parser("status", help="Show manifest state for a run.")
    status_parser.add_argument("--run-id", required=True)

    return parser


def build_agent(args: argparse.Namespace, repo_root: Path):
    if not args.agent_command:
        return DemoFormalizationAgent()
    command = _resolve_agent_command(shlex.split(args.agent_command), repo_root)
    return SubprocessFormalizationAgent(command)


def _resolve_agent_command(command: list[str], repo_root: Path) -> list[str]:
    resolved_command: list[str] = []
    for index, part in enumerate(command):
        if Path(part).is_absolute() or part.startswith("-"):
            resolved_command.append(part)
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
        manifest = workflow.run(args.source, args.run_id, auto_approve=args.auto_approve)
    elif args.command == "resume":
        manifest = workflow.resume(args.run_id, auto_approve=args.auto_approve)
    elif args.command == "approve-spec":
        workflow.approve_spec(args.run_id, notes=args.notes)
        manifest = workflow.status(args.run_id)
    elif args.command == "approve-plan":
        workflow.approve_plan(args.run_id, notes=args.notes)
        manifest = workflow.status(args.run_id)
    elif args.command == "approve-final":
        workflow.approve_final(args.run_id, notes=args.notes)
        manifest = workflow.status(args.run_id)
    else:
        manifest = workflow.status(args.run_id)

    print(json.dumps(asdict(manifest), indent=2, default=str))


if __name__ == "__main__":
    main()
