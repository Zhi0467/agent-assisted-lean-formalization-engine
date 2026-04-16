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
        self.lake_path: str | None = None

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


class EnrichmentFeedbackAgent(RepairResumeAgent):
    name = "enrichment_feedback_agent"

    def __init__(self) -> None:
        self.context_notes: list[str] | None = None

    def draft_formalization_plan(
        self,
        source_ref: SourceRef,
        source_text: str,
        extraction: TheoremExtraction,
        enrichment: EnrichmentReport,
        context_pack: ContextPack,
    ) -> tuple[FormalizationPlan, AgentTurn]:
        self.context_notes = list(context_pack.notes)
        return super().draft_formalization_plan(
            source_ref,
            source_text,
            extraction,
            enrichment,
            context_pack,
        )


class PlanFeedbackAgent(RepairResumeAgent):
    name = "plan_feedback_agent"

    def __init__(self) -> None:
        self.seen_human_feedback: str | None = None
        self.seen_feedback_by_attempt: list[str | None] = []

    def draft_lean_file(
        self,
        plan: FormalizationPlan,
        repair_context: RepairContext,
    ) -> tuple[LeanDraft, AgentTurn]:
        self.seen_feedback_by_attempt.append(repair_context.human_feedback)
        if repair_context.current_attempt == 1:
            self.seen_human_feedback = repair_context.human_feedback
            draft = LeanDraft(
                theorem_name="zero_add_resume",
                module_name="FormalizationEngineWorkspace.Generated",
                imports=["FormalizationEngineWorkspace.Basic"],
                content=(
                    "import FormalizationEngineWorkspace.Basic\n\n"
                    "theorem zero_add_resume (n : Nat) : 0 + n = n := by\n"
                    "  simpa using Nat.zero_add n\n"
                ),
                rationale="guided first attempt",
            )
            return draft, AgentTurn(request_payload={}, prompt="draft", raw_response="draft")
        return super().draft_lean_file(plan, repair_context)


