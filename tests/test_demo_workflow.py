from __future__ import annotations

import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
import sys

from lean_formalization_engine.cli import _resolve_source_path, build_agent
from lean_formalization_engine.demo_agent import DemoFormalizationAgent
from lean_formalization_engine.lean_runner import LeanRunner
from lean_formalization_engine.models import (
    AgentTurn,
    ContextPack,
    FormalizationPlan,
    HumanDecision,
    LeanDraft,
    RepairContext,
    RunStage,
    SourceRef,
    TheoremSpec,
    utc_now,
)
from lean_formalization_engine.storage import RunStore
from lean_formalization_engine.subprocess_agent import SubprocessFormalizationAgent
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
        repair_context: RepairContext,
    ) -> tuple[LeanDraft, AgentTurn]:
        if repair_context.current_attempt == 1:
            content = (
                "import FormalizationEngineWorkspace.Basic\n\n"
                "theorem zero_add_resume (n : Nat) : 0 + n = n := by\n"
                "  sorry\n"
            )
        else:
            assert repair_context.previous_draft is not None
            assert "sorry" in repair_context.previous_draft.content
            assert repair_context.previous_result is not None
            assert repair_context.previous_result.attempt == 1
            assert repair_context.previous_result.contains_sorry
            assert not repair_context.previous_result.quality_gate_passed
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
            rationale=f"attempt {repair_context.current_attempt}",
        )
        return draft, AgentTurn(
            request_payload={"attempt": repair_context.current_attempt},
            prompt="draft",
            raw_response="draft",
        )


class CrashBeforeRepairAgent(RepairResumeAgent):
    name = "crash_before_repair_agent"

    def draft_lean_file(
        self,
        plan: FormalizationPlan,
        repair_context: RepairContext,
    ) -> tuple[LeanDraft, AgentTurn]:
        if repair_context.current_attempt == 2:
            raise RuntimeError("simulated crash before second attempt")
        return super().draft_lean_file(plan, repair_context)


