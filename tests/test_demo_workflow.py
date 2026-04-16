from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lean_formalization_engine.demo_agent import DemoFormalizationAgent
from lean_formalization_engine.lean_runner import LeanRunner
from lean_formalization_engine.models import (
    AgentConfig,
    AgentTurn,
    CompileAttempt,
    ContextPack,
    EnrichmentReport,
    FormalizationPlan,
    LeanDraft,
    RepairContext,
    RunStage,
    SourceRef,
    TheoremExtraction,
)
from lean_formalization_engine.storage import RunStore
from lean_formalization_engine.workflow import FormalizationWorkflow


class RepairResumeAgent:
    name = "repair_resume_agent"

    def draft_theorem_extraction(
        self,
        source_ref: SourceRef,
        source_text: str,
        normalized_text: str,
    ) -> tuple[TheoremExtraction, AgentTurn]:
        extraction = TheoremExtraction(
            title="Zero add",
            informal_statement=normalized_text.strip(),
            definitions=["Nat"],
            lemmas=["Nat.zero_add"],
            propositions=[],
            dependencies=["Nat.zero_add"],
            notes=[],
        )
        return extraction, AgentTurn(request_payload={}, prompt="extraction", raw_response="extraction")

    def draft_theorem_enrichment(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        extraction_markdown: str,
    ) -> tuple[EnrichmentReport, AgentTurn]:
        enrichment = EnrichmentReport(
            self_contained=True,
            satisfied_prerequisites=["Nat.zero_add exists."],
            missing_prerequisites=[],
            required_plan_additions=[],
            recommended_scope="Keep the theorem over Nat.",
            difficulty_assessment="easy",
            open_questions=[],
            next_steps=["Approve enrichment."],
            human_handoff="Everything needed is already present.",
        )
        return enrichment, AgentTurn(request_payload={}, prompt="enrichment", raw_response="enrichment")

    def draft_formalization_plan(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        enrichment: EnrichmentReport,
        context_pack: ContextPack,
    ) -> tuple[FormalizationPlan, AgentTurn]:
        plan = FormalizationPlan(
            title="Zero add",
            informal_statement=extraction.informal_statement,
            assumptions=["n : Nat"],
            conclusion="0 + n = n",
            symbols=["0", "+", "Nat"],
            ambiguities=[],
            paraphrase="Zero on the left does not change a natural number.",
            theorem_name="zero_add_resume",
            imports=["FormalizationEngineWorkspace.Basic"],
            prerequisites_to_formalize=[],
            helper_definitions=[],
            target_statement="theorem zero_add_resume (n : Nat) : 0 + n = n",
            proof_sketch=["Use the existing `Nat.zero_add` lemma."],
            human_summary="The theorem stays exactly over Nat and uses Nat.zero_add.",
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


class SequencedLeanRunner:
    def __init__(self, outcomes: list[str]):
        self.outcomes = outcomes
        self.attempts: list[int] = []
        self.template_dir = Path("/tmp/legacy-template")

    def compile_draft(self, store: RunStore, draft: LeanDraft, attempt: int) -> CompileAttempt:
        self.attempts.append(attempt)
        outcome = self.outcomes[attempt - 1]
        contains_sorry = "sorry" in draft.content
        diagnostics = [outcome.replace("_", " ")]

        if outcome == "missing_toolchain":
            return CompileAttempt(
                attempt=attempt,
                command=["lake build FormalizationEngineWorkspace"],
                stdout="",
                stderr="lake missing",
                returncode=127,
                diagnostics=diagnostics,
                fast_check_passed=False,
                build_passed=False,
                contains_sorry=contains_sorry,
                missing_toolchain=True,
                quality_gate_passed=not contains_sorry,
                passed=False,
                status="toolchain_missing",
            )

        if outcome == "passed":
            return CompileAttempt(
                attempt=attempt,
                command=["lake build FormalizationEngineWorkspace"],
                stdout="ok",
                stderr="",
                returncode=0,
                diagnostics=[],
                fast_check_passed=True,
                build_passed=True,
                contains_sorry=contains_sorry,
                missing_toolchain=False,
                quality_gate_passed=not contains_sorry,
                passed=not contains_sorry,
                status="passed" if not contains_sorry else "compile_failed",
            )

        return CompileAttempt(
            attempt=attempt,
            command=["lake build FormalizationEngineWorkspace"],
            stdout="",
            stderr="compile failed",
            returncode=1,
            diagnostics=diagnostics,
            fast_check_passed=False,
            build_passed=False,
            contains_sorry=contains_sorry,
            missing_toolchain=False,
            quality_gate_passed=not contains_sorry,
            passed=False,
            status="compile_failed",
        )


class DemoWorkflowTest(unittest.TestCase):
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
                    "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                    "        generated = pathlib.Path.cwd() / 'FormalizationEngineWorkspace' / 'Generated.lean'",
                    "        content = generated.read_text(encoding='utf-8')",
                    "        if 'sorry' in content:",
                    "            print('found sorry', file=sys.stderr)",
                    "            return 1",
                    "        return 0",
                    "    if args[:3] == ['new', 'lean_workspace_template', 'math']:",
                    "        target = pathlib.Path.cwd() / 'lean_workspace_template'",
                    "        target.mkdir(parents=True, exist_ok=True)",
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
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )
            manifest = workflow.prove(source_path=source_path, run_id="demo-test", auto_approve=True)

            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(manifest.final_output_path, "04_final/final.lean")
            final_output = temp_root / "artifacts" / "runs" / "demo-test" / "04_final" / "final.lean"
            self.assertTrue(final_output.exists())
            self.assertIn("zero_add_demo", final_output.read_text(encoding="utf-8"))

    def test_manual_review_path_uses_review_files(self) -> None:
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
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )

            manifest = workflow.prove(source_path=source_path, run_id="manual-review", auto_approve=False)
            run_root = temp_root / "artifacts" / "runs" / "manual-review"
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)
            self.assertTrue((run_root / "01_enrichment" / "checkpoint.md").exists())
            self.assertTrue((run_root / "01_enrichment" / "review.md").exists())

            self._write_review(run_root, "01_enrichment", "approve", "Scope and prerequisites look right.")
            manifest = workflow.resume("manual-review", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)

            self._write_review(run_root, "02_plan", "approve", "The theorem statement and proof route are right.")
            manifest = workflow.resume("manual-review", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_APPROVAL)

            self._write_review(run_root, "04_final", "approve", "The compiling Lean file matches the plan.")
            manifest = workflow.resume("manual-review", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)

    def test_proof_blocked_requires_retry_decision(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        template_dir = project_root / "lean_workspace_template"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            fake_lake = self._write_fake_lake(temp_root)
            source_path = temp_root / "input.md"
            source_path.write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
                max_attempts=1,
            )

            manifest = workflow.prove(source_path=source_path, run_id="proof-blocked", auto_approve=True)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            run_root = temp_root / "artifacts" / "runs" / "proof-blocked"
            self.assertTrue((run_root / "03_proof" / "blocker.md").exists())

            self._write_review(run_root, "03_proof", "retry", "Take one more attempt with the same plan.")
            manifest = workflow.resume("proof-blocked", auto_approve=True)
            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(manifest.attempt_count, 2)

    def test_retry_decision_allows_exactly_one_more_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )
            runner = SequencedLeanRunner(["missing_toolchain", "compile_failed", "compile_failed"])
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=runner,
                max_attempts=3,
            )

            manifest = workflow.prove(source_path=source_path, run_id="one-more-attempt", auto_approve=True)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 1)

            run_root = temp_root / "artifacts" / "runs" / "one-more-attempt"
            self._write_review(run_root, "03_proof", "retry", "Toolchain is back; take one more shot.")
            manifest = workflow.resume("one-more-attempt", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 2)
            self.assertEqual(runner.attempts, [1, 2])

    def test_resume_repair_loop_reuses_last_compile_result(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        template_dir = project_root / "lean_workspace_template"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            fake_lake = self._write_fake_lake(temp_root)
            source_path = temp_root / "input.md"
            source_path.write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )

            crashing_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=CrashBeforeRepairAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )
            with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                crashing_workflow.prove(
                    source_path=source_path,
                    run_id="repair-resume",
                    auto_approve=True,
                )

            manifest = crashing_workflow.status("repair-resume")
            self.assertEqual(manifest.current_stage, RunStage.PROVING)
            self.assertEqual(manifest.attempt_count, 1)

            resumed_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )
            manifest = resumed_workflow.resume("repair-resume", auto_approve=True)

            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(manifest.attempt_count, 2)

    def test_resume_legacy_plan_review_imports_old_spec_and_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-plan"
            run_root.mkdir(parents=True)
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                """{
  "run_id": "legacy-plan",
  "source": {"path": "input.md", "kind": "markdown"},
  "agent_name": "repair_resume_agent",
  "created_at": "2026-04-16T00:00:00Z",
  "updated_at": "2026-04-16T00:00:00Z",
  "current_stage": "awaiting_plan_review"
}
""",
                encoding="utf-8",
            )
            store = RunStore(temp_root / "artifacts", "legacy-plan")
            store.write_json(
                "04_spec/theorem_spec.approved.json",
                {
                    "title": "Zero add",
                    "informal_statement": "For every natural number n, 0 + n = n.",
                    "assumptions": ["n : Nat"],
                    "conclusion": "0 + n = n",
                    "symbols": ["0", "+", "Nat"],
                    "ambiguities": [],
                    "paraphrase": "Zero on the left does not change a natural number.",
                },
            )
            store.write_json(
                "05_context/context_pack.json",
                {
                    "recommended_imports": ["FormalizationEngineWorkspace.Basic"],
                    "local_examples": ["examples/inputs/zero_add.md"],
                    "notes": ["Use Nat.zero_add."],
                },
            )
            store.write_json(
                "06_plan/formalization_plan.json",
                {
                    "theorem_name": "zero_add_legacy",
                    "imports": ["FormalizationEngineWorkspace.Basic"],
                    "prerequisites_to_formalize": [],
                    "helper_definitions": [],
                    "target_statement": "theorem zero_add_legacy (n : Nat) : 0 + n = n",
                    "proof_sketch": ["Use the existing `Nat.zero_add` lemma."],
                },
            )

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=SequencedLeanRunner(["compile_failed"]),
                max_attempts=1,
            )
            manifest = workflow.resume("legacy-plan", auto_approve=True)

            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 1)
            self.assertTrue((run_root / "03_proof" / "checkpoint.md").exists())

    def test_resume_legacy_final_review_uses_old_candidate_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-final"
            run_root.mkdir(parents=True)
            (run_root / "manifest.json").write_text(
                """{
  "run_id": "legacy-final",
  "source": {"path": "input.md", "kind": "markdown"},
  "agent_name": "repair_resume_agent",
  "created_at": "2026-04-16T00:00:00Z",
  "updated_at": "2026-04-16T00:00:00Z",
  "current_stage": "awaiting_final_review",
  "attempt_count": 1
}
""",
                encoding="utf-8",
            )
            store = RunStore(temp_root / "artifacts", "legacy-final")
            store.write_text(
                "10_final/final_candidate.lean",
                "import FormalizationEngineWorkspace.Basic\n",
            )
            store.write_text(
                "10_final/final_report.md",
                "Legacy final report.\n",
            )

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=SequencedLeanRunner(["passed"]),
            )
            manifest = workflow.resume("legacy-final", auto_approve=True)

            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(manifest.final_output_path, "04_final/final.lean")
            self.assertTrue((run_root / "04_final" / "final.lean").exists())

    def test_logs_capture_checkpoints_and_proof_events(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        template_dir = project_root / "lean_workspace_template"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            fake_lake = self._write_fake_lake(temp_root)
            source_path = temp_root / "input.md"
            source_path.write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )

            manifest = workflow.prove(source_path=source_path, run_id="logging", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)
            run_root = temp_root / "artifacts" / "runs" / "logging"
            log_text = (run_root / "logs" / "timeline.md").read_text(encoding="utf-8")
            self.assertIn("run_started", log_text)
            self.assertIn("checkpoint_opened", log_text)
