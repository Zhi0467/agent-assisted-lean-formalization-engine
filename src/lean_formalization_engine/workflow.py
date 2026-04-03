from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .agents import FormalizationAgent
from .ingest import ingest_source
from .lean_runner import LeanRunner
from .models import (
    AgentTurn,
    CompileAttempt,
    FormalizationPlan,
    LeanDraft,
    RunManifest,
    RunStage,
    RunStatus,
    SourceRef,
    TheoremSpec,
)
from .storage import ArtifactStore, utc_timestamp


@dataclass
class WorkflowOptions:
    auto_approve_spec: bool = False
    auto_approve_plan: bool = False
    auto_finalize: bool = False
    max_repair_attempts: int = 2


class FormalizationWorkflow:
    def __init__(
        self,
        store: ArtifactStore,
        agent: FormalizationAgent,
        lean_runner: LeanRunner,
    ) -> None:
        self.store = store
        self.agent = agent
        self.lean_runner = lean_runner

    def run(self, run_id: str, source: SourceRef, options: WorkflowOptions) -> RunManifest:
        run_dir = self.store.initialize_run(run_id)
        manifest = RunManifest(
            run_id=run_id,
            source=source,
            current_stage=RunStage.CREATED,
            status=RunStatus.RUNNING,
            created_at=utc_timestamp(),
            updated_at=utc_timestamp(),
        )
        self._save_manifest(run_dir, manifest)

        ingested = ingest_source(source)
        self.store.write_text(run_dir, "00_input/source.txt", ingested.raw_text)
        self.store.write_json(run_dir, "00_input/provenance.json", ingested.provenance)
        self.store.write_text(run_dir, "01_normalized/normalized.txt", ingested.normalized_text)
        self._advance(manifest, run_dir, RunStage.INGESTED, RunStatus.RUNNING)

        theorem_spec = self._record_agent_turn(
            run_dir=run_dir,
            prefix="02_spec",
            turn=self.agent.draft_spec(ingested.normalized_text),
            parsed_filename="theorem_spec.json",
        )
        self._advance(manifest, run_dir, RunStage.SPEC_DRAFTED, RunStatus.RUNNING)

        if not options.auto_approve_spec:
            self.store.write_json(
                run_dir,
                "02_spec/pending_review.json",
                {"message": "Approve or edit theorem_spec.json before continuing."},
            )
            self._advance(manifest, run_dir, RunStage.WAITING_FOR_SPEC_APPROVAL, RunStatus.WAITING_HUMAN)
            return manifest

        self.store.write_json(run_dir, "02_spec/decision.json", {"approved": True, "source": "auto"})
        self.store.write_json(run_dir, "02_spec/theorem_spec.approved.json", theorem_spec)
        self._advance(manifest, run_dir, RunStage.SPEC_APPROVED, RunStatus.RUNNING)

        plan = self._record_agent_turn(
            run_dir=run_dir,
            prefix="03_plan",
            turn=self.agent.draft_plan(theorem_spec),
            parsed_filename="formalization_plan.json",
        )
        self._advance(manifest, run_dir, RunStage.PLAN_DRAFTED, RunStatus.RUNNING)

        if not options.auto_approve_plan:
            self.store.write_json(
                run_dir,
                "03_plan/pending_review.json",
                {"message": "Approve or edit formalization_plan.json before continuing."},
            )
            self._advance(manifest, run_dir, RunStage.WAITING_FOR_PLAN_APPROVAL, RunStatus.WAITING_HUMAN)
            return manifest

        self.store.write_json(run_dir, "03_plan/decision.json", {"approved": True, "source": "auto"})
        self.store.write_json(run_dir, "03_plan/formalization_plan.approved.json", plan)
        self._advance(manifest, run_dir, RunStage.PLAN_APPROVED, RunStatus.RUNNING)

        draft_turn = self.agent.draft_lean(theorem_spec, plan)
        draft = self._record_agent_turn(
            run_dir=run_dir,
            prefix="04_draft",
            turn=draft_turn,
            parsed_filename="draft.json",
        )
        self.store.write_text(run_dir, "04_draft/draft_0001.lean", draft.code)
        self._advance(manifest, run_dir, RunStage.DRAFT_GENERATED, RunStatus.RUNNING)

        final_draft, compile_attempt = self._compile_with_repairs(
            run_dir, theorem_spec, plan, draft, options
        )
        manifest.attempt_count = compile_attempt.attempt
        self._record_compile(run_dir, compile_attempt)

        if compile_attempt.passed and compile_attempt.quality_gate_passed:
            self._advance(manifest, run_dir, RunStage.COMPILE_PASSED, RunStatus.RUNNING)
            self.store.write_text(run_dir, "06_final/final.lean", final_draft.code)
            self.store.write_json(
                run_dir,
                "06_final/final_report.json",
                {
                    "theorem_name": final_draft.theorem_name,
                    "compile_attempt": compile_attempt.attempt,
                    "quality_gate_passed": compile_attempt.quality_gate_passed,
                },
            )
            manifest.final_output_path = "06_final/final.lean"
            if options.auto_finalize:
                self.store.write_json(run_dir, "06_final/decision.json", {"approved": True, "source": "auto"})
                self._advance(manifest, run_dir, RunStage.COMPLETED, RunStatus.COMPLETED)
            else:
                self._advance(manifest, run_dir, RunStage.WAITING_FOR_FINAL_APPROVAL, RunStatus.WAITING_HUMAN)
            return manifest

        self._advance(manifest, run_dir, RunStage.COMPILE_FAILED, RunStatus.WAITING_HUMAN)
        return manifest

    def _compile_with_repairs(
        self,
        run_dir: Path,
        theorem_spec: TheoremSpec,
        plan: FormalizationPlan,
        draft: LeanDraft,
        options: WorkflowOptions,
    ) -> tuple[LeanDraft, CompileAttempt]:
        current_draft = draft
        for attempt in range(1, options.max_repair_attempts + 2):
            result = self.lean_runner.compile_draft(run_dir, current_draft, attempt)
            if result.passed and result.quality_gate_passed:
                if attempt > 1:
                    self.store.write_text(run_dir, f"04_draft/draft_{attempt:04d}.lean", current_draft.code)
                return current_draft, result
            if result.missing_toolchain or attempt > options.max_repair_attempts:
                if attempt > 1:
                    self.store.write_text(run_dir, f"04_draft/draft_{attempt:04d}.lean", current_draft.code)
                return current_draft, result
            repair_turn = self.agent.repair_lean(
                theorem_spec=theorem_spec,
                plan=plan,
                previous_draft=current_draft,
                diagnostics=result.stderr,
                attempt=attempt,
            )
            current_draft = repair_turn.parsed_output
            self._record_agent_turn(
                run_dir=run_dir,
                prefix="04_draft",
                turn=repair_turn,
                parsed_filename=f"repair_{attempt:04d}.json",
            )
            self.store.write_text(run_dir, f"04_draft/draft_{attempt + 1:04d}.lean", current_draft.code)
        return current_draft, result

    def _record_agent_turn(
        self,
        run_dir: Path,
        prefix: str,
        turn: AgentTurn,
        parsed_filename: str,
    ):
        self.store.write_text(run_dir, f"{prefix}/prompt.md", turn.prompt + "\n")
        self.store.write_json(run_dir, f"{prefix}/request.json", turn.request_payload)
        self.store.write_json(run_dir, f"{prefix}/raw_response.json", {"raw_response": turn.raw_response})
        self.store.write_json(run_dir, f"{prefix}/{parsed_filename}", turn.parsed_output)
        return turn.parsed_output

    def _record_compile(self, run_dir: Path, compile_attempt: CompileAttempt) -> None:
        prefix = f"05_compile/attempt_{compile_attempt.attempt:04d}"
        self.store.write_json(run_dir, f"{prefix}/result.json", compile_attempt)
        self.store.write_text(run_dir, f"{prefix}/stdout.txt", compile_attempt.stdout)
        self.store.write_text(run_dir, f"{prefix}/stderr.txt", compile_attempt.stderr)
        self.store.write_json(
            run_dir,
            f"{prefix}/quality_gate.json",
            {
                "passed": compile_attempt.quality_gate_passed,
                "checks": ["no_sorry_literals"],
            },
        )

    def _advance(self, manifest: RunManifest, run_dir: Path, stage: RunStage, status: RunStatus) -> None:
        manifest.current_stage = stage
        manifest.status = status
        manifest.updated_at = utc_timestamp()
        self.store.write_manifest(run_dir, manifest)
        self.store.append_event(run_dir, "stage_advanced", {"stage": stage.value, "status": status.value})

    def _save_manifest(self, run_dir: Path, manifest: RunManifest) -> None:
        self.store.write_manifest(run_dir, manifest)
        self.store.append_event(run_dir, "run_created", {"run_id": manifest.run_id})
