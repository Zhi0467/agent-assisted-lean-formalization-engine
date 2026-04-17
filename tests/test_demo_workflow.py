from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from lean_formalization_engine.demo_agent import DemoFormalizationAgent
from lean_formalization_engine.lean_runner import LeanRunner
from lean_formalization_engine.models import (
    AgentConfig,
    AgentTurn,
    BackendStage,
    CompileAttempt,
    RunManifest,
    RunStage,
    SourceKind,
    SourceRef,
    StageRequest,
)
from lean_formalization_engine.storage import RunStore
from lean_formalization_engine.subprocess_agent import SubprocessFormalizationAgent
from lean_formalization_engine.workflow import FormalizationWorkflow


class ContentCheckingLeanRunner:
    def __init__(self) -> None:
        self.attempts: list[int] = []
        self.template_dir = Path("/tmp/unused-template")
        self.lake_path: str | None = None

    def compile_candidate(self, store: RunStore, candidate_relative_path: str, attempt: int) -> CompileAttempt:
        self.attempts.append(attempt)
        content = store.read_text(candidate_relative_path)
        contains_sorry = "sorry" in content
        passed = not contains_sorry
        return CompileAttempt(
            attempt=attempt,
            command=["lake build FormalizationEngineWorkspace"],
            stdout="" if contains_sorry else "ok",
            stderr="found sorry" if contains_sorry else "",
            returncode=1 if contains_sorry else 0,
            diagnostics=["found sorry"] if contains_sorry else [],
            fast_check_passed=passed,
            build_passed=passed,
            contains_sorry=contains_sorry,
            missing_toolchain=False,
            quality_gate_passed=not contains_sorry,
            passed=passed,
            status="compile_failed" if contains_sorry else "passed",
        )


class RecordingRepairAgent:
    name = "recording_repair_agent"

    def __init__(self) -> None:
        self.requests: list[StageRequest] = []

    def run_stage(self, request: StageRequest) -> AgentTurn:
        self.requests.append(request)
        output_dir = Path(request.repo_root) / request.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        if request.stage == BackendStage.ENRICHMENT:
            content = "# Enrichment Handoff\n\nSelf-contained over Nat.\n"
            (output_dir / "handoff.md").write_text(content, encoding="utf-8")
        elif request.stage == BackendStage.PLAN:
            content = "\n".join(
                [
                    "# Plan Handoff",
                    "",
                    "Proposed theorem name: `recorded_zero_add`",
                    "Target statement: `theorem recorded_zero_add (n : Nat) : 0 + n = n`",
                    "Proof route: use `Nat.zero_add`.",
                    "",
                ]
            )
            (output_dir / "handoff.md").write_text(content, encoding="utf-8")
        elif request.stage == BackendStage.PROOF:
            proof_retry = request.review_notes_path is not None and request.review_notes_path.endswith(
                "03_proof/review.md"
            )
            if not proof_retry:
                content = "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem recorded_zero_add (n : Nat) : 0 + n = n := by",
                        "  sorry",
                        "",
                    ]
                )
            else:
                content = "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem recorded_zero_add (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                )
            (output_dir / "candidate.lean").write_text(content, encoding="utf-8")
        else:
            raise ValueError(f"Unsupported stage {request.stage.value}")

        return AgentTurn(
            request_payload={"stage": request.stage.value},
            prompt=f"{request.stage.value} prompt",
            raw_response=f"{request.stage.value} response",
        )


