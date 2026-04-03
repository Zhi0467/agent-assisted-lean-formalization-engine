from __future__ import annotations

from pathlib import Path

from .agents import FormalizationAgent
from .ingest import ingest_source
from .lean_runner import LeanRunner
from .models import (
    CompileAttempt,
    ContextPack,
    FormalizationPlan,
    HumanDecision,
    LeanDraft,
    RunManifest,
    RunStage,
    SourceKind,
    SourceRef,
    TheoremSpec,
    utc_now,
)
from .storage import RunStore


class FormalizationWorkflow:
    def __init__(
        self,
        repo_root: Path,
        agent: FormalizationAgent,
        lean_runner: LeanRunner | None = None,
        max_attempts: int = 3,
    ):
        self.repo_root = repo_root
        self.agent = agent
        self.max_attempts = max_attempts
        self.artifacts_root = repo_root / "artifacts"
        self.lean_runner = lean_runner or LeanRunner(
            repo_root / "lean_workspace_template"
        )

    def run(self, source_path: Path, run_id: str, auto_approve: bool = False) -> RunManifest:
        store = RunStore(self.artifacts_root, run_id)
        store.ensure()

        source_ref, ingested = ingest_source(source_path, repo_root=self.repo_root)
        manifest = RunManifest(
            run_id=run_id,
            source=source_ref,
            agent_name=self.agent.name,
            created_at=utc_now(),
            updated_at=utc_now(),
            current_stage=RunStage.CREATED,
        )
        self._save_manifest(store, manifest)
        store.write_text("00_input/source.txt", ingested.raw_text)
        store.write_text("01_normalized/normalized.md", ingested.normalized_text)
        store.write_json(
            "00_input/provenance.json",
            {
                "source": source_ref,
                "extraction_method": ingested.extraction_method,
            },
        )
        store.append_event(
            "run_created",
            {"run_id": run_id, "source_path": source_ref.path, "agent": self.agent.name},
        )

        theorem_spec, spec_turn = self.agent.draft_theorem_spec(
            source_ref,
            ingested.normalized_text,
        )
        self._write_agent_turn(store, "02_spec", spec_turn, theorem_spec)
        store.write_json("02_spec/theorem_spec.json", theorem_spec)

        if auto_approve:
            self._seed_spec_approval(store)
        if not store.exists("02_spec/theorem_spec.approved.json"):
            manifest.current_stage = RunStage.AWAITING_SPEC_REVIEW
            return self._save_manifest(store, manifest)

        self._build_context_pack(store, theorem_spec)
        plan = self._draft_plan(store, auto_approve=auto_approve)
        if isinstance(plan, RunManifest):
            return plan

        return self._compile_loop(store, plan, auto_approve=auto_approve)

    def resume(self, run_id: str, auto_approve: bool = False) -> RunManifest:
        store = RunStore(self.artifacts_root, run_id)
        manifest = self._load_manifest(store)

        if manifest.current_stage == RunStage.AWAITING_SPEC_REVIEW:
            if auto_approve:
                self._seed_spec_approval(store)
            if not store.exists("02_spec/theorem_spec.approved.json"):
                return manifest
            theorem_spec = self._load_theorem_spec(store, approved=True)
            self._build_context_pack(store, theorem_spec)
            plan = self._draft_plan(store, auto_approve=auto_approve)
            if isinstance(plan, RunManifest):
                return plan
            return self._compile_loop(store, plan, auto_approve=auto_approve)

        if manifest.current_stage == RunStage.AWAITING_PLAN_REVIEW:
            if auto_approve:
                self._seed_plan_approval(store)
            if not store.exists("04_plan/formalization_plan.approved.json"):
                return manifest
            plan = self._load_plan(store, approved=True)
            return self._compile_loop(store, plan, auto_approve=auto_approve)

        if manifest.current_stage == RunStage.AWAITING_FINAL_REVIEW:
            if auto_approve:
                self._seed_final_approval(store)
            if not store.exists("08_final/decision.json"):
                return manifest
            return self._complete_from_candidate(store, manifest)

        return manifest

    def approve_spec(self, run_id: str, notes: str = "Approved by CLI.") -> None:
        store = RunStore(self.artifacts_root, run_id)
        payload = store.read_json("02_spec/theorem_spec.json")
        store.write_json("02_spec/theorem_spec.approved.json", payload)
        store.write_json(
            "02_spec/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes=notes),
        )

    def approve_plan(self, run_id: str, notes: str = "Approved by CLI.") -> None:
        store = RunStore(self.artifacts_root, run_id)
        payload = store.read_json("04_plan/formalization_plan.json")
        store.write_json("04_plan/formalization_plan.approved.json", payload)
        store.write_json(
            "04_plan/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes=notes),
        )

    def approve_final(self, run_id: str, notes: str = "Approved by CLI.") -> None:
        store = RunStore(self.artifacts_root, run_id)
        store.write_json(
            "08_final/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes=notes),
        )

    def status(self, run_id: str) -> RunManifest:
        store = RunStore(self.artifacts_root, run_id)
        return self._load_manifest(store)

    def _draft_plan(self, store: RunStore, auto_approve: bool) -> FormalizationPlan | RunManifest:
        theorem_spec = self._load_theorem_spec(store, approved=True)
        context_payload = store.read_json("03_context/context_pack.json")
        context_pack = ContextPack(**context_payload)
        plan, plan_turn = self.agent.draft_formalization_plan(theorem_spec, context_pack)
        self._write_agent_turn(store, "04_plan", plan_turn, plan)
        store.write_json("04_plan/formalization_plan.json", plan)

        if auto_approve:
            self._seed_plan_approval(store)

        if not store.exists("04_plan/formalization_plan.approved.json"):
            manifest = self._load_manifest(store)
            manifest.current_stage = RunStage.AWAITING_PLAN_REVIEW
            return self._save_manifest(store, manifest)

        return self._load_plan(store, approved=True)

    def _compile_loop(
        self,
        store: RunStore,
        plan: FormalizationPlan,
        auto_approve: bool,
    ) -> RunManifest:
        manifest = self._load_manifest(store)
        previous_result: CompileAttempt | None = None

        while manifest.attempt_count < self.max_attempts:
            attempt = manifest.attempt_count + 1
            draft, draft_turn = self.agent.draft_lean_file(plan, attempt, previous_result)
            self._write_attempt(store, attempt, draft_turn, draft)
            compile_result = self.lean_runner.compile_draft(store, draft, attempt)
            self._write_compile_result(store, attempt, compile_result)

            manifest.attempt_count = attempt
            manifest.updated_at = utc_now()

            if compile_result.passed:
                return self._queue_final_review(store, manifest, draft, auto_approve)

            if compile_result.missing_toolchain:
                manifest.current_stage = RunStage.AWAITING_STALL_REVIEW
                manifest.latest_error = compile_result.stderr.strip() or compile_result.status
                self._save_manifest(store, manifest)
                store.write_text(
                    "07_review/stall_report.md",
                    "Lean toolchain is unavailable, so the run stopped before proving the compile gate.\n\n"
                    "Install Lean via elan, then resume the run or rerun the example.\n",
                )
                return manifest

            manifest.current_stage = RunStage.REPAIRING
            manifest.latest_error = compile_result.stderr.strip() or compile_result.status
            self._save_manifest(store, manifest)
            previous_result = compile_result

        manifest.current_stage = RunStage.AWAITING_STALL_REVIEW
        manifest.latest_error = previous_result.stderr.strip() if previous_result else "Unknown failure."
        self._save_manifest(store, manifest)
        store.write_text(
            "07_review/stall_report.md",
            "The compile loop hit the retry cap.\n\n"
            "Next action should be one of:\n"
            "- revise the theorem spec\n"
            "- revise the formalization plan\n"
            "- allow one more targeted repair attempt\n",
        )
        return manifest

    def _build_context_pack(self, store: RunStore, theorem_spec: TheoremSpec) -> ContextPack:
        context_pack = ContextPack(
            recommended_imports=["FormalizationEngineWorkspace.Basic"],
            local_examples=["examples/inputs/zero_add.md"],
            notes=[
                f"Title: {theorem_spec.title}",
                "Start from repo-local examples before adding retrieval or external corpora.",
            ],
        )
        store.write_json("03_context/context_pack.json", context_pack)
        return context_pack

    def _queue_final_review(
        self,
        store: RunStore,
        manifest: RunManifest,
        draft: LeanDraft,
        auto_approve: bool,
    ) -> RunManifest:
        candidate_relative_path = "08_final/final_candidate.lean"
        store.write_text(candidate_relative_path, draft.content)
        store.write_text(
            "08_final/final_report.md",
            "Candidate Lean file passed the compile gate and the no-`sorry` quality check.\n",
        )
        store.write_json(
            "08_final/provenance.json",
            {
                "agent_name": self.agent.name,
                "candidate_path": candidate_relative_path,
                "generated_at": utc_now(),
            },
        )
        if auto_approve:
            self._seed_final_approval(store)
        if not store.exists("08_final/decision.json"):
            manifest.current_stage = RunStage.AWAITING_FINAL_REVIEW
            manifest.final_output_path = candidate_relative_path
            return self._save_manifest(store, manifest)
        return self._complete_from_candidate(store, manifest)

    def _complete_from_candidate(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        candidate_relative_path = "08_final/final_candidate.lean"
        final_relative_path = "08_final/final.lean"
        candidate_path = store.path(candidate_relative_path)
        store.write_text(
            final_relative_path,
            candidate_path.read_text(encoding="utf-8"),
        )
        manifest.current_stage = RunStage.COMPLETED
        manifest.updated_at = utc_now()
        manifest.final_output_path = final_relative_path
        manifest.latest_error = None
        return self._save_manifest(store, manifest)

    def _seed_spec_approval(self, store: RunStore) -> None:
        payload = store.read_json("02_spec/theorem_spec.json")
        store.write_json("02_spec/theorem_spec.approved.json", payload)
        store.write_json(
            "02_spec/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes="Auto-approved."),
        )

    def _seed_plan_approval(self, store: RunStore) -> None:
        payload = store.read_json("04_plan/formalization_plan.json")
        store.write_json("04_plan/formalization_plan.approved.json", payload)
        store.write_json(
            "04_plan/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes="Auto-approved."),
        )

    def _seed_final_approval(self, store: RunStore) -> None:
        store.write_json(
            "08_final/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes="Auto-approved."),
        )

    def _write_agent_turn(self, store: RunStore, stage_dir: str, turn, parsed_output) -> None:
        store.write_json(f"{stage_dir}/request.json", turn.request_payload)
        store.write_text(f"{stage_dir}/prompt.md", turn.prompt)
        store.write_json(f"{stage_dir}/raw_response.json", {"raw_response": turn.raw_response})
        store.write_json(f"{stage_dir}/parsed_output.json", parsed_output)

    def _write_attempt(self, store: RunStore, attempt: int, turn, draft: LeanDraft) -> None:
        attempt_dir = f"05_draft/attempt_{attempt:04d}"
        self._write_agent_turn(store, attempt_dir, turn, draft)
        store.write_text(f"{attempt_dir}/draft.lean", draft.content)

    def _write_compile_result(self, store: RunStore, attempt: int, compile_result: CompileAttempt) -> None:
        attempt_dir = f"06_compile/attempt_{attempt:04d}"
        store.write_json(f"{attempt_dir}/result.json", compile_result)
        store.write_text(f"{attempt_dir}/stdout.txt", compile_result.stdout)
        store.write_text(f"{attempt_dir}/stderr.txt", compile_result.stderr)
        store.write_json(
            f"{attempt_dir}/quality_gate.json",
            {
                "passed": compile_result.quality_gate_passed,
                "checks": ["no_sorry_literals"],
            },
        )

    def _save_manifest(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        manifest.updated_at = utc_now()
        store.write_json("manifest.json", manifest)
        return manifest

    def _load_manifest(self, store: RunStore) -> RunManifest:
        payload = store.read_json("manifest.json")
        return RunManifest(
            run_id=payload["run_id"],
            source=SourceRef(
                path=payload["source"]["path"],
                kind=SourceKind(payload["source"]["kind"]),
            ),
            agent_name=payload["agent_name"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            current_stage=RunStage(payload["current_stage"]),
            attempt_count=payload.get("attempt_count", 0),
            latest_error=payload.get("latest_error"),
            final_output_path=payload.get("final_output_path"),
        )

    def _load_theorem_spec(self, store: RunStore, approved: bool) -> TheoremSpec:
        filename = (
            "02_spec/theorem_spec.approved.json"
            if approved
            else "02_spec/theorem_spec.json"
        )
        payload = store.read_json(filename)
        return TheoremSpec(**payload)

    def _load_plan(self, store: RunStore, approved: bool) -> FormalizationPlan:
        filename = (
            "04_plan/formalization_plan.approved.json"
            if approved
            else "04_plan/formalization_plan.json"
        )
        payload = store.read_json(filename)
        return FormalizationPlan(**payload)
