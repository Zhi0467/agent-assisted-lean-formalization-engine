from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .demo_agent import DemoFormalizationAgent
from .lean_runner import LeanRunner
from .workflow import FormalizationWorkflow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Lean formalization scaffold.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="Repository root that contains artifacts/, examples/, and lean_workspace_template/.",
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


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    repo_root = args.repo_root.resolve()
    template_root = repo_root / "lean_workspace_template"
    if not template_root.exists():
        template_root = Path(__file__).resolve().parent / "workspace_template"

    workflow = FormalizationWorkflow(
        repo_root=repo_root,
        agent=DemoFormalizationAgent(),
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