class RepairFeedbackAgent(RepairResumeAgent):
    name = "repair_feedback_agent"

    def __init__(self) -> None:
        self.seen_feedback_by_attempt: list[str | None] = []

    def draft_lean_file(
        self,
        plan: FormalizationPlan,
        repair_context: RepairContext,
    ) -> tuple[LeanDraft, AgentTurn]:
        self.seen_feedback_by_attempt.append(repair_context.human_feedback)
        return super().draft_lean_file(plan, repair_context)


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

    def test_checkpoint_resume_command_preserves_repo_root_and_lake_path(self) -> None:
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
            )

            manifest = workflow.prove(source_path=source_path, run_id="resume-context", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            checkpoint_text = (
                temp_root
                / "artifacts"
                / "runs"
                / "resume-context"
                / "01_enrichment"
                / "checkpoint.md"
            ).read_text(encoding="utf-8")
            self.assertIn(
                (
                    "terry --repo-root "
                    f"{temp_root.resolve()} --lake-path {fake_lake.resolve()} resume resume-context"
                ),
                checkpoint_text,
            )

    def test_extraction_turn_artifacts_are_preserved(self) -> None:
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
            )

            manifest = workflow.prove(source_path=source_path, run_id="turn-artifacts", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            run_root = temp_root / "artifacts" / "runs" / "turn-artifacts" / "01_enrichment"
            self.assertEqual(
                (run_root / "extraction_turn" / "prompt.md").read_text(encoding="utf-8"),
                "extraction",
            )
            self.assertEqual(
                (run_root / "enrichment_turn" / "prompt.md").read_text(encoding="utf-8"),
                "enrichment",
            )

    def test_review_template_keeps_notes_empty_without_feedback(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        template_dir = project_root / "lean_workspace_template"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir),
            )

            review_text = workflow._review_template("Proof Loop Blocked", "retry")
            parsed = workflow._parse_review_file(
                review_text.replace("decision: pending", "decision: retry")
            )

            assert parsed is not None
            self.assertEqual(parsed.notes, "")

    def test_enrichment_review_notes_flow_into_plan_context(self) -> None:
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
            agent = EnrichmentFeedbackAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )

            manifest = workflow.prove(source_path=source_path, run_id="enrichment-feedback", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            run_root = temp_root / "artifacts" / "runs" / "enrichment-feedback"
            self._write_review(run_root, "01_enrichment", "approve", "Need to keep the scope fully over Nat.")
            manifest = workflow.resume("enrichment-feedback", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)
            assert agent.context_notes is not None
            self.assertIn(
                "Reviewer guidance from the enrichment checkpoint: Need to keep the scope fully over Nat.",
                agent.context_notes,
            )

    def test_plan_review_notes_flow_into_prove_loop(self) -> None:
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
            agent = PlanFeedbackAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )

            manifest = workflow.prove(source_path=source_path, run_id="plan-feedback", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)
            run_root = temp_root / "artifacts" / "runs" / "plan-feedback"

            self._write_review(run_root, "01_enrichment", "approve", "")
            manifest = workflow.resume("plan-feedback", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)

            self._write_review(run_root, "02_plan", "approve", "Use the direct Nat.zero_add route.")
            manifest = workflow.resume("plan-feedback", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_APPROVAL)
            self.assertEqual(agent.seen_human_feedback, "Use the direct Nat.zero_add route.")
            self.assertEqual(agent.seen_feedback_by_attempt, ["Use the direct Nat.zero_add route."])

    def test_plan_review_guidance_reaches_every_proof_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            agent = RepairFeedbackAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=SequencedLeanRunner(["compile_failed", "passed"]),
                max_attempts=2,
            )
            source_path = temp_root / "input.md"
            source_path.write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )

            manifest = workflow.prove(source_path=source_path, run_id="plan-feedback-retry", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)
            run_root = temp_root / "artifacts" / "runs" / "plan-feedback-retry"

            self._write_review(run_root, "01_enrichment", "approve", "")
            manifest = workflow.resume("plan-feedback-retry", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)

            self._write_review(run_root, "02_plan", "approve", "Use the direct Nat.zero_add route.")
            manifest = workflow.resume("plan-feedback-retry", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_APPROVAL)
            self.assertEqual(
                agent.seen_feedback_by_attempt,
                ["Use the direct Nat.zero_add route.", "Use the direct Nat.zero_add route."],
            )

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

    def test_rejected_review_file_decision_is_persisted(self) -> None:
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
            )

            manifest = workflow.prove(source_path=source_path, run_id="reject-review", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            run_root = temp_root / "artifacts" / "runs" / "reject-review"
            self._write_review(run_root, "01_enrichment", "reject", "Scope is still wrong.")
            manifest = workflow.resume("reject-review", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)
            self.assertEqual(
                RunStore(temp_root / "artifacts", "reject-review").read_json("01_enrichment/decision.json")[
                    "decision"
                ],
                "reject",
            )

            self._write_review(run_root, "01_enrichment", "approve", "Scope looks right now.")
            manifest = workflow.resume("reject-review", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)

    def test_auto_approve_still_respects_rejected_review_file(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        template_dir = project_root / "lean_workspace_template"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path="/definitely/missing/lake"),
            )

            manifest = workflow.prove(source_path=source_path, run_id="reject-auto-approve", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            run_root = temp_root / "artifacts" / "runs" / "reject-auto-approve"
            self._write_review(run_root, "01_enrichment", "reject", "Need changes first.")
            manifest = workflow.resume("reject-auto-approve", auto_approve=True)

            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)
            self.assertEqual(
                RunStore(temp_root / "artifacts", "reject-auto-approve").read_json("01_enrichment/decision.json")[
                    "decision"
                ],
                "reject",
            )

    def test_invalid_review_file_decision_raises(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        template_dir = project_root / "lean_workspace_template"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path="/definitely/missing/lake"),
            )

            manifest = workflow.prove(source_path=source_path, run_id="invalid-review", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            run_root = temp_root / "artifacts" / "runs" / "invalid-review"
            self._write_review(run_root, "01_enrichment", "approved", "Typo.")

            with self.assertRaisesRegex(ValueError, "Unsupported review decision"):
                workflow.resume("invalid-review", auto_approve=False)

    def test_successful_retry_clears_latest_error_before_final_review(self) -> None:
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
            )

            manifest = workflow.prove(source_path=source_path, run_id="clear-latest-error", auto_approve=False)
            run_root = temp_root / "artifacts" / "runs" / "clear-latest-error"
            self._write_review(run_root, "01_enrichment", "approve", "Looks good.")
            manifest = workflow.resume("clear-latest-error", auto_approve=False)
            self._write_review(run_root, "02_plan", "approve", "Proceed to proof.")
            manifest = workflow.resume("clear-latest-error", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_APPROVAL)
            self.assertIsNone(manifest.latest_error)

    def test_resume_proving_run_with_final_candidate_promotes_final_review(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "queued-final"
            run_root.mkdir(parents=True)
            store = RunStore(temp_root / "artifacts", "queued-final")
            store.write_json(
                "manifest.json",
                {
                    "run_id": "queued-final",
                    "source": {"path": "input.md", "kind": "markdown"},
                    "agent_name": "repair_resume_agent",
                    "agent_config": {"backend": "demo", "command": None, "codex_model": None},
                    "template_dir": str(temp_root / "lean_workspace_template"),
                    "created_at": "2026-04-16T00:00:00Z",
                    "updated_at": "2026-04-16T00:00:00Z",
                    "current_stage": "proving",
                    "attempt_count": 1,
                },
            )
            store.write_text(
                "04_final/final_candidate.lean",
                "import FormalizationEngineWorkspace.Basic\n",
            )
            store.write_text(
                "04_final/final_report.md",
                "Candidate compiled already.\n",
            )

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=SequencedLeanRunner(["compile_failed"]),
            )
            manifest = workflow.resume("queued-final", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_APPROVAL)
            self.assertEqual(manifest.attempt_count, 1)
            self.assertTrue((run_root / "04_final" / "review.md").exists())

    def test_resume_override_updates_manifest_lake_path(self) -> None:
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
            blocked_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path="/definitely/missing/lake"),
                max_attempts=1,
            )
            manifest = blocked_workflow.prove(source_path=source_path, run_id="lake-override", auto_approve=True)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)

            run_root = temp_root / "artifacts" / "runs" / "lake-override"
            self._write_review(run_root, "03_proof", "retry", "")

            resumed_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
                max_attempts=1,
            )
            resumed_workflow.resume("lake-override", auto_approve=False)

            persisted_manifest = RunStore(temp_root / "artifacts", "lake-override").read_json("manifest.json")
            self.assertEqual(persisted_manifest["lake_path"], str(fake_lake.resolve()))

    def test_resume_without_override_keeps_manifest_lake_path(self) -> None:
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
            initial_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir, lake_path=str(fake_lake)),
            )
            manifest = initial_workflow.prove(source_path=source_path, run_id="lake-sticky", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            resumed_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(template_dir=template_dir),
            )
            manifest = resumed_workflow.resume("lake-sticky", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            persisted_manifest = RunStore(temp_root / "artifacts", "lake-sticky").read_json("manifest.json")
            self.assertEqual(persisted_manifest["lake_path"], str(fake_lake.resolve()))

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
                lean_runner=SequencedLeanRunner(["compile_failed", "compile_failed"]),
                max_attempts=1,
            )
            manifest = workflow.resume("legacy-plan", auto_approve=True)

            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 1)
            self.assertTrue((run_root / "03_proof" / "checkpoint.md").exists())

    def test_resume_legacy_enrichment_review_honors_existing_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-enrichment"
            run_root.mkdir(parents=True)
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                """{
  "run_id": "legacy-enrichment",
  "source": {"path": "input.md", "kind": "markdown"},
  "agent_name": "repair_resume_agent",
  "created_at": "2026-04-16T00:00:00Z",
  "updated_at": "2026-04-16T00:00:00Z",
  "current_stage": "awaiting_enrichment_review"
}
""",
                encoding="utf-8",
            )
            store = RunStore(temp_root / "artifacts", "legacy-enrichment")
            store.write_json(
                "02_extraction/theorem_extraction.json",
                {
                    "title": "Zero add",
                    "informal_statement": "For every natural number n, 0 + n = n.",
                    "definitions": ["Nat"],
                    "lemmas": ["Nat.zero_add"],
                    "propositions": [],
                    "dependencies": ["Nat.zero_add"],
                    "notes": [],
                },
            )
            store.write_json(
                "03_enrichment/enrichment_report.json",
                {
                    "self_contained": True,
                    "satisfied_prerequisites": ["Nat.zero_add exists."],
                    "missing_prerequisites": [],
                    "required_plan_additions": [],
                    "recommended_scope": "Keep the theorem over Nat.",
                    "difficulty_assessment": "easy",
                    "open_questions": [],
                    "next_steps": ["Approve the merged plan."],
                    "human_handoff": "Everything needed is already present.",
                },
            )
            store.write_json(
                "03_enrichment/decision.json",
                {
                    "approved": True,
                    "updated_at": "2026-04-16T00:01:00Z",
                    "notes": "approved legacy enrichment",
                },
            )

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=SequencedLeanRunner(["compile_failed", "compile_failed"]),
                max_attempts=1,
            )
            manifest = workflow.resume("legacy-enrichment", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)
            self.assertTrue((run_root / "02_plan" / "checkpoint.md").exists())

    def test_resume_legacy_plan_review_honors_existing_decision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-plan-review"
            run_root.mkdir(parents=True)
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                """{
  "run_id": "legacy-plan-review",
  "source": {"path": "input.md", "kind": "markdown"},
  "agent_name": "repair_resume_agent",
  "created_at": "2026-04-16T00:00:00Z",
  "updated_at": "2026-04-16T00:00:00Z",
  "current_stage": "awaiting_plan_review"
}
""",
                encoding="utf-8",
            )
            store = RunStore(temp_root / "artifacts", "legacy-plan-review")
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
            store.write_json(
                "06_plan/decision.json",
                {
                    "approved": True,
                    "updated_at": "2026-04-16T00:01:00Z",
                    "notes": "approved legacy plan",
                },
            )

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=SequencedLeanRunner(["compile_failed", "compile_failed", "compile_failed"]),
                max_attempts=1,
            )
            manifest = workflow.resume("legacy-plan-review", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 1)

    def test_resume_legacy_spec_review_builds_merged_plan_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-spec"
            run_root.mkdir(parents=True)
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                """{
  "run_id": "legacy-spec",
  "source": {"path": "input.md", "kind": "markdown"},
  "agent_name": "repair_resume_agent",
  "created_at": "2026-04-16T00:00:00Z",
  "updated_at": "2026-04-16T00:00:00Z",
  "current_stage": "awaiting_spec_review"
}
""",
                encoding="utf-8",
            )
            store = RunStore(temp_root / "artifacts", "legacy-spec")
            store.write_json(
                "02_extraction/theorem_extraction.json",
                {
                    "title": "Zero add",
                    "informal_statement": "For every natural number n, 0 + n = n.",
                    "definitions": ["Nat"],
                    "lemmas": ["Nat.zero_add"],
                    "propositions": [],
                    "dependencies": ["Nat.zero_add"],
                    "notes": [],
                },
            )
            store.write_json(
                "03_enrichment/enrichment_report.approved.json",
                {
                    "self_contained": True,
                    "satisfied_prerequisites": ["Nat.zero_add exists."],
                    "missing_prerequisites": [],
                    "required_plan_additions": [],
                    "recommended_scope": "Keep the theorem over Nat.",
                    "difficulty_assessment": "easy",
                    "open_questions": [],
                    "next_steps": ["Approve the merged plan."],
                    "human_handoff": "Everything needed is already present.",
                },
            )
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

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=SequencedLeanRunner(["compile_failed"]),
                max_attempts=1,
            )

            status = workflow.status("legacy-spec")
            self.assertEqual(status.current_stage, RunStage.AWAITING_PLAN_APPROVAL)

            manifest = workflow.resume("legacy-spec", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)
            self.assertTrue((run_root / "02_plan" / "formalization_plan.json").exists())
            self.assertTrue((run_root / "02_plan" / "checkpoint.md").exists())

    def test_resume_legacy_spec_review_does_not_promote_rejected_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-spec-rejected"
            run_root.mkdir(parents=True)
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                """{
  "run_id": "legacy-spec-rejected",
  "source": {"path": "input.md", "kind": "markdown"},
  "agent_name": "repair_resume_agent",
  "created_at": "2026-04-16T00:00:00Z",
  "updated_at": "2026-04-16T00:00:00Z",
  "current_stage": "awaiting_spec_review"
}
""",
                encoding="utf-8",
            )
            store = RunStore(temp_root / "artifacts", "legacy-spec-rejected")
            store.write_json(
                "04_spec/theorem_spec.json",
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
                "04_spec/decision.json",
                {
                    "approved": False,
                    "updated_at": "2026-04-16T00:01:00Z",
                    "notes": "spec rejected",
                },
            )

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=SequencedLeanRunner(["compile_failed"]),
                max_attempts=1,
            )

            manifest = workflow.resume("legacy-spec-rejected", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)
            self.assertFalse((run_root / "02_plan" / "formalization_plan.json").exists())
            self.assertFalse((run_root / "02_plan" / "checkpoint.md").exists())

    def test_resume_legacy_spec_review_creates_actionable_review_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-spec-pending"
            run_root.mkdir(parents=True)
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                """{
  "run_id": "legacy-spec-pending",
  "source": {"path": "input.md", "kind": "markdown"},
  "agent_name": "repair_resume_agent",
  "created_at": "2026-04-16T00:00:00Z",
  "updated_at": "2026-04-16T00:00:00Z",
  "current_stage": "awaiting_spec_review"
}
""",
                encoding="utf-8",
            )
            store = RunStore(temp_root / "artifacts", "legacy-spec-pending")
            store.write_json(
                "02_extraction/theorem_extraction.json",
                {
                    "title": "Zero add",
                    "informal_statement": "For every natural number n, 0 + n = n.",
                    "definitions": ["Nat"],
                    "lemmas": ["Nat.zero_add"],
                    "propositions": [],
                    "dependencies": ["Nat.zero_add"],
                    "notes": [],
                },
            )
            store.write_json(
                "03_enrichment/enrichment_report.approved.json",
                {
                    "self_contained": True,
                    "satisfied_prerequisites": ["Nat.zero_add exists."],
                    "missing_prerequisites": [],
                    "required_plan_additions": [],
                    "recommended_scope": "Keep the theorem over Nat.",
                    "difficulty_assessment": "easy",
                    "open_questions": [],
                    "next_steps": ["Approve the merged plan."],
                    "human_handoff": "Everything needed is already present.",
                },
            )
            store.write_json(
                "04_spec/theorem_spec.json",
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

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=SequencedLeanRunner(["compile_failed"]),
                max_attempts=1,
            )

            manifest = workflow.resume("legacy-spec-pending", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)
            self.assertTrue((run_root / "04_spec" / "checkpoint.md").exists())
            self.assertTrue((run_root / "04_spec" / "review.md").exists())
            self.assertFalse((run_root / "02_plan" / "formalization_plan.json").exists())

            (run_root / "04_spec" / "review.md").write_text(
                "# Legacy spec review\n\ndecision: approve\n\nNotes:\nLooks good.\n",
                encoding="utf-8",
            )

            manifest = workflow.resume("legacy-spec-pending", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)
            self.assertTrue((run_root / "02_plan" / "formalization_plan.json").exists())
            self.assertTrue((run_root / "02_plan" / "checkpoint.md").exists())

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

    def test_resume_legacy_rejected_final_review_stays_paused(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-final-reject"
            run_root.mkdir(parents=True)
            (run_root / "manifest.json").write_text(
                """{
  "run_id": "legacy-final-reject",
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
            store = RunStore(temp_root / "artifacts", "legacy-final-reject")
            store.write_text(
                "10_final/final_candidate.lean",
                "import FormalizationEngineWorkspace.Basic\n",
            )
            store.write_json(
                "10_final/decision.json",
                {
                    "approved": False,
                    "updated_at": "2026-04-16T00:01:00Z",
                    "notes": "Needs changes.",
                },
            )

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=SequencedLeanRunner(["passed"]),
            )
            manifest = workflow.resume("legacy-final-reject", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_APPROVAL)
            self.assertIsNone(manifest.final_output_path)
            self.assertFalse((run_root / "04_final" / "final.lean").exists())
            self.assertEqual(
                store.read_json("04_final/decision.json")["decision"],
                "reject",
            )

    def test_resume_legacy_rejected_stall_review_stays_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-stall-reject"
            run_root.mkdir(parents=True)
            (run_root / "manifest.json").write_text(
                """{
  "run_id": "legacy-stall-reject",
  "source": {"path": "input.md", "kind": "markdown"},
  "agent_name": "repair_resume_agent",
  "created_at": "2026-04-16T00:00:00Z",
  "updated_at": "2026-04-16T00:00:00Z",
  "current_stage": "awaiting_stall_review",
  "attempt_count": 1
}
""",
                encoding="utf-8",
            )
            store = RunStore(temp_root / "artifacts", "legacy-stall-reject")
            store.write_text("09_review/stall_report.md", "Still blocked.\n")
            store.write_json(
                "09_review/decision.json",
                {
                    "approved": False,
                    "updated_at": "2026-04-16T00:01:00Z",
                    "notes": "Do not retry yet.",
                },
            )

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=SequencedLeanRunner(["passed"]),
            )
            manifest = workflow.resume("legacy-stall-reject", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 1)
            self.assertEqual(
                store.read_json("03_proof/decision.json")["decision"],
                "reject",
            )

    def test_resume_legacy_stall_retry_approval_is_one_shot(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-stall-once"
            run_root.mkdir(parents=True)
            (run_root / "manifest.json").write_text(
                """{
  "run_id": "legacy-stall-once",
  "source": {"path": "input.md", "kind": "markdown"},
  "agent_name": "repair_resume_agent",
  "created_at": "2026-04-16T00:00:00Z",
  "updated_at": "2026-04-16T00:02:00Z",
  "current_stage": "awaiting_stall_review",
  "attempt_count": 1
}
""",
                encoding="utf-8",
            )
            store = RunStore(temp_root / "artifacts", "legacy-stall-once")
            store.write_text("09_review/stall_report.md", "Still blocked.\n")
            store.write_json(
                "09_review/decision.json",
                {
                    "approved": True,
                    "updated_at": "2026-04-16T00:01:00Z",
                    "notes": "Retry now.",
                },
            )

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=SequencedLeanRunner(["passed"]),
            )
            manifest = workflow.resume("legacy-stall-once", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 1)
            self.assertEqual(
                store.read_text("03_proof/blocker.md"),
                "# Proof Loop Blocked\n\nStill blocked.\n",
            )

    def test_resume_legacy_stall_retry_accepts_same_second_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-stall-same-second"
            run_root.mkdir(parents=True)
            (run_root / "manifest.json").write_text(
                """{
  "run_id": "legacy-stall-same-second",
  "source": {"path": "input.md", "kind": "markdown"},
  "agent_name": "repair_resume_agent",
  "created_at": "2026-04-16T00:00:00Z",
  "updated_at": "2026-04-16T00:01:00Z",
  "current_stage": "awaiting_stall_review",
  "attempt_count": 1
}
""",
                encoding="utf-8",
            )
            store = RunStore(temp_root / "artifacts", "legacy-stall-same-second")
            store.write_json(
                "04_spec/theorem_spec.json",
                {
                    "title": "t",
                    "informal_statement": "True",
                    "assumptions": [],
                    "conclusion": "True",
                    "symbols": [],
                    "ambiguities": [],
                    "paraphrase": "True",
                },
            )
            store.write_json(
                "06_plan/formalization_plan.json",
                {
                    "theorem_name": "t",
                    "imports": ["FormalizationEngineWorkspace.Basic"],
                    "prerequisites_to_formalize": [],
                    "helper_definitions": [],
                    "target_statement": "theorem t : True",
                    "proof_sketch": ["x"],
                },
            )
            store.write_json(
                "08_compile/attempt_0001/result.json",
                {
                    "attempt": 1,
                    "command": ["lake build FormalizationEngineWorkspace"],
                    "stdout": "",
                    "stderr": "compile failed",
                    "returncode": 1,
                    "diagnostics": ["compile failed"],
                    "fast_check_passed": False,
                    "build_passed": False,
                    "contains_sorry": True,
                    "missing_toolchain": False,
                    "quality_gate_passed": False,
                    "passed": False,
                    "status": "compile_failed",
                },
            )
            store.write_json(
                "07_draft/attempt_0001/parsed_output.json",
                {
                    "theorem_name": "t",
                    "module_name": "FormalizationEngineWorkspace.Generated",
                    "imports": ["FormalizationEngineWorkspace.Basic"],
                    "content": (
                        "import FormalizationEngineWorkspace.Basic\n\n"
                        "theorem t : True := by\n"
                        "  sorry\n"
                    ),
                    "rationale": "legacy first attempt",
                },
            )
            store.write_json(
                "09_review/decision.json",
                {
                    "approved": True,
                    "updated_at": "2026-04-16T00:01:00Z",
                    "notes": "retry now",
                },
            )

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=SequencedLeanRunner(["compile_failed", "compile_failed", "compile_failed"]),
                max_attempts=1,
            )
            manifest = workflow.resume("legacy-stall-same-second", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 2)

    def test_resume_legacy_stall_retry_keeps_new_blocker_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-stall"
            run_root.mkdir(parents=True)
            (run_root / "manifest.json").write_text(
                """{
  "run_id": "legacy-stall",
  "source": {"path": "input.md", "kind": "markdown"},
  "agent_name": "repair_resume_agent",
  "created_at": "2026-04-16T00:00:00Z",
  "updated_at": "2026-04-16T00:00:00Z",
  "current_stage": "awaiting_stall_review",
  "attempt_count": 1
}
""",
                encoding="utf-8",
            )
            store = RunStore(temp_root / "artifacts", "legacy-stall")
            store.write_json(
                "04_spec/theorem_spec.json",
                {
                    "title": "t",
                    "informal_statement": "True",
                    "assumptions": [],
                    "conclusion": "True",
                    "symbols": [],
                    "ambiguities": [],
                    "paraphrase": "True",
                },
            )
            store.write_json(
                "06_plan/formalization_plan.json",
                {
                    "theorem_name": "t",
                    "imports": ["FormalizationEngineWorkspace.Basic"],
                    "prerequisites_to_formalize": [],
                    "helper_definitions": [],
                    "target_statement": "theorem t : True",
                    "proof_sketch": ["x"],
                },
            )
            store.write_json(
                "08_compile/attempt_0001/result.json",
                {
                    "attempt": 1,
                    "command": ["lake build FormalizationEngineWorkspace"],
                    "stdout": "",
                    "stderr": "compile failed",
                    "returncode": 1,
                    "diagnostics": ["compile failed"],
                    "fast_check_passed": False,
                    "build_passed": False,
                    "contains_sorry": True,
                    "missing_toolchain": False,
                    "quality_gate_passed": False,
                    "passed": False,
                    "status": "compile_failed",
                },
            )
            store.write_json(
                "07_draft/attempt_0001/parsed_output.json",
                {
                    "theorem_name": "t",
                    "module_name": "FormalizationEngineWorkspace.Generated",
                    "imports": ["FormalizationEngineWorkspace.Basic"],
                    "content": (
                        "import FormalizationEngineWorkspace.Basic\n\n"
                        "theorem t : True := by\n"
                        "  sorry\n"
                    ),
                    "rationale": "legacy first attempt",
                },
            )
            store.write_text("09_review/stall_report.md", "OLD STALL REPORT\n")
            store.write_json(
                "09_review/decision.json",
                {
                    "approved": True,
                    "updated_at": "2026-04-16T00:01:00Z",
                    "notes": "retry now",
                },
            )

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RepairResumeAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=SequencedLeanRunner(["compile_failed", "compile_failed", "compile_failed"]),
                max_attempts=1,
            )
            manifest = workflow.resume("legacy-stall", auto_approve=False)

            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 2)
            blocker_text = store.read_text("03_proof/blocker.md")
            self.assertIn("retry cap", blocker_text)
            self.assertNotIn("OLD STALL REPORT", blocker_text)

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
