from __future__ import annotations

import argparse
from pathlib import Path

from .demo_agent import DemoFormalizationAgent
from .lean_runner import LeanRunner
from .models import SourceKind, SourceRef
from .storage import ArtifactStore
from .workflow import FormalizationWorkflow, WorkflowOptions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Lean formalization engine scaffold.")
    parser.add_argument("--input", required=True, help="Path to the theorem source.")
    parser.add_argument("--kind", choices=[kind.value for kind in SourceKind], default="markdown")
    parser.add_argument("--run-id", required=True, help="Run identifier used under artifacts/runs/.")
    parser.add_argument(
        "--artifacts-root",
        default="artifacts/runs",
        help="Directory where run artifacts should be written.",
    )
    parser.add_argument("--auto-approve-spec", action="store_true")
    parser.add_argument("--auto-approve-plan", action="store_true")
    parser.add_argument("--auto-finalize", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    repo_root = _resolve_repo_root()
    workflow = FormalizationWorkflow(
        store=ArtifactStore(repo_root / args.artifacts_root),
        agent=DemoFormalizationAgent(),
        lean_runner=LeanRunner(repo_root / "lean_workspace_template"),
    )
    manifest = workflow.run(
        run_id=args.run_id,
        source=SourceRef(path=args.input, kind=SourceKind(args.kind), label=Path(args.input).stem),
        options=WorkflowOptions(
            auto_approve_spec=args.auto_approve_spec,
            auto_approve_plan=args.auto_approve_plan,
            auto_finalize=args.auto_finalize,
        ),
    )
    print(f"run_id={manifest.run_id}")
    print(f"stage={manifest.current_stage.value}")
    print(f"status={manifest.status.value}")
    if manifest.final_output_path:
        print(f"final_output={manifest.final_output_path}")


def _resolve_repo_root() -> Path:
    candidates = [Path.cwd(), Path(__file__).resolve().parents[2]]
    for candidate in candidates:
        if (candidate / "lean_workspace_template").exists():
            return candidate
    return Path.cwd()