class CrashBeforeFirstDraftAgent(RepairResumeAgent):
    name = "crash_before_first_draft_agent"

    def draft_lean_file(
        self,
        plan: FormalizationPlan,
        repair_context: RepairContext,
    ) -> tuple[LeanDraft, AgentTurn]:
        if repair_context.current_attempt == 1:
            raise RuntimeError("simulated crash before first draft")
        return super().draft_lean_file(plan, repair_context)


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

    def test_compile_artifacts_hide_resolved_lake_path(self) -> None:
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
            workflow.run(source_path=source_path, run_id="portable-command", auto_approve=True)

            result_path = (
                temp_root
                / "artifacts"
                / "runs"
                / "portable-command"
                / "06_compile"
                / "attempt_0001"
                / "result.json"
            )
            result_text = result_path.read_text(encoding="utf-8")
            payload = json.loads(result_text)

            self.assertEqual(payload["command"], ["lake build FormalizationEngineWorkspace"])
            self.assertIn("$ lake build FormalizationEngineWorkspace", payload["stdout"])
            self.assertIn("$ lake build FormalizationEngineWorkspace", payload["stderr"])
            self.assertNotIn(str(fake_lake), result_text)
            self.assertNotIn(str(temp_root), result_text)

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

    def test_resume_created_run_retries_after_precompile_agent_crash(self) -> None:
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
                agent=CrashBeforeFirstDraftAgent(),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )
            with self.assertRaisesRegex(RuntimeError, "simulated crash before first draft"):
                crashing_workflow.run(
                    source_path=source_path,
                    run_id="created-resume",
                    auto_approve=True,
                )

            manifest = crashing_workflow.status("created-resume")
            self.assertEqual(manifest.current_stage, RunStage.CREATED)
            self.assertEqual(manifest.attempt_count, 0)

            resumed_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )
            manifest = resumed_workflow.resume("created-resume", auto_approve=True)

            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(manifest.attempt_count, 2)

    def test_resume_after_missing_toolchain_retries_same_run(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        template_dir = project_root / "lean_workspace_template"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text(
                "For every natural number n, adding zero on the left gives back n.\n"
                "Target statement: 0 + n = n.\n",
                encoding="utf-8",
            )

            stalled_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path="missing-lake"),
            )
            manifest = stalled_workflow.run(
                source_path=source_path,
                run_id="stall-missing-toolchain",
                auto_approve=True,
            )
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_STALL_REVIEW)

            fake_lake = self._write_fake_lake(temp_root)
            resumed_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )
            manifest = resumed_workflow.resume(
                "stall-missing-toolchain",
                auto_approve=True,
            )

            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(manifest.attempt_count, 2)

    def test_retry_cap_requires_fresh_stall_approval(self) -> None:
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
                agent=RepairResumeAgent(),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
                max_attempts=1,
            )
            manifest = workflow.run(
                source_path=source_path,
                run_id="stall-retry-cap",
                auto_approve=True,
            )
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_STALL_REVIEW)
            self.assertEqual(manifest.attempt_count, 1)

            workflow.approve_stall("stall-retry-cap")
            manifest = workflow.resume("stall-retry-cap", auto_approve=True)

            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(manifest.attempt_count, 2)

    def test_rejected_final_decision_does_not_complete_run(self) -> None:
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

            manifest = workflow.run(source_path=source_path, run_id="reject-final", auto_approve=False)
            workflow.approve_spec("reject-final")
            manifest = workflow.resume("reject-final", auto_approve=False)
            workflow.approve_plan("reject-final")
            manifest = workflow.resume("reject-final", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_REVIEW)

            store = RunStore(temp_root / "artifacts", "reject-final")
            store.write_json(
                "08_final/decision.json",
                HumanDecision(approved=False, updated_at=utc_now(), notes="Needs changes."),
            )

            manifest = workflow.resume("reject-final", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_REVIEW)
            self.assertEqual(manifest.final_output_path, "08_final/final_candidate.lean")
            self.assertFalse(store.exists("08_final/final.lean"))

    def test_run_ids_must_be_safe_and_unique(self) -> None:
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

            with self.assertRaises(ValueError):
                workflow.run(source_path=source_path, run_id="../escape", auto_approve=True)

            workflow.run(source_path=source_path, run_id="safe-run", auto_approve=True)
            with self.assertRaises(FileExistsError):
                workflow.run(source_path=source_path, run_id="safe-run", auto_approve=True)

    def test_subprocess_agent_repair_loop_uses_external_provider(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        template_dir = project_root / "lean_workspace_template"
        provider_script = (
            project_root / "examples" / "providers" / "scripted_repair_provider.py"
        )
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
                agent=SubprocessFormalizationAgent(
                    [sys.executable, str(provider_script)]
                ),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )
            manifest = workflow.run(
                source_path=source_path,
                run_id="subprocess-demo",
                auto_approve=True,
            )

            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(manifest.attempt_count, 2)
            request_path = (
                temp_root
                / "artifacts"
                / "runs"
                / "subprocess-demo"
                / "05_draft"
                / "attempt_0002"
                / "request.json"
            )
            request = request_path.read_text(encoding="utf-8")
            self.assertIn('"previous_draft"', request)
            self.assertIn('"attempts_remaining"', request)

    def test_cli_build_agent_resolves_repo_relative_provider_path(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(
            agent_command="python3 examples/providers/scripted_repair_provider.py"
        )

        agent = build_agent(args, project_root)

        self.assertIsInstance(agent, SubprocessFormalizationAgent)
        self.assertEqual(agent.command[0], "python3")
        self.assertEqual(
            Path(agent.command[1]),
            project_root / "examples" / "providers" / "scripted_repair_provider.py",
        )
        self.assertEqual(agent.name, "subprocess:scripted_repair_provider.py")
        self.assertEqual(agent.working_directory, project_root)

    def test_cli_build_agent_preserves_python_module_invocation(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(agent_command="python3 -m examples")

        agent = build_agent(args, project_root)

        self.assertIsInstance(agent, SubprocessFormalizationAgent)
        self.assertEqual(agent.command, ["python3", "-m", "examples"])
        self.assertEqual(agent.name, "subprocess:examples")

    def test_cli_resolves_source_against_repo_root(self) -> None:
        project_root = Path(__file__).resolve().parents[1]

        self.assertEqual(
            _resolve_source_path(Path("examples/inputs/zero_add.md"), project_root),
            project_root / "examples" / "inputs" / "zero_add.md",
        )
