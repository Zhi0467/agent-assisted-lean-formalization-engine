from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lean_formalization_engine.demo_agent import DemoFormalizationAgent
from lean_formalization_engine.lean_runner import LeanRunner
from lean_formalization_engine.models import RunStage
from lean_formalization_engine.workflow import FormalizationWorkflow


class DemoWorkflowTest(unittest.TestCase):
    def _resolve_output_path(self, repo_root: Path, run_id: str, output_path: str) -> Path:
        path = Path(output_path)
        if path.is_absolute():
            return path
        return repo_root / "artifacts" / "runs" / run_id / path

    def _write_fake_lake(self, directory: Path) -> Path:
        fake_lake = directory / "lake"
        fake_lake.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import pathlib",
                    "import sys",
                    "",
                    "def main() -> int:",
                    "    args = sys.argv[1:]",
                    "    if args[:2] == ['env', 'lean']:",
                    "        content = pathlib.Path(args[2]).read_text(encoding='utf-8')",
                    "        if 'sorry' in content:",
                    "            print('found sorry', file=sys.stderr)",
                    "            return 1",
                    "        return 0",
                    "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                    "        return 0",
                    "    print(f'unexpected args: {args}', file=sys.stderr)",
                    "    return 1",
                    "",
                    "if __name__ == '__main__':",
                    "    raise SystemExit(main())",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        fake_lake.chmod(0o755)
        return fake_lake

    def test_demo_workflow_completes_with_fake_lake(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        template_dir = project_root / "lean_workspace_template"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            fake_lake = self._write_fake_lake(temp_root)
            source_path = temp_root / "input.md"
            source_path.write_text(
                "For every natural number n, adding zero on the left gives back n.\n"
                "Target statement: 0 + n = n.\n",
                encoding="utf-8",
            )

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )
            manifest = workflow.run(source_path=source_path, run_id="demo-test", auto_approve=True)

            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertIsNotNone(manifest.final_output_path)
            final_output = self._resolve_output_path(
                temp_root,
                "demo-test",
                manifest.final_output_path or "",
            )
            self.assertTrue(final_output.exists())
            self.assertIn("zero_add_demo", final_output.read_text(encoding="utf-8"))

    def test_manual_review_path_is_explicit(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        template_dir = project_root / "lean_workspace_template"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            fake_lake = self._write_fake_lake(temp_root)
            source_path = temp_root / "input.md"
            source_path.write_text(
                "For every natural number n, adding zero on the left gives back n.\n"
                "Target statement: 0 + n = n.\n",
                encoding="utf-8",
            )
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )

            manifest = workflow.run(source_path=source_path, run_id="manual-review", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_SPEC_REVIEW)

            workflow.approve_spec("manual-review")
            manifest = workflow.resume("manual-review", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_REVIEW)

            workflow.approve_plan("manual-review")
            manifest = workflow.resume("manual-review", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_REVIEW)

            workflow.approve_final("manual-review")
            manifest = workflow.resume("manual-review", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)

    def test_packaged_template_matches_repo_template(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        repo_template = project_root / "lean_workspace_template"
        package_template = project_root / "src" / "lean_formalization_engine" / "workspace_template"

        for relative_path in [
            "FormalizationEngineWorkspace.lean",
            "FormalizationEngineWorkspace/Basic.lean",
            "FormalizationEngineWorkspace/Generated.lean",
            "lakefile.toml",
            "lean-toolchain",
        ]:
            self.assertEqual(
                (repo_template / relative_path).read_text(encoding="utf-8"),
                (package_template / relative_path).read_text(encoding="utf-8"),
            )