class AlwaysSorryAgent:
    name = "always_sorry_agent"

    def run_stage(self, request: StageRequest) -> AgentTurn:
        output_dir = Path(request.repo_root) / request.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        if request.stage == BackendStage.ENRICHMENT:
            (output_dir / "handoff.md").write_text("# Enrichment Handoff\n\nStill scoped over Nat.\n", encoding="utf-8")
        elif request.stage == BackendStage.PLAN:
            (output_dir / "handoff.md").write_text(
                "\n".join(
                    [
                        "# Plan Handoff",
                        "",
                        "Target statement: `theorem stuck_zero_add (n : Nat) : 0 + n = n`",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        elif request.stage == BackendStage.PROOF:
            (output_dir / "candidate.lean").write_text(
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem stuck_zero_add (n : Nat) : 0 + n = n := by",
                        "  sorry",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        else:
            raise ValueError(f"Unsupported stage {request.stage.value}")

        return AgentTurn(
            request_payload={"stage": request.stage.value},
            prompt=f"{request.stage.value} prompt",
            raw_response=f"{request.stage.value} response",
        )


class BrokenAgent:
    name = "broken_agent"

    def run_stage(self, request: StageRequest) -> AgentTurn:
        return AgentTurn(request_payload={"stage": request.stage.value}, prompt="broken", raw_response="broken")


class DemoWorkflowTest(unittest.TestCase):
    def _write_review(self, run_root: Path, stage_dir: str, decision: str, notes: str) -> None:
        (run_root / stage_dir / "review.md").write_text(
            "\n".join(
                [
                    f"# {stage_dir}",
                    "",
                    f"decision: {decision}",
                    "",
                    "Notes:",
                    notes,
                    "",
                ]
            ),
            encoding="utf-8",
        )

    def _write_fake_lake(self, directory: Path) -> Path:
        fake_lake = directory / "lake"
        workspace_template = (
            Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
        )
        fake_lake.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import pathlib",
                    "import shutil",
                    "import sys",
                    "",
                    f"WORKSPACE_TEMPLATE = pathlib.Path({str(workspace_template)!r})",
                    "",
                    "def main() -> int:",
                    "    args = sys.argv[1:]",
                    "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                    "        generated = pathlib.Path.cwd() / 'FormalizationEngineWorkspace' / 'Generated.lean'",
                    "        content = generated.read_text(encoding='utf-8')",
                    "        if 'sorry' in content:",
                    "            print('found sorry', file=sys.stderr)",
                    "            return 1",
                    "        return 0",
                    "    if args[:3] == ['new', 'lean_workspace_template', 'math']:",
                    "        target = pathlib.Path.cwd() / 'lean_workspace_template'",
                    "        if target.exists():",
                    "            shutil.rmtree(target)",
                    "        shutil.copytree(WORKSPACE_TEMPLATE, target)",
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

    def test_demo_workflow_completes_without_old_payload_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.prove(source_path=source_path, run_id="demo-test", auto_approve=True)

            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(manifest.final_output_path, "04_final/final.lean")
            run_root = temp_root / "artifacts" / "runs" / "demo-test"
            self.assertTrue((run_root / "01_enrichment" / "handoff.md").exists())
            self.assertTrue((run_root / "02_plan" / "handoff.md").exists())
            self.assertFalse((run_root / "01_enrichment" / "enrichment_report.json").exists())
            self.assertFalse((run_root / "02_plan" / "formalization_plan.json").exists())

    def test_manual_review_path_uses_review_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, n + 0 = n.\n", encoding="utf-8")

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.prove(source_path=source_path, run_id="manual-demo", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            run_root = temp_root / "artifacts" / "runs" / "manual-demo"
            self.assertTrue((run_root / "01_enrichment" / "checkpoint.md").exists())
            self.assertTrue((run_root / "01_enrichment" / "review.md").exists())

            self._write_review(
                run_root,
                "01_enrichment",
                "approve",
                "The theorem is ready for planning.",
            )
            manifest = workflow.resume("manual-demo", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)

            self._write_review(
                run_root,
                "02_plan",
                "approve",
                "The theorem statement and proof route are correct.",
            )
            manifest = workflow.resume("manual-demo", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_APPROVAL)

            self._write_review(
                run_root,
                "04_final",
                "approve",
                "The compiling Lean file is acceptable.",
            )
            manifest = workflow.resume("manual-demo", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)

    def test_resume_rejects_backend_switch_for_paused_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.prove(source_path=source_path, run_id="stable-backend", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            provider_script = Path(__file__).resolve().parents[1] / "examples" / "providers" / "scripted_repair_provider.py"
            command = [sys.executable, str(provider_script)]
            wrong_backend_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=SubprocessFormalizationAgent(command),
                agent_config=AgentConfig(backend="command", command=command),
                lean_runner=ContentCheckingLeanRunner(),
            )

            with self.assertRaisesRegex(ValueError, "keep the backend recorded in the manifest"):
                wrong_backend_workflow.resume("stable-backend", auto_approve=False)

            manifest = workflow.status("stable-backend")
            self.assertEqual(manifest.agent_config.backend, "demo")

    def test_resume_keeps_packaged_template_after_missing_lake_stall(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()

            blocked_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(temp_root / "lean_workspace_template", lake_path="missing-lake"),
            )
            manifest = blocked_workflow.prove(source_path=source_path, run_id="stall-demo", auto_approve=True)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(Path(manifest.template_dir), packaged_template)

            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            fake_lake = self._write_fake_lake(temp_root)

            resumed_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(Path(manifest.template_dir), lake_path=str(fake_lake)),
            )
            manifest = resumed_workflow.resume("stall-demo", auto_approve=True)
            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(Path(manifest.template_dir), packaged_template)

    def test_resume_reuses_existing_plan_handoff_after_enrichment_approval(self) -> None:
        class PlanCountingAgent:
            name = "plan_counting_agent"

            def __init__(self) -> None:
                self.plan_calls = 0

            def run_stage(self, request: StageRequest) -> AgentTurn:
                if request.stage == BackendStage.PLAN:
                    self.plan_calls += 1
                raise AssertionError("Resume should reuse the existing plan handoff instead of rerunning the backend.")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "reused-plan"
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "01_enrichment").mkdir(parents=True, exist_ok=True)
            (run_root / "02_plan").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text(
                "For every natural number n, 0 + n = n.\n",
                encoding="utf-8",
            )
            (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")
            (run_root / "01_enrichment" / "review.md").write_text(
                "# Enrichment Review\n\ndecision: approve\n\nNotes:\n\n",
                encoding="utf-8",
            )
            (run_root / "02_plan" / "handoff.md").write_text("# Existing Plan Handoff\n", encoding="utf-8")
            (run_root / "02_plan" / "request.json").write_text('{"stage": "plan"}', encoding="utf-8")
            (run_root / "02_plan" / "prompt.md").write_text("plan prompt", encoding="utf-8")
            (run_root / "02_plan" / "response.txt").write_text("plan response", encoding="utf-8")
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "reused-plan",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "plan_counting_agent",
                        "agent_config": {"backend": "demo"},
                        "template_dir": str((temp_root / "lean_workspace_template").resolve()),
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_enrichment_approval",
                        "attempt_count": 0,
                    }
                ),
                encoding="utf-8",
            )

            agent = PlanCountingAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.resume("reused-plan", auto_approve=False)

            self.assertEqual(agent.plan_calls, 0)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)
            self.assertEqual((run_root / "02_plan" / "handoff.md").read_text(encoding="utf-8"), "# Existing Plan Handoff\n")
            self.assertTrue((run_root / "02_plan" / "checkpoint.md").exists())
            self.assertTrue((run_root / "02_plan" / "review.md").exists())

    def test_resume_reruns_orphaned_plan_turn(self) -> None:
        class FailingPlanAgent:
            name = "failing_plan_agent"

            def __init__(self) -> None:
                self.plan_calls = 0

            def run_stage(self, request: StageRequest) -> AgentTurn:
                output_dir = Path(request.repo_root) / request.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                if request.stage == BackendStage.ENRICHMENT:
                    (output_dir / "handoff.md").write_text("# Enrichment Handoff\n", encoding="utf-8")
                    return AgentTurn({"stage": "enrichment"}, "enrichment prompt", "enrichment response")
                if request.stage == BackendStage.PLAN:
                    self.plan_calls += 1
                    (output_dir / "handoff.md").write_text("# Plan Handoff\n", encoding="utf-8")
                    raise ValueError("plan serialization failed")
                raise AssertionError("Proof should not run while the plan turn is still failing.")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            agent = FailingPlanAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )

            with self.assertRaisesRegex(ValueError, "plan serialization failed"):
                workflow.prove(source_path=source_path, run_id="plan-failure", auto_approve=True)
            self.assertEqual(agent.plan_calls, 1)

            with self.assertRaisesRegex(ValueError, "plan serialization failed"):
                workflow.resume("plan-failure", auto_approve=False)
            self.assertEqual(agent.plan_calls, 2)
            self.assertFalse(
                (temp_root / "artifacts" / "runs" / "plan-failure" / "03_proof" / "attempts" / "attempt_0001").exists()
            )

    def test_resume_reruns_orphaned_proof_turn(self) -> None:
        class FailingProofAgent:
            name = "failing_proof_agent"

            def __init__(self) -> None:
                self.proof_calls = 0

            def run_stage(self, request: StageRequest) -> AgentTurn:
                output_dir = Path(request.repo_root) / request.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                if request.stage == BackendStage.ENRICHMENT:
                    (output_dir / "handoff.md").write_text("# Enrichment Handoff\n", encoding="utf-8")
                    return AgentTurn({"stage": "enrichment"}, "enrichment prompt", "enrichment response")
                if request.stage == BackendStage.PLAN:
                    (output_dir / "handoff.md").write_text("# Plan Handoff\n", encoding="utf-8")
                    return AgentTurn({"stage": "plan"}, "plan prompt", "plan response")
                self.proof_calls += 1
                (output_dir / "candidate.lean").write_text(
                    "\n".join(
                        [
                            "import FormalizationEngineWorkspace.Basic",
                            "",
                            "theorem failed_proof (n : Nat) : 0 + n = n := by",
                            "  sorry",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                raise ValueError("proof serialization failed")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            agent = FailingProofAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )

            with self.assertRaisesRegex(ValueError, "proof serialization failed"):
                workflow.prove(source_path=source_path, run_id="proof-failure", auto_approve=True)
            self.assertEqual(agent.proof_calls, 1)
            run_root = temp_root / "artifacts" / "runs" / "proof-failure"
            self.assertFalse((run_root / "03_proof" / "attempts" / "attempt_0001" / "request.json").exists())

            with self.assertRaisesRegex(ValueError, "proof serialization failed"):
                workflow.resume("proof-failure", auto_approve=False)
            self.assertEqual(agent.proof_calls, 2)
            self.assertFalse((run_root / "03_proof" / "attempts" / "attempt_0001" / "compile_result.json").exists())

    def test_resume_clears_stale_candidate_before_rerunning_proof_turn(self) -> None:
        class CrashingProofAgent:
            name = "crashing_proof_agent"

            def run_stage(self, request: StageRequest) -> AgentTurn:
                output_dir = Path(request.repo_root) / request.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                if request.stage == BackendStage.ENRICHMENT:
                    (output_dir / "handoff.md").write_text("# Enrichment Handoff\n", encoding="utf-8")
                    return AgentTurn({"stage": "enrichment"}, "enrichment prompt", "enrichment response")
                if request.stage == BackendStage.PLAN:
                    (output_dir / "handoff.md").write_text("# Plan Handoff\n", encoding="utf-8")
                    return AgentTurn({"stage": "plan"}, "plan prompt", "plan response")
                (output_dir / "candidate.lean").write_text(
                    "\n".join(
                        [
                            "import FormalizationEngineWorkspace.Basic",
                            "",
                            "theorem failed_proof (n : Nat) : 0 + n = n := by",
                            "  sorry",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                raise ValueError("proof serialization failed")

        class MissingCandidateAgent:
            name = "missing_candidate_agent"

            def run_stage(self, request: StageRequest) -> AgentTurn:
                output_dir = Path(request.repo_root) / request.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                if request.stage == BackendStage.ENRICHMENT:
                    (output_dir / "handoff.md").write_text("# Enrichment Handoff\n", encoding="utf-8")
                elif request.stage == BackendStage.PLAN:
                    (output_dir / "handoff.md").write_text("# Plan Handoff\n", encoding="utf-8")
                return AgentTurn({"stage": request.stage.value}, f"{request.stage.value} prompt", f"{request.stage.value} response")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            crashing_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=CrashingProofAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )

            with self.assertRaisesRegex(ValueError, "proof serialization failed"):
                crashing_workflow.prove(source_path=source_path, run_id="proof-stale", auto_approve=True)

            recovery_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=MissingCandidateAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            with self.assertRaisesRegex(RuntimeError, "attempt_0001/candidate.lean"):
                recovery_workflow.resume("proof-stale", auto_approve=False)

            run_root = temp_root / "artifacts" / "runs" / "proof-stale"
            manifest = recovery_workflow.status("proof-stale")
            self.assertEqual(manifest.attempt_count, 0)
            self.assertFalse((run_root / "03_proof" / "attempts" / "attempt_0001" / "candidate.lean").exists())
            self.assertFalse((run_root / "03_proof" / "attempts" / "attempt_0001" / "compile_result.json").exists())
            self.assertFalse((run_root / "03_proof" / "attempts" / "attempt_0002").exists())

    def test_command_backend_repairs_after_sorry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            provider_script = Path(__file__).resolve().parents[1] / "examples" / "providers" / "scripted_repair_provider.py"
            command = [sys.executable, str(provider_script)]

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=SubprocessFormalizationAgent(command),
                agent_config=AgentConfig(backend="command", command=command),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.prove(source_path=source_path, run_id="command-demo", auto_approve=True)
            run_root = temp_root / "artifacts" / "runs" / "command-demo"

            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(manifest.attempt_count, 2)
            first_attempt = json.loads(
                (run_root / "03_proof" / "attempts" / "attempt_0001" / "compile_result.json").read_text(
                    encoding="utf-8"
                )
            )
            second_attempt = json.loads(
                (run_root / "03_proof" / "attempts" / "attempt_0002" / "compile_result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(first_attempt["contains_sorry"])
            self.assertEqual(first_attempt["status"], "compile_failed")
            self.assertTrue(second_attempt["passed"])

    def test_stage_requests_use_file_paths_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            agent = RecordingRepairAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.prove(source_path=source_path, run_id="recording", auto_approve=False)
            run_root = temp_root / "artifacts" / "runs" / "recording"
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            self._write_review(run_root, "01_enrichment", "approve", "Scope looks right.")
            manifest = workflow.resume("recording", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)

            self._write_review(run_root, "02_plan", "approve", "Start proving.")
            manifest = workflow.resume("recording", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)

            self._write_review(run_root, "03_proof", "retry", "One more attempt.")
            manifest = workflow.resume("recording", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_APPROVAL)

            self.assertEqual(agent.requests[0].stage, BackendStage.ENRICHMENT)
            self.assertEqual(
                set(agent.requests[0].input_paths),
                {"normalized_source", "provenance", "source"},
            )
            self.assertIsNone(agent.requests[0].review_notes_path)

            self.assertEqual(agent.requests[1].stage, BackendStage.PLAN)
            self.assertIn("enrichment_handoff", agent.requests[1].input_paths)
            self.assertIn("enrichment_review", agent.requests[1].input_paths)
            self.assertTrue(agent.requests[1].review_notes_path.endswith("01_enrichment/review.md"))
            self.assertNotIn("extraction", agent.requests[1].input_paths)
            self.assertNotIn("theorem_spec", agent.requests[1].input_paths)

            first_proof = agent.requests[2]
            self.assertEqual(first_proof.stage, BackendStage.PROOF)
            self.assertIn("plan_handoff", first_proof.input_paths)
            self.assertIn("plan_review", first_proof.input_paths)
            self.assertTrue(first_proof.review_notes_path.endswith("02_plan/review.md"))
            self.assertNotIn("plan", first_proof.input_paths)

            retry_proof = agent.requests[-1]
            self.assertEqual(retry_proof.stage, BackendStage.PROOF)
            self.assertIn("previous_compile_result", retry_proof.input_paths)
            self.assertIn("previous_candidate", retry_proof.input_paths)
            self.assertTrue(retry_proof.review_notes_path.endswith("03_proof/review.md"))

    def test_retry_review_file_resets_after_consumption(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=AlwaysSorryAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
                max_attempts=1,
            )
            manifest = workflow.prove(source_path=source_path, run_id="stale-retry", auto_approve=False)
            run_root = temp_root / "artifacts" / "runs" / "stale-retry"
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            self._write_review(run_root, "01_enrichment", "approve", "Scope is fixed.")
            manifest = workflow.resume("stale-retry", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)

            self._write_review(run_root, "02_plan", "approve", "Try once.")
            manifest = workflow.resume("stale-retry", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 1)

            self._write_review(run_root, "03_proof", "retry", "Try one more attempt.")
            manifest = workflow.resume("stale-retry", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 2)

            review_text = (run_root / "03_proof" / "review.md").read_text(encoding="utf-8")
            self.assertIn("decision: pending", review_text)
            self.assertNotIn("decision: retry", review_text)

            manifest = workflow.resume("stale-retry", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 2)

    def test_stage_requests_fall_back_to_legacy_normalized_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RecordingRepairAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            store = RunStore(temp_root / "artifacts", "legacy-normalized")
            store.ensure_new()
            store.write_text("00_input/source.txt", "For every natural number n, 0 + n = n.\n")
            store.write_json("00_input/provenance.json", {})
            store.write_text("01_normalized/normalized.md", "For every natural number n, 0 + n = n.\n")

            manifest = RunManifest(
                run_id="legacy-normalized",
                source=SourceRef(path="input.md", kind=SourceKind.MARKDOWN),
                agent_name="recording_repair_agent",
                agent_config=AgentConfig(backend="demo"),
                template_dir=str((temp_root / "lean_workspace_template").resolve()),
                created_at="2026-04-16T00:00:00Z",
                updated_at="2026-04-16T00:00:00Z",
                current_stage=RunStage.CREATED,
            )

            request = workflow._build_stage_request(
                store,
                manifest,
                stage=BackendStage.ENRICHMENT,
                output_dir="01_enrichment",
                required_outputs=["handoff.md"],
            )

            self.assertTrue(request.input_paths["normalized_source"].endswith("01_normalized/normalized.md"))

    def test_auto_approve_does_not_advertise_missing_review_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            agent = RecordingRepairAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            workflow.prove(source_path=source_path, run_id="auto-approve", auto_approve=True)

            plan_request = agent.requests[1]
            first_proof_request = agent.requests[2]
            self.assertNotIn("enrichment_review", plan_request.input_paths)
            self.assertIsNone(plan_request.review_notes_path)
            self.assertNotIn("plan_review", first_proof_request.input_paths)
            self.assertIsNone(first_proof_request.review_notes_path)

    def test_auto_approve_resume_does_not_pass_pending_review_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            agent = RecordingRepairAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
                max_attempts=1,
            )

            manifest = workflow.prove(source_path=source_path, run_id="auto-approve-resume", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            manifest = workflow.resume("auto-approve-resume", auto_approve=True)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)

            plan_request = agent.requests[1]
            proof_request = agent.requests[2]
            self.assertNotIn("enrichment_review", plan_request.input_paths)
            self.assertIsNone(plan_request.review_notes_path)
            self.assertNotIn("plan_review", proof_request.input_paths)
            self.assertIsNone(proof_request.review_notes_path)

    def test_legacy_auto_approve_does_not_pass_pending_enrichment_review_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-enrichment-auto"
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "03_enrichment").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")
            (run_root / "03_enrichment" / "enrichment_report.approved.json").write_text("{}", encoding="utf-8")
            (run_root / "03_enrichment" / "review.md").write_text(
                "# Legacy Enrichment Review\n\ndecision: pending\n\nNotes:\n\n",
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-enrichment-auto",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "recording_repair_agent",
                        "agent_config": {"backend": "demo"},
                        "template_dir": str((temp_root / "lean_workspace_template").resolve()),
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_enrichment_review",
                        "attempt_count": 0,
                    }
                ),
                encoding="utf-8",
            )

            agent = RecordingRepairAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
                max_attempts=0,
            )
            manifest = workflow.resume("legacy-enrichment-auto", auto_approve=True)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)

            plan_request = agent.requests[0]
            self.assertNotIn("legacy_enrichment_review", plan_request.input_paths)
            self.assertIsNone(plan_request.review_notes_path)

    def test_legacy_auto_approve_does_not_pass_pending_plan_review_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-plan-auto"
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "06_plan").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")
            (run_root / "06_plan" / "formalization_plan.approved.json").write_text("{}", encoding="utf-8")
            (run_root / "06_plan" / "review.md").write_text(
                "# Legacy Plan Review\n\ndecision: pending\n\nNotes:\n\n",
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-plan-auto",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "recording_repair_agent",
                        "agent_config": {"backend": "demo"},
                        "template_dir": str((temp_root / "lean_workspace_template").resolve()),
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_plan_review",
                        "attempt_count": 0,
                    }
                ),
                encoding="utf-8",
            )

            agent = RecordingRepairAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
                max_attempts=1,
            )
            manifest = workflow.resume("legacy-plan-auto", auto_approve=True)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)

            proof_request = agent.requests[0]
            self.assertNotIn("legacy_plan_review", proof_request.input_paths)
            self.assertIsNone(proof_request.review_notes_path)

    def test_legacy_spec_review_stays_legacy_until_plan_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-spec"
            (run_root / "04_spec").mkdir(parents=True, exist_ok=True)
            (run_root / "03_enrichment").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")
            (run_root / "03_enrichment" / "enrichment_report.approved.json").write_text("{}", encoding="utf-8")
            (run_root / "04_spec" / "theorem_spec.approved.json").write_text(
                json.dumps({"title": "Legacy spec", "conclusion": "0 + n = n"}),
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-spec",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "recording_repair_agent",
                        "agent_config": {"backend": "demo"},
                        "template_dir": str((temp_root / "lean_workspace_template").resolve()),
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_spec_review",
                        "attempt_count": 0,
                    }
                ),
                encoding="utf-8",
            )

            agent = RecordingRepairAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )

            manifest = workflow.status("legacy-spec")
            self.assertEqual(manifest.current_stage, RunStage.LEGACY_AWAITING_SPEC_REVIEW)

            manifest = workflow.resume("legacy-spec", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.LEGACY_AWAITING_SPEC_REVIEW)
            self.assertTrue((run_root / "04_spec" / "checkpoint.md").exists())
            self.assertTrue((run_root / "04_spec" / "review.md").exists())

            self._write_review(run_root, "04_spec", "approve", "Use the approved legacy spec.")
            manifest = workflow.resume("legacy-spec", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)
            self.assertTrue((run_root / "02_plan" / "handoff.md").exists())
            self.assertIn("legacy_spec", agent.requests[0].input_paths)
            self.assertTrue(agent.requests[0].review_notes_path.endswith("04_spec/review.md"))

    def test_legacy_reject_review_is_not_overwritten_on_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-reject"
            (run_root / "04_spec").mkdir(parents=True, exist_ok=True)
            (run_root / "04_spec" / "theorem_spec.json").write_text("{}", encoding="utf-8")
            original_review = "\n".join(
                [
                    "# Legacy Spec Review",
                    "",
                    "decision: reject",
                    "",
                    "Notes:",
                    "keep these notes",
                    "",
                ]
            )
            (run_root / "04_spec" / "review.md").write_text(original_review, encoding="utf-8")
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-reject",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "demo_zero_add_agent",
                        "agent_config": {"backend": "demo"},
                        "template_dir": str((temp_root / "lean_workspace_template").resolve()),
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_spec_review",
                        "attempt_count": 0,
                    }
                ),
                encoding="utf-8",
            )

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.resume("legacy-reject", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.LEGACY_AWAITING_SPEC_REVIEW)
            self.assertEqual((run_root / "04_spec" / "review.md").read_text(encoding="utf-8"), original_review)

    def test_legacy_stall_retry_carries_forward_previous_compile_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-stall"
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "06_plan").mkdir(parents=True, exist_ok=True)
            (run_root / "09_review").mkdir(parents=True, exist_ok=True)
            (run_root / "07_draft" / "attempt_0001").mkdir(parents=True, exist_ok=True)
            (run_root / "08_compile" / "attempt_0001").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")
            (run_root / "06_plan" / "formalization_plan.approved.json").write_text("{}", encoding="utf-8")
            (run_root / "09_review" / "review.md").write_text(
                "# Legacy Proof Stall Review\n\ndecision: retry\n\nNotes:\ntry again\n",
                encoding="utf-8",
            )
            (run_root / "07_draft" / "attempt_0001" / "draft.lean").write_text("theorem x : True := by\n  sorry\n", encoding="utf-8")
            (run_root / "08_compile" / "attempt_0001" / "result.json").write_text('{"status":"compile_failed"}', encoding="utf-8")
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-stall",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "recording_repair_agent",
                        "agent_config": {"backend": "demo"},
                        "template_dir": str((temp_root / "lean_workspace_template").resolve()),
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_stall_review",
                        "attempt_count": 1,
                    }
                ),
                encoding="utf-8",
            )

            agent = RecordingRepairAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.resume("legacy-stall", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)

            proof_request = agent.requests[0]
            self.assertEqual(proof_request.stage, BackendStage.PROOF)
            self.assertIn("legacy_previous_compile_result", proof_request.input_paths)
            self.assertIn("legacy_previous_candidate", proof_request.input_paths)
            self.assertTrue(proof_request.latest_compile_result_path.endswith("08_compile/attempt_0001/result.json"))

    def test_resume_queues_final_review_after_successful_compile_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            runner = ContentCheckingLeanRunner()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=runner,
            )
            workflow.prove(source_path=source_path, run_id="proof-crash", auto_approve=False)
            run_root = temp_root / "artifacts" / "runs" / "proof-crash"
            self._write_review(run_root, "01_enrichment", "approve", "")
            workflow.resume("proof-crash", auto_approve=False)
            self._write_review(run_root, "02_plan", "approve", "")

            store = RunStore(temp_root / "artifacts", "proof-crash")
            manifest = workflow.status("proof-crash")
            request = workflow._build_stage_request(
                store,
                manifest,
                stage=BackendStage.PROOF,
                output_dir="03_proof/attempts/attempt_0001",
                required_outputs=["candidate.lean"],
                review_notes_relative_path="02_plan/review.md",
                attempt=1,
                max_attempts=3,
            )
            workflow._run_backend_stage(store, request, "03_proof/attempts/attempt_0001")
            compile_result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            workflow._write_compile_result(store, 1, compile_result)
            manifest.current_stage = RunStage.PROVING
            manifest.attempt_count = 1
            manifest.latest_error = None
            workflow._save_manifest(store, manifest)

            manifest = workflow.resume("proof-crash", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_APPROVAL)
            self.assertEqual(manifest.attempt_count, 1)
            self.assertTrue((run_root / "04_final" / "final_candidate.lean").exists())

    def test_missing_required_output_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=BrokenAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            with self.assertRaisesRegex(RuntimeError, "required Terry output"):
                workflow.prove(source_path=source_path, run_id="broken", auto_approve=False)

    def test_cli_demo_backend_e2e(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            fake_lake = self._write_fake_lake(temp_root)

            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            command = [
                sys.executable,
                "-m",
                "lean_formalization_engine",
                "--repo-root",
                str(temp_root),
                "--lake-path",
                str(fake_lake),
                "prove",
                str(source_path),
                "--run-id",
                "cli-demo",
                "--agent-backend",
                "demo",
                "--auto-approve",
            ]
            result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Stage: completed", result.stdout)
            self.assertTrue((temp_root / "artifacts" / "runs" / "cli-demo" / "04_final" / "final.lean").exists())

    def test_cli_command_backend_e2e(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            fake_lake = self._write_fake_lake(temp_root)
            provider_script = Path(__file__).resolve().parents[1] / "examples" / "providers" / "scripted_repair_provider.py"

            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            command = [
                sys.executable,
                "-m",
                "lean_formalization_engine",
                "--repo-root",
                str(temp_root),
                "--lake-path",
                str(fake_lake),
                "prove",
                str(source_path),
                "--run-id",
                "cli-command",
                "--agent-backend",
                "command",
                "--agent-command",
                f"{sys.executable} {provider_script}",
                "--auto-approve",
            ]
            result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Attempts: 2", result.stdout)
            self.assertTrue((temp_root / "artifacts" / "runs" / "cli-command" / "04_final" / "final.lean").exists())
