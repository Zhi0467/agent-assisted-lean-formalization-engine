from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lean_formalization_engine.demo_agent import DemoFormalizationAgent
from lean_formalization_engine.lean_runner import LeanRunner
from lean_formalization_engine.models import (
    AgentTurn,
    CompileAttempt,
    ContextPack,
    FormalizationPlan,
    LeanDraft,
    RunStage,
    SourceRef,
    TheoremSpec,
)
from lean_formalization_engine.workflow import FormalizationWorkflow


class RepairResumeAgent:
    name = "repair_resume_agent"

    def draft_theorem_spec(
        self,
        source_ref: SourceRef,
        normalized_text: str,
    ) -> tuple[TheoremSpec, AgentTurn]:
        spec = TheoremSpec(
            title="Zero add",
            informal_statement=normalized_text.strip(),
            assumptions=["n : Nat"],
            conclusion="0 + n = n",
            symbols=["0", "+", "Nat"],
            ambiguities=[],
            paraphrase="Zero on the left does not change a natural number.",
        )
        return spec, AgentTurn(request_payload={}, prompt="spec", raw_response="spec")

    def draft_formalization_plan(
        self,
        theorem_spec: TheoremSpec,
        context_pack: ContextPack,
    ) -> tuple[FormalizationPlan, AgentTurn]:
        plan = FormalizationPlan(
            theorem_name="zero_add_resume",
            imports=["FormalizationEngineWorkspace.Basic"],
            helper_definitions=[],
            target_statement="theorem zero_add_resume (n : Nat) : 0 + n = n",
            proof_sketch=["Use the existing `Nat.zero_add` lemma."],
        )
        return plan, AgentTurn(request_payload={}, prompt="plan", raw_response="plan")

    def draft_lean_file(
        self,
        plan: FormalizationPlan,
        attempt: int,
        previous_result: CompileAttempt | None,
    ) -> tuple[LeanDraft, AgentTurn]:
        if attempt == 1:
            content = (
                "import FormalizationEngineWorkspace.Basic\n\n"
                "theorem zero_add_resume (n : Nat) : 0 + n = n := by\n"
                "  sorry\n"
            )
        else:
            assert previous_result is not None
            assert previous_result.attempt == 1
            assert previous_result.contains_sorry
            assert not previous_result.quality_gate_passed
            content = (
                "import FormalizationEngineWorkspace.Basic\n\n"
                "theorem zero_add_resume (n : Nat) : 0 + n = n := by\n"
                "  simpa using Nat.zero_add n\n"
            )
        draft = LeanDraft(
            theorem_name="zero_add_resume",
            module_name="FormalizationEngineWorkspace.Generated",
            imports=["FormalizationEngineWorkspace.Basic"],
            content=content,
            rationale=f"attempt {attempt}",
        )
        return draft, AgentTurn(request_payload={"attempt": attempt}, prompt="draft", raw_response="draft")


class CrashBeforeRepairAgent(RepairResumeAgent):
    name = "crash_before_repair_agent"

    def draft_lean_file(
        self,
        plan: FormalizationPlan,
        attempt: int,
        previous_result: CompileAttempt | None,
    ) -> tuple[LeanDraft, AgentTurn]:
        if attempt == 2:
            raise RuntimeError("simulated crash before second attempt")
        return super().draft_lean_file(plan, attempt, previous_result)


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

    def test_resume_repair_loop_reuses_last_compile_result(self) -> None:
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

            crashing_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=CrashBeforeRepairAgent(),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )
            with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                crashing_workflow.run(
                    source_path=source_path,
                    run_id="repair-resume",
                    auto_approve=True,
                )

            manifest = crashing_workflow.status("repair-resume")
            self.assertEqual(manifest.current_stage, RunStage.REPAIRING)
            self.assertEqual(manifest.attempt_count, 1)

            resumed_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )
            manifest = resumed_workflow.resume("repair-resume", auto_approve=True)

            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(manifest.attempt_count, 2)
            self.assertIsNotNone(manifest.final_output_path)
