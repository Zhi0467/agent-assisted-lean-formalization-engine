from __future__ import annotations

import shlex
from pathlib import Path

from .agents import FormalizationAgent
from .ingest import ingest_source
from .lean_runner import LeanRunner
from .models import (
    AgentConfig,
    AgentTurn,
    BackendStage,
    CompileAttempt,
    DEFAULT_WORKFLOW_TAGS,
    DEFAULT_WORKFLOW_VERSION,
    NaturalLanguageProofStatus,
    ReviewDecision,
    RunManifest,
    RunStage,
    SourceKind,
    SourceRef,
    StageRequest,
    utc_now,
)
from .storage import RunStore
from .template_manager import _is_eligible_template, discover_workspace_template, resolve_workspace_template

ENRICHMENT_DIR = "01_enrichment"
PLAN_DIR = "02_plan"
PROOF_DIR = "03_proof"
FINAL_DIR = "04_final"

ENRICHMENT_HANDOFF = f"{ENRICHMENT_DIR}/handoff.md"
ENRICHMENT_PROOF_STATUS = f"{ENRICHMENT_DIR}/proof_status.json"
ENRICHMENT_NATURAL_LANGUAGE_STATEMENT = f"{ENRICHMENT_DIR}/natural_language_statement.md"
ENRICHMENT_NATURAL_LANGUAGE_PROOF = f"{ENRICHMENT_DIR}/natural_language_proof.md"
PLAN_HANDOFF = f"{PLAN_DIR}/handoff.md"
PROOF_BLOCKER = f"{PROOF_DIR}/blocker.md"
PROOF_LOOP = f"{PROOF_DIR}/loop.md"
FINAL_CANDIDATE = f"{FINAL_DIR}/final_candidate.lean"
ATTEMPT_WALKTHROUGH = "walkthrough.md"
ATTEMPT_READABLE_CANDIDATE = "readable_candidate.lean"
ATTEMPT_ERROR_REPORT = "error.md"
ATTEMPT_REVIEW_OUTPUTS = [
    ATTEMPT_WALKTHROUGH,
    ATTEMPT_READABLE_CANDIDATE,
    ATTEMPT_ERROR_REPORT,
]

LEGACY_ENRICHMENT_DIR = "03_enrichment"
LEGACY_SPEC_DIR = "04_spec"
LEGACY_PLAN_DIR = "06_plan"
LEGACY_STALL_DIR = "09_review"
LEGACY_FINAL_DIR = "10_final"

LEGACY_DEMO_AGENT_NAMES = {
    "demo_zero_add_agent",
    "repair_resume_agent",
}


class FormalizationWorkflow:
    def __init__(
        self,
        repo_root: Path,
        agent: FormalizationAgent,
        agent_config: AgentConfig,
        lean_runner: LeanRunner | None = None,
        *,
        max_attempts: int = 3,
        terry_command: str = "terry",
    ):
        self.repo_root = repo_root
        self.agent = agent
        self.agent_config = agent_config
        self.max_attempts = max_attempts
        self.terry_command = terry_command
        self.artifacts_root = repo_root / "artifacts"
        self.lean_runner = lean_runner or LeanRunner(
            repo_root / "lean_workspace_template",
            repo_root=repo_root,
        )

    def prove(self, source_path: Path, run_id: str, auto_approve: bool = False) -> RunManifest:
        store = RunStore(self.artifacts_root, run_id)
        source_ref, ingested = ingest_source(source_path, repo_root=self.repo_root)
        store.ensure_new()

        manifest = RunManifest(
            run_id=run_id,
            source=source_ref,
            agent_name=self.agent.name,
            agent_config=self.agent_config,
            template_dir=str(self.lean_runner.template_dir.resolve()),
            created_at=utc_now(),
            updated_at=utc_now(),
            current_stage=RunStage.CREATED,
            lake_path=self._persisted_lake_path(),
        )
        self._save_manifest(store, manifest)

        store.write_text("00_input/source.txt", ingested.raw_text)
        store.write_text("00_input/normalized.md", ingested.normalized_text)
        store.write_json(
            "00_input/provenance.json",
            {
                "source": source_ref,
                "extraction_method": ingested.extraction_method,
            },
        )
        store.append_log(
            "run_started",
            f"Started run `{run_id}` from `{source_ref.path}`.",
            stage="input",
            details={
                "agent": self.agent.name,
                "template_dir": manifest.template_dir,
            },
        )
        return self._resume_from_created(store, manifest, auto_approve=auto_approve)

    def resume(self, run_id: str, auto_approve: bool = False) -> RunManifest:
        store = RunStore(self.artifacts_root, run_id)
        manifest = self._load_manifest(store)
        if manifest.agent_config.backend != self.agent_config.backend:
            raise ValueError(
                "Paused Terry runs keep the backend recorded in the manifest. "
                f"This run uses `{manifest.agent_config.backend}`."
            )
        if (
            manifest.agent_config.backend != "command"
            and manifest.agent_config != self.agent_config
        ):
            raise ValueError(
                "Paused Terry runs keep the backend configuration recorded in the manifest."
            )
        if (
            manifest.agent_config.backend == "command"
            and self.agent_config.command
            and manifest.agent_config.command != self.agent_config.command
        ):
            manifest.agent_config = self.agent_config
            manifest.agent_name = self.agent.name
            self._save_manifest(store, manifest)
        if self.lean_runner.lake_path is None and manifest.lake_path is not None:
            self.lean_runner.lake_path = manifest.lake_path
        persisted_lake_path = self._persisted_lake_path()
        if persisted_lake_path is not None and persisted_lake_path != manifest.lake_path:
            manifest.lake_path = persisted_lake_path
            self._save_manifest(store, manifest)

        store.append_log(
            "resume_requested",
            f"Resume requested while run is in `{manifest.current_stage.value}`.",
            stage=manifest.current_stage.value,
        )

        if manifest.current_stage == RunStage.CREATED:
            return self._resume_from_created(store, manifest, auto_approve=auto_approve)

        if manifest.current_stage == RunStage.LEGACY_AWAITING_ENRICHMENT_REVIEW:
            decision = self._resolve_checkpoint_decision(
                store,
                LEGACY_ENRICHMENT_DIR,
                continue_decision="approve",
                auto_approve=auto_approve,
            )
            if decision is None or decision.decision != "approve":
                return self._pause_for_legacy_enrichment(store, manifest)
            store.append_log(
                "checkpoint_approved",
                "Legacy enrichment checkpoint approved.",
                stage="enrichment",
                details={"notes": decision.notes},
            )
            return self._run_plan_stage(
                store,
                manifest,
                auto_approve=auto_approve,
                review_notes_relative_path=f"{LEGACY_ENRICHMENT_DIR}/review.md",
                allow_missing_proof=True,
            )

        if manifest.current_stage == RunStage.LEGACY_AWAITING_SPEC_REVIEW:
            decision = self._resolve_checkpoint_decision(
                store,
                LEGACY_SPEC_DIR,
                continue_decision="approve",
                auto_approve=auto_approve,
            )
            if decision is None or decision.decision != "approve":
                return self._pause_for_legacy_spec_review(store, manifest)
            store.append_log(
                "checkpoint_approved",
                "Legacy spec checkpoint approved.",
                stage="plan",
                details={"notes": decision.notes},
            )
            return self._run_plan_stage(
                store,
                manifest,
                auto_approve=auto_approve,
                review_notes_relative_path=f"{LEGACY_SPEC_DIR}/review.md",
                allow_missing_proof=True,
            )

        if manifest.current_stage == RunStage.LEGACY_AWAITING_PLAN_REVIEW:
            decision = self._resolve_checkpoint_decision(
                store,
                LEGACY_PLAN_DIR,
                continue_decision="approve",
                auto_approve=auto_approve,
            )
            if decision is None or decision.decision != "approve":
                return self._pause_for_legacy_plan_review(store, manifest)
            store.append_log(
                "checkpoint_approved",
                "Legacy plan checkpoint approved.",
                stage="plan",
                details={"notes": decision.notes},
            )
            return self._prove_loop(
                store,
                manifest,
                auto_approve=auto_approve,
                review_notes_relative_path=f"{LEGACY_PLAN_DIR}/review.md",
            )

        if manifest.current_stage == RunStage.AWAITING_ENRICHMENT_APPROVAL:
            decision = self._resolve_checkpoint_decision(
                store,
                ENRICHMENT_DIR,
                continue_decision="approve",
                auto_approve=auto_approve,
            )
            if decision is None:
                if self._checkpoint_surface_missing(store, ENRICHMENT_DIR):
                    return self._pause_for_enrichment(store, manifest)
                return manifest
            if decision.decision == "reject":
                store.append_log(
                    "checkpoint_rejected",
                    "Enrichment checkpoint rejected; Terry is rerunning enrichment.",
                    stage="enrichment",
                    details={"notes": decision.notes},
                )
                return self._run_enrichment_stage(
                    store,
                    manifest,
                    auto_approve=auto_approve,
                    review_notes_relative_path=f"{ENRICHMENT_DIR}/review.md",
                )
            store.append_log(
                "checkpoint_approved",
                "Enrichment checkpoint approved.",
                stage="enrichment",
                details={"notes": decision.notes},
            )
            return self._run_plan_stage(
                store,
                manifest,
                auto_approve=auto_approve,
                review_notes_relative_path=f"{ENRICHMENT_DIR}/review.md",
            )

        if manifest.current_stage == RunStage.AWAITING_PLAN_APPROVAL:
            decision = self._resolve_checkpoint_decision(
                store,
                PLAN_DIR,
                continue_decision="approve",
                auto_approve=auto_approve,
            )
            if decision is None:
                if self._checkpoint_surface_missing(store, PLAN_DIR):
                    return self._pause_for_plan(store, manifest)
                return manifest
            if decision.decision == "reject":
                store.append_log(
                    "checkpoint_rejected",
                    "Plan checkpoint rejected; Terry is rerunning the plan stage.",
                    stage="plan",
                    details={"notes": decision.notes},
                )
                return self._run_plan_stage(
                    store,
                    manifest,
                    auto_approve=auto_approve,
                    review_notes_relative_path=f"{PLAN_DIR}/review.md",
                    force_rerun=True,
                )
            store.append_log(
                "checkpoint_approved",
                "Plan checkpoint approved.",
                stage="plan",
                details={"notes": decision.notes},
            )
            return self._prove_loop(
                store,
                manifest,
                auto_approve=auto_approve,
                review_notes_relative_path=f"{PLAN_DIR}/review.md",
            )

        if manifest.current_stage == RunStage.PROVING:
            latest_compile_path = (
                self._attempt_result_path(manifest.attempt_count)
                if manifest.attempt_count > 0
                else None
            )
            latest_candidate_path = (
                f"{PROOF_DIR}/attempts/attempt_{manifest.attempt_count:04d}/candidate.lean"
                if manifest.attempt_count > 0
                else None
            )
            if (
                latest_compile_path
                and latest_candidate_path
                and store.exists(latest_compile_path)
                and store.exists(latest_candidate_path)
            ):
                latest_compile = self._load_compile_attempt(store, latest_compile_path)
                if latest_compile.passed:
                    return self._queue_final_review(
                        store,
                        manifest,
                        latest_candidate_path,
                        latest_compile,
                        auto_approve=auto_approve,
            )
            if store.exists(FINAL_CANDIDATE):
                decision = self._resolve_checkpoint_decision(
                    store,
                    FINAL_DIR,
                    continue_decision="approve",
                    auto_approve=auto_approve,
                )
                if decision is not None and decision.decision == "approve":
                    return self._complete_from_candidate(store, manifest)
                return self._pause_for_final(store, manifest)
            return self._prove_loop(store, manifest, auto_approve=auto_approve)

        if manifest.current_stage == RunStage.LEGACY_REPAIRING:
            return self._prove_loop(store, manifest, auto_approve=auto_approve)

        if manifest.current_stage == RunStage.PROOF_BLOCKED:
            raise ValueError(
                f"Run `{run_id}` is proof-blocked after {manifest.attempt_count} attempt(s). "
                "Use `terry retry` to grant more prove-and-repair budget:\n\n"
                f"  terry retry {run_id} --attempts 3"
            )

        if manifest.current_stage == RunStage.LEGACY_AWAITING_STALL_REVIEW:
            raise ValueError(
                f"Run `{run_id}` is proof-blocked (legacy stall) after {manifest.attempt_count} attempt(s). "
                "Use `terry retry` to grant more prove-and-repair budget:\n\n"
                f"  terry retry {run_id} --attempts 3"
            )

        if manifest.current_stage == RunStage.AWAITING_FINAL_APPROVAL:
            decision = self._resolve_checkpoint_decision(
                store,
                FINAL_DIR,
                continue_decision="approve",
                auto_approve=auto_approve,
            )
            if decision is None or decision.decision != "approve":
                if self._checkpoint_surface_missing(store, FINAL_DIR):
                    return self._pause_for_final(store, manifest)
                return manifest
            store.append_log(
                "checkpoint_approved",
                "Final checkpoint approved.",
                stage="final",
                details={"notes": decision.notes},
            )
            return self._complete_from_candidate(store, manifest)

        if manifest.current_stage == RunStage.LEGACY_AWAITING_FINAL_REVIEW:
            decision = self._resolve_checkpoint_decision(
                store,
                LEGACY_FINAL_DIR,
                continue_decision="approve",
                auto_approve=auto_approve,
            )
            if decision is None or decision.decision != "approve":
                return self._pause_for_legacy_final_review(store, manifest)
            store.append_log(
                "checkpoint_approved",
                "Legacy final checkpoint approved.",
                stage="final",
                details={"notes": decision.notes},
            )
            return self._complete_from_candidate(store, manifest)

        return manifest

    def retry(self, run_id: str, extra_attempts: int = 3, auto_approve: bool = False) -> RunManifest:
        store = RunStore(self.artifacts_root, run_id)
        manifest = self._load_manifest(store)

        blocked_stages = {
            RunStage.PROOF_BLOCKED,
            RunStage.LEGACY_AWAITING_STALL_REVIEW,
        }
        if manifest.current_stage not in blocked_stages:
            raise ValueError(
                f"Run `{run_id}` is in `{manifest.current_stage.value}`, not proof-blocked. "
                "`terry retry` only works on runs that exhausted their prove-and-repair budget."
            )
        if extra_attempts < 1:
            raise ValueError("--attempts must be at least 1.")

        review_notes_relative_path: str | None = None
        if manifest.current_stage == RunStage.PROOF_BLOCKED:
            review_notes_relative_path = f"{PROOF_DIR}/review.md"
        elif manifest.current_stage == RunStage.LEGACY_AWAITING_STALL_REVIEW:
            review_notes_relative_path = f"{LEGACY_STALL_DIR}/review.md"

        store.append_log(
            "proof_retry_approved",
            f"Human approved {extra_attempts} more prove-and-repair attempt(s) via `terry retry`.",
            stage="proof",
            details={"extra_attempts": extra_attempts},
        )

        return self._prove_loop(
            store,
            manifest,
            auto_approve=auto_approve,
            max_attempts=manifest.attempt_count + extra_attempts,
            review_notes_relative_path=review_notes_relative_path,
        )

    def status(self, run_id: str) -> RunManifest:
        store = RunStore(self.artifacts_root, run_id)
        return self._load_manifest(store)

    def review_attempt(self, run_id: str, attempt: int | None = None) -> int:
        store = RunStore(self.artifacts_root, run_id)
        manifest = self._load_manifest(store)
        selected_attempt = attempt or manifest.attempt_count
        if selected_attempt <= 0:
            raise ValueError("Terry review needs a completed proof attempt.")
        self._run_attempt_review(store, manifest, selected_attempt)
        return selected_attempt

    def _resume_from_created(
        self,
        store: RunStore,
        manifest: RunManifest,
        *,
        auto_approve: bool,
    ) -> RunManifest:
        if self._turn_artifacts_ready(
            store,
            FINAL_DIR,
            ["final_candidate.lean", "compile_result.json", "provenance.json"],
        ):
            decision = self._resolve_checkpoint_decision(
                store,
                FINAL_DIR,
                continue_decision="approve",
                auto_approve=auto_approve,
            )
            if decision is not None and decision.decision == "approve":
                return self._complete_from_candidate(store, manifest)
            return self._pause_for_final(store, manifest)

        if self._turn_artifacts_ready(store, PLAN_DIR, ["handoff.md"]):
            decision = self._resolve_checkpoint_decision(
                store,
                PLAN_DIR,
                continue_decision="approve",
                auto_approve=auto_approve,
            )
            if decision is not None and decision.decision == "approve":
                return self._prove_loop(
                    store,
                    manifest,
                    auto_approve=auto_approve,
                    review_notes_relative_path=f"{PLAN_DIR}/review.md",
                )
            if decision is not None and decision.decision == "reject":
                return self._run_plan_stage(
                    store,
                    manifest,
                    auto_approve=auto_approve,
                    review_notes_relative_path=f"{PLAN_DIR}/review.md",
                    force_rerun=True,
                )
            return self._pause_for_plan(store, manifest)

        if self._enrichment_stage_ready(store):
            decision = self._resolve_checkpoint_decision(
                store,
                ENRICHMENT_DIR,
                continue_decision="approve",
                auto_approve=auto_approve,
            )
            if decision is not None and decision.decision == "approve":
                return self._run_plan_stage(
                    store,
                    manifest,
                    auto_approve=auto_approve,
                    review_notes_relative_path=f"{ENRICHMENT_DIR}/review.md",
                )
            if decision is not None and decision.decision == "reject":
                return self._run_enrichment_stage(
                    store,
                    manifest,
                    auto_approve=auto_approve,
                    review_notes_relative_path=f"{ENRICHMENT_DIR}/review.md",
                )
            return self._pause_for_enrichment(store, manifest)

        return self._run_enrichment_stage(store, manifest, auto_approve=auto_approve)

    def _run_enrichment_stage(
        self,
        store: RunStore,
        manifest: RunManifest,
        *,
        auto_approve: bool,
        review_notes_relative_path: str | None = None,
    ) -> RunManifest:
        request = self._build_stage_request(
            store,
            manifest,
            stage=BackendStage.ENRICHMENT,
            output_dir=ENRICHMENT_DIR,
            required_outputs=["handoff.md", "proof_status.json", "natural_language_statement.md"],
            review_notes_relative_path=review_notes_relative_path,
        )
        self._run_backend_stage(store, request, ENRICHMENT_DIR)
        proof_status = self._load_proof_status(store)
        if proof_status is None:
            raise RuntimeError("Enrichment stage did not write a valid `01_enrichment/proof_status.json`.")
        if not store.exists(ENRICHMENT_NATURAL_LANGUAGE_STATEMENT):
            raise RuntimeError("Enrichment stage did not write `01_enrichment/natural_language_statement.md`.")
        if not proof_status.obtained and store.exists(ENRICHMENT_NATURAL_LANGUAGE_PROOF):
            store.path(ENRICHMENT_NATURAL_LANGUAGE_PROOF).unlink()
        if proof_status.obtained and not store.exists(ENRICHMENT_NATURAL_LANGUAGE_PROOF):
            raise RuntimeError(
                "Enrichment reported that a natural-language proof was obtained, but "
                "`01_enrichment/natural_language_proof.md` is missing."
            )
        store.append_log(
            "enrichment_ready",
            "Prepared the backend-owned enrichment handoff.",
            stage="enrichment",
            details={
                "natural_language_proof_obtained": proof_status.obtained,
                "proof_source": proof_status.source,
            },
        )
        self._reset_checkpoint_surface(store, ENRICHMENT_DIR)

        if auto_approve and proof_status.obtained:
            self._write_decision(
                store,
                ENRICHMENT_DIR,
                ReviewDecision("approve", utc_now(), "Auto-approved."),
            )
            store.append_log(
                "checkpoint_approved",
                "Enrichment checkpoint auto-approved.",
                stage="enrichment",
            )
            return self._run_plan_stage(
                store,
                manifest,
                auto_approve=auto_approve,
                review_notes_relative_path=f"{ENRICHMENT_DIR}/review.md",
            )
        return self._pause_for_enrichment(store, manifest)

    def _run_plan_stage(
        self,
        store: RunStore,
        manifest: RunManifest,
        *,
        auto_approve: bool,
        review_notes_relative_path: str | None = None,
        force_rerun: bool = False,
        allow_missing_proof: bool = False,
    ) -> RunManifest:
        if not allow_missing_proof and not self._natural_language_proof_ready(store):
            raise RuntimeError(
                "Terry cannot start the plan stage without `01_enrichment/natural_language_statement.md`, "
                "`01_enrichment/natural_language_proof.md`, and `01_enrichment/proof_status.json` "
                "reporting `obtained: true`."
            )

        if not force_rerun and self._turn_artifacts_ready(store, PLAN_DIR, ["handoff.md"]):
            store.append_log(
                "plan_reused",
                "Reused the existing backend-owned plan handoff.",
                stage="plan",
            )
        else:
            request = self._build_stage_request(
                store,
                manifest,
                stage=BackendStage.PLAN,
                output_dir=PLAN_DIR,
                required_outputs=["handoff.md"],
                review_notes_relative_path=review_notes_relative_path,
            )
            self._run_backend_stage(store, request, PLAN_DIR)
            store.append_log(
                "plan_ready",
                "Prepared the backend-owned plan handoff.",
                stage="plan",
            )
            self._reset_checkpoint_surface(store, PLAN_DIR)

        if auto_approve:
            self._write_decision(
                store,
                PLAN_DIR,
                ReviewDecision("approve", utc_now(), "Auto-approved."),
            )
            store.append_log(
                "checkpoint_approved",
                "Plan checkpoint auto-approved.",
                stage="plan",
            )
            return self._prove_loop(
                store,
                manifest,
                auto_approve=auto_approve,
                review_notes_relative_path=f"{PLAN_DIR}/review.md",
            )
        return self._pause_for_plan(store, manifest)

    def _prove_loop(
        self,
        store: RunStore,
        manifest: RunManifest,
        *,
        auto_approve: bool,
        max_attempts: int | None = None,
        review_notes_relative_path: str | None = None,
    ) -> RunManifest:
        manifest = self._load_manifest(store)
        manifest = self._ensure_workspace_template(store, manifest)
        manifest.current_stage = RunStage.PROVING
        self._save_manifest(store, manifest)
        attempt_limit = max_attempts or self.max_attempts

        store.append_log(
            "prove_loop_started",
            "Started the bounded prove-and-repair loop.",
            stage="proof",
            details={
                "attempt_count": manifest.attempt_count,
                "max_attempts": attempt_limit,
            },
        )

        while manifest.attempt_count < attempt_limit:
            attempt = manifest.attempt_count + 1
            candidate_relative_path = f"{PROOF_DIR}/attempts/attempt_{attempt:04d}/candidate.lean"
            compile_relative_path = f"{PROOF_DIR}/attempts/attempt_{attempt:04d}/compile_result.json"
            previous_attempt = attempt - 1 if attempt > 1 else None
            previous_compile_relative = (
                f"{PROOF_DIR}/attempts/attempt_{previous_attempt:04d}/compile_result.json"
                if previous_attempt is not None
                else None
            )
            previous_attempt_dir = (
                f"{PROOF_DIR}/attempts/attempt_{previous_attempt:04d}"
                if previous_attempt is not None
                else None
            )

            store.append_log(
                "prove_attempt_started",
                f"Starting proof attempt {attempt} of {attempt_limit}.",
                stage="proof",
                details={"attempt": attempt},
            )

            attempt_dir = f"{PROOF_DIR}/attempts/attempt_{attempt:04d}"
            if not self._turn_artifacts_ready(store, attempt_dir, ["candidate.lean"]):
                request = self._build_stage_request(
                    store,
                    manifest,
                    stage=BackendStage.PROOF,
                    output_dir=attempt_dir,
                    required_outputs=["candidate.lean"],
                    review_notes_relative_path=review_notes_relative_path,
                    latest_compile_result_path=previous_compile_relative,
                    previous_attempt_dir=previous_attempt_dir,
                    attempt=attempt,
                    max_attempts=attempt_limit,
                )
                self._run_backend_stage(
                    store,
                    request,
                    attempt_dir,
                )
            else:
                store.append_log(
                    "prove_attempt_resumed",
                    f"Found an existing candidate for attempt {attempt}; compiling it now.",
                    stage="proof",
                    details={"attempt": attempt},
                )

            compile_result = self.lean_runner.compile_candidate(store, candidate_relative_path, attempt)
            self._write_compile_result(store, attempt, compile_result)
            manifest.attempt_count = attempt
            manifest.updated_at = utc_now()
            self._save_manifest(store, manifest)
            self._run_attempt_review(
                store,
                manifest,
                attempt,
                review_notes_relative_path=review_notes_relative_path,
                max_attempts=attempt_limit,
            )

            if compile_result.passed:
                manifest.latest_error = None
                self._save_manifest(store, manifest)
                store.append_log(
                    "prove_attempt_passed",
                    f"Attempt {attempt} compiled successfully.",
                    stage="proof",
                    details={"attempt": attempt},
                )
                return self._queue_final_review(
                    store,
                    manifest,
                    candidate_relative_path,
                    compile_result,
                    auto_approve=auto_approve,
                )

            if compile_result.missing_toolchain:
                manifest.latest_error = compile_result.stderr.strip() or compile_result.status
                self._save_manifest(store, manifest)
                store.append_log(
                    "prove_loop_blocked",
                    "Proof loop stopped because the Lean toolchain is unavailable.",
                    stage="proof",
                    details={"attempt": attempt},
                )
                return self._pause_for_proof_blocked(
                    store,
                    manifest,
                    reason=(
                        "Lean toolchain is unavailable, so Terry could not continue the proof loop.\n\n"
                        "Fix the toolchain, then run `terry retry <run_id>` to grant more attempts."
                    ),
                )

            manifest.latest_error = compile_result.stderr.strip() or compile_result.status
            self._save_manifest(store, manifest)
            review_notes_relative_path = None
            store.append_log(
                "prove_attempt_failed",
                f"Attempt {attempt} failed and Terry is trying the next repair step.",
                stage="proof",
                details={"attempt": attempt, "status": compile_result.status},
            )

        manifest.latest_error = self._latest_attempt_error(store, manifest.attempt_count)
        self._save_manifest(store, manifest)
        store.append_log(
            "prove_loop_blocked",
            "Proof loop hit the retry cap and paused for human input.",
            stage="proof",
            details={"attempt_count": manifest.attempt_count},
        )
        return self._pause_for_proof_blocked(
            store,
            manifest,
            reason=(
                "The prove-and-repair loop hit the retry cap.\n\n"
                "To grant more attempts, run `terry retry <run_id> --attempts N`.\n"
                "Add any guidance in the `03_proof/review.md` notes before retrying."
            ),
        )

    def _run_backend_stage(
        self,
        store: RunStore,
        request: StageRequest,
        turn_dir: str,
    ) -> AgentTurn:
        self._clear_turn_artifacts(
            store,
            turn_dir,
            request.required_outputs,
            clear_compile_outputs=request.stage == BackendStage.PROOF,
        )
        turn = self.agent.run_stage(request)
        store.write_json(f"{turn_dir}/request.json", turn.request_payload)
        store.write_text(f"{turn_dir}/prompt.md", turn.prompt)
        store.write_text(f"{turn_dir}/response.txt", turn.raw_response)

        missing = [
            required_output
            for required_output in request.required_outputs
            if not (self.repo_root / request.output_dir / required_output).exists()
        ]
        if missing:
            raise RuntimeError(
                "Backend did not write the required Terry output(s): "
                + ", ".join(f"{request.output_dir}/{path}" for path in missing)
            )
        return turn

    def _queue_final_review(
        self,
        store: RunStore,
        manifest: RunManifest,
        candidate_relative_path: str,
        compile_result: CompileAttempt,
        *,
        auto_approve: bool,
    ) -> RunManifest:
        store.write_text(FINAL_CANDIDATE, store.read_text(candidate_relative_path))
        store.write_json(f"{FINAL_DIR}/compile_result.json", compile_result)
        store.write_json(
            f"{FINAL_DIR}/provenance.json",
            {
                "agent_name": self.agent.name,
                "candidate_path": candidate_relative_path,
                "generated_at": utc_now(),
                "attempt": manifest.attempt_count,
            },
        )
        store.append_log(
            "final_candidate_ready",
            "Generated a compiling Lean candidate for final review.",
            stage="final",
            details={"attempt_count": manifest.attempt_count},
        )

        if auto_approve:
            self._write_decision(
                store,
                FINAL_DIR,
                ReviewDecision("approve", utc_now(), "Auto-approved."),
            )
            return self._complete_from_candidate(store, manifest)
        return self._pause_for_final(store, manifest)

    def _complete_from_candidate(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        candidate_relative_path = self._first_existing_path(
            store,
            FINAL_CANDIDATE,
            f"{LEGACY_FINAL_DIR}/final_candidate.lean",
        )
        if candidate_relative_path is None:
            raise FileNotFoundError("Missing final Lean candidate for completion.")
        final_relative_path = f"{FINAL_DIR}/final.lean"
        store.write_text(final_relative_path, store.read_text(candidate_relative_path))
        manifest.current_stage = RunStage.COMPLETED
        manifest.updated_at = utc_now()
        manifest.final_output_path = final_relative_path
        manifest.latest_error = None
        self._save_manifest(store, manifest)
        store.append_log(
            "run_completed",
            "Final Lean file approved and written to disk.",
            stage="final",
            details={"final_output_path": final_relative_path},
        )
        return manifest

    def _pause_for_enrichment(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        proof_status = self._load_proof_status(store)
        summary = "Terry is waiting for enrichment approval before locking the formalization scope."
        if proof_status is not None and not proof_status.obtained:
            summary = (
                "Terry still needs an existing natural-language proof before it can open the plan stage. "
                "Use the enrichment review notes to supply that proof or point Terry at it, then rerun enrichment."
            )
        artifact_paths = [
            ENRICHMENT_HANDOFF,
            ENRICHMENT_PROOF_STATUS,
            ENRICHMENT_NATURAL_LANGUAGE_STATEMENT,
        ]
        if store.exists(ENRICHMENT_NATURAL_LANGUAGE_PROOF):
            artifact_paths.append(ENRICHMENT_NATURAL_LANGUAGE_PROOF)
        return self._pause_for_checkpoint(
            store,
            manifest,
            stage=RunStage.AWAITING_ENRICHMENT_APPROVAL,
            stage_dir=ENRICHMENT_DIR,
            title="Enrichment Approval",
            summary=summary,
            artifact_paths=artifact_paths,
            continue_decision="approve",
        )

    def _pause_for_legacy_enrichment(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        return self._pause_for_checkpoint(
            store,
            manifest,
            stage=RunStage.LEGACY_AWAITING_ENRICHMENT_REVIEW,
            stage_dir=LEGACY_ENRICHMENT_DIR,
            title="Legacy Enrichment Review",
            summary="This run paused in the legacy enrichment checkpoint before Terry's new handoff layout.",
            artifact_paths=self._legacy_artifact_paths(
                store,
                f"{LEGACY_ENRICHMENT_DIR}/handoff.md",
                f"{LEGACY_ENRICHMENT_DIR}/enrichment_report.json",
                f"{LEGACY_ENRICHMENT_DIR}/enrichment_report.approved.json",
            ),
            continue_decision="approve",
        )

    def _pause_for_plan(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        return self._pause_for_checkpoint(
            store,
            manifest,
            stage=RunStage.AWAITING_PLAN_APPROVAL,
            stage_dir=PLAN_DIR,
            title="Plan Approval",
            summary="Terry is waiting for the merged plan approval before starting the prove-and-repair loop.",
            artifact_paths=[PLAN_HANDOFF],
            continue_decision="approve",
        )

    def _pause_for_legacy_spec_review(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        return self._pause_for_checkpoint(
            store,
            manifest,
            stage=RunStage.LEGACY_AWAITING_SPEC_REVIEW,
            stage_dir=LEGACY_SPEC_DIR,
            title="Legacy Spec Review",
            summary="This run paused in the legacy theorem-spec checkpoint before Terry's merged plan handoff.",
            artifact_paths=self._legacy_artifact_paths(
                store,
                f"{LEGACY_SPEC_DIR}/theorem_spec.approved.json",
                f"{LEGACY_SPEC_DIR}/theorem_spec.json",
            ),
            continue_decision="approve",
        )

    def _pause_for_legacy_plan_review(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        return self._pause_for_checkpoint(
            store,
            manifest,
            stage=RunStage.LEGACY_AWAITING_PLAN_REVIEW,
            stage_dir=LEGACY_PLAN_DIR,
            title="Legacy Plan Review",
            summary="This run paused in the legacy plan checkpoint before Terry's new `02_plan/` handoff layout.",
            artifact_paths=self._legacy_artifact_paths(
                store,
                f"{LEGACY_PLAN_DIR}/formalization_plan.approved.json",
                f"{LEGACY_PLAN_DIR}/formalization_plan.json",
            ),
            continue_decision="approve",
        )

    def _pause_for_proof_blocked(
        self,
        store: RunStore,
        manifest: RunManifest,
        *,
        reason: str,
    ) -> RunManifest:
        store.write_text(PROOF_BLOCKER, self._render_proof_blocker(reason))
        if manifest.attempt_count > 0:
            store.write_text(PROOF_LOOP, self._render_loop_summary(store, manifest.attempt_count))
        artifact_paths = [PROOF_BLOCKER]
        if manifest.attempt_count > 0:
            artifact_paths.extend(
                [
                    PROOF_LOOP,
                    self._attempt_result_path(manifest.attempt_count),
                ]
            )
            artifact_paths.extend(self._existing_attempt_review_artifacts(store, manifest.attempt_count))
        return self._pause_for_checkpoint(
            store,
            manifest,
            stage=RunStage.PROOF_BLOCKED,
            stage_dir=PROOF_DIR,
            title="Proof Loop Blocked",
            summary="Terry paused inside the prove-and-repair loop. Run `terry retry` to grant more attempts.",
            artifact_paths=artifact_paths,
            continue_decision="retry",
        )

    def _pause_for_legacy_stall_review(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        return self._pause_for_checkpoint(
            store,
            manifest,
            stage=RunStage.LEGACY_AWAITING_STALL_REVIEW,
            stage_dir=LEGACY_STALL_DIR,
            title="Legacy Proof Stall Review",
            summary="This run paused in the legacy proof-stall checkpoint before Terry's current proof-blocked layout.",
            artifact_paths=self._legacy_artifact_paths(
                store,
                f"{LEGACY_STALL_DIR}/stall_report.md",
                self._attempt_result_path(manifest.attempt_count) if manifest.attempt_count > 0 else None,
            ),
            continue_decision="retry",
        )

    def _pause_for_final(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        artifact_paths = [FINAL_CANDIDATE]
        final_compile_path = f"{FINAL_DIR}/compile_result.json"
        if store.exists(final_compile_path):
            artifact_paths.append(final_compile_path)
        if manifest.attempt_count > 0:
            artifact_paths.extend(self._existing_attempt_review_artifacts(store, manifest.attempt_count))
        return self._pause_for_checkpoint(
            store,
            manifest,
            stage=RunStage.AWAITING_FINAL_APPROVAL,
            stage_dir=FINAL_DIR,
            title="Final Approval",
            summary="Terry is waiting for final approval of the compiling Lean candidate.",
            artifact_paths=artifact_paths,
            continue_decision="approve",
        )

    def _pause_for_legacy_final_review(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        return self._pause_for_checkpoint(
            store,
            manifest,
            stage=RunStage.LEGACY_AWAITING_FINAL_REVIEW,
            stage_dir=LEGACY_FINAL_DIR,
            title="Legacy Final Review",
            summary="This run paused in the legacy final checkpoint before Terry's current `04_final/` layout.",
            artifact_paths=self._legacy_artifact_paths(
                store,
                f"{LEGACY_FINAL_DIR}/final_candidate.lean",
                f"{LEGACY_FINAL_DIR}/final_report.md",
            ),
            continue_decision="approve",
        )

    def _pause_for_checkpoint(
        self,
        store: RunStore,
        manifest: RunManifest,
        *,
        stage: RunStage,
        stage_dir: str,
        title: str,
        summary: str,
        artifact_paths: list[str],
        continue_decision: str,
    ) -> RunManifest:
        manifest.current_stage = stage
        self._save_manifest(store, manifest)
        review_path = f"{stage_dir}/review.md"
        checkpoint_path = f"{stage_dir}/checkpoint.md"
        resume_command = self._resume_command(manifest)

        existing_decision = self._load_decision(store, f"{stage_dir}/decision.json")
        if existing_decision is None or existing_decision.decision in {"pending", continue_decision}:
            self._write_decision(
                store,
                stage_dir,
                ReviewDecision("pending", utc_now(), ""),
            )

        if not store.exists(review_path) or self._review_requests_continue(
            store.read_text(review_path),
            continue_decision,
        ):
            store.write_text(
                review_path,
                self._review_template(title, continue_decision),
            )
        store.write_text(
            checkpoint_path,
            self._checkpoint_text(
                title=title,
                summary=summary,
                artifact_paths=artifact_paths,
                review_path=review_path,
                resume_command=resume_command,
                continue_decision=continue_decision,
            ),
        )
        store.append_log(
            "checkpoint_opened",
            summary,
            stage=stage.value,
            details={
                "checkpoint_path": checkpoint_path,
                "review_path": review_path,
                "resume_command": resume_command,
            },
        )
        return manifest

    def _build_stage_request(
        self,
        store: RunStore,
        manifest: RunManifest,
        *,
        stage: BackendStage,
        output_dir: str,
        required_outputs: list[str],
        review_notes_relative_path: str | None = None,
        latest_compile_result_path: str | None = None,
        previous_attempt_dir: str | None = None,
        attempt: int | None = None,
        max_attempts: int | None = None,
    ) -> StageRequest:
        normalized_source = self._first_existing_path(
            store,
            "00_input/normalized.md",
            "01_normalized/normalized.md",
        )
        input_paths = {
            "source": self._repo_relative(store.path("00_input/source.txt")),
            "provenance": self._repo_relative(store.path("00_input/provenance.json")),
        }
        if normalized_source is not None:
            input_paths["normalized_source"] = self._repo_relative(store.path(normalized_source))
        if stage in {BackendStage.PLAN, BackendStage.PROOF, BackendStage.REVIEW}:
            self._maybe_add_input_path(store, input_paths, "enrichment_handoff", ENRICHMENT_HANDOFF)
            self._maybe_add_input_path(
                store,
                input_paths,
                "natural_language_statement",
                ENRICHMENT_NATURAL_LANGUAGE_STATEMENT,
            )
            self._maybe_add_input_path(
                store,
                input_paths,
                "natural_language_proof",
                ENRICHMENT_NATURAL_LANGUAGE_PROOF,
            )
            self._maybe_add_input_path(store, input_paths, "proof_status", ENRICHMENT_PROOF_STATUS)
            self._maybe_add_input_path(
                store,
                input_paths,
                "legacy_enrichment_handoff",
                f"{LEGACY_ENRICHMENT_DIR}/handoff.md",
            )
            self._maybe_add_input_path(
                store,
                input_paths,
                "legacy_enrichment_report",
                f"{LEGACY_ENRICHMENT_DIR}/enrichment_report.approved.json",
            )
            self._maybe_add_input_path(
                store,
                input_paths,
                "legacy_enrichment_report",
                f"{LEGACY_ENRICHMENT_DIR}/enrichment_report.json",
            )
            self._maybe_add_review_input_path(store, input_paths, "enrichment_review", f"{ENRICHMENT_DIR}/review.md")
            self._maybe_add_review_input_path(
                store,
                input_paths,
                "legacy_enrichment_review",
                f"{LEGACY_ENRICHMENT_DIR}/review.md",
            )
        if stage in {BackendStage.PROOF, BackendStage.REVIEW}:
            self._maybe_add_input_path(store, input_paths, "plan_handoff", PLAN_HANDOFF)
            self._maybe_add_input_path(
                store,
                input_paths,
                "legacy_plan",
                f"{LEGACY_PLAN_DIR}/formalization_plan.approved.json",
            )
            self._maybe_add_input_path(
                store,
                input_paths,
                "legacy_plan",
                f"{LEGACY_PLAN_DIR}/formalization_plan.json",
            )
            self._maybe_add_review_input_path(store, input_paths, "plan_review", f"{PLAN_DIR}/review.md")
            self._maybe_add_review_input_path(
                store,
                input_paths,
                "legacy_plan_review",
                f"{LEGACY_PLAN_DIR}/review.md",
            )
            if latest_compile_result_path and store.exists(latest_compile_result_path):
                input_paths["previous_compile_result"] = self._repo_relative(store.path(latest_compile_result_path))
            elif attempt is not None and attempt > 1:
                self._maybe_add_input_path(
                    store,
                    input_paths,
                    "legacy_previous_compile_result",
                    f"08_compile/attempt_{attempt - 1:04d}/result.json",
                )
            if previous_attempt_dir and store.exists(f"{previous_attempt_dir}/candidate.lean"):
                input_paths["previous_candidate"] = self._repo_relative(
                    store.path(f"{previous_attempt_dir}/candidate.lean")
                )
                for key, filename in (
                    ("previous_walkthrough", ATTEMPT_WALKTHROUGH),
                    ("previous_readable_candidate", ATTEMPT_READABLE_CANDIDATE),
                    ("previous_error_report", ATTEMPT_ERROR_REPORT),
                ):
                    previous_review_path = f"{previous_attempt_dir}/{filename}"
                    if store.exists(previous_review_path):
                        input_paths[key] = self._repo_relative(store.path(previous_review_path))
            elif attempt is not None and attempt > 1:
                self._maybe_add_input_path(
                    store,
                    input_paths,
                    "legacy_previous_candidate",
                    f"07_draft/attempt_{attempt - 1:04d}/draft.lean",
                )
                self._maybe_add_input_path(
                    store,
                    input_paths,
                    "legacy_previous_candidate_payload",
                    f"07_draft/attempt_{attempt - 1:04d}/parsed_output.json",
                )
            self._maybe_add_review_input_path(store, input_paths, "proof_review", f"{PROOF_DIR}/review.md")
        if stage == BackendStage.REVIEW and attempt is not None:
            current_attempt_dir = f"{PROOF_DIR}/attempts/attempt_{attempt:04d}"
            self._maybe_add_input_path(store, input_paths, "attempt_candidate", f"{current_attempt_dir}/candidate.lean")
            self._maybe_add_input_path(
                store,
                input_paths,
                "attempt_compile_result",
                f"{current_attempt_dir}/compile_result.json",
            )
        if stage == BackendStage.PLAN:
            self._maybe_add_input_path(
                store,
                input_paths,
                "legacy_spec",
                f"{LEGACY_SPEC_DIR}/theorem_spec.approved.json",
            )
            self._maybe_add_input_path(
                store,
                input_paths,
                "legacy_spec",
                f"{LEGACY_SPEC_DIR}/theorem_spec.json",
            )

        compile_result_relative = (
            self._repo_relative(store.path(latest_compile_result_path))
            if latest_compile_result_path and store.exists(latest_compile_result_path)
            else None
        )
        if compile_result_relative is None and stage in {BackendStage.PROOF, BackendStage.REVIEW} and attempt is not None:
            current_compile_relative = f"{PROOF_DIR}/attempts/attempt_{attempt:04d}/compile_result.json"
            if store.exists(current_compile_relative):
                compile_result_relative = self._repo_relative(store.path(current_compile_relative))
        if compile_result_relative is None and stage == BackendStage.PROOF and attempt is not None and attempt > 1:
            legacy_compile_relative = f"08_compile/attempt_{attempt - 1:04d}/result.json"
            if store.exists(legacy_compile_relative):
                compile_result_relative = self._repo_relative(store.path(legacy_compile_relative))

        return StageRequest(
            stage=stage,
            run_id=manifest.run_id,
            repo_root=str(self.repo_root.resolve()),
            run_dir=self._repo_relative(store.run_root),
            output_dir=self._repo_relative(store.path(output_dir)),
            input_paths=input_paths,
            required_outputs=required_outputs,
            review_notes_path=self._meaningful_review_notes_path(store, review_notes_relative_path),
            latest_compile_result_path=compile_result_relative,
            previous_attempt_dir=(
                self._repo_relative(store.path(previous_attempt_dir))
                if previous_attempt_dir and store.path(previous_attempt_dir).exists()
                else None
            ),
            attempt=attempt,
            max_attempts=max_attempts,
        )

    def _maybe_add_input_path(
        self,
        store: RunStore,
        input_paths: dict[str, str],
        key: str,
        relative_path: str,
    ) -> None:
        if key in input_paths:
            return
        if store.exists(relative_path):
            input_paths[key] = self._repo_relative(store.path(relative_path))

    def _maybe_add_review_input_path(
        self,
        store: RunStore,
        input_paths: dict[str, str],
        key: str,
        relative_path: str,
    ) -> None:
        if key in input_paths:
            return
        meaningful_path = self._meaningful_review_notes_path(store, relative_path)
        if meaningful_path is not None:
            input_paths[key] = meaningful_path

    def _run_attempt_review(
        self,
        store: RunStore,
        manifest: RunManifest,
        attempt: int,
        *,
        review_notes_relative_path: str | None = None,
        max_attempts: int | None = None,
    ) -> None:
        attempt_dir = f"{PROOF_DIR}/attempts/attempt_{attempt:04d}"
        candidate_path = f"{attempt_dir}/candidate.lean"
        compile_path = f"{attempt_dir}/compile_result.json"
        if not store.exists(candidate_path) or not store.exists(compile_path):
            raise ValueError(
                "Terry review needs both the candidate and compile result for the selected attempt."
            )
        request = self._build_stage_request(
            store,
            manifest,
            stage=BackendStage.REVIEW,
            output_dir=attempt_dir,
            required_outputs=ATTEMPT_REVIEW_OUTPUTS,
            review_notes_relative_path=review_notes_relative_path,
            latest_compile_result_path=compile_path,
            attempt=attempt,
            max_attempts=max_attempts or manifest.attempt_count or self.max_attempts,
        )
        self._run_backend_stage(store, request, attempt_dir)
        store.append_log(
            "attempt_review_ready",
            f"Wrote Terry review artifacts for attempt {attempt}.",
            stage="proof",
            details={"attempt": attempt},
        )

    def _attempt_review_paths(self, attempt: int) -> list[str]:
        attempt_dir = f"{PROOF_DIR}/attempts/attempt_{attempt:04d}"
        return [f"{attempt_dir}/{relative_path}" for relative_path in ATTEMPT_REVIEW_OUTPUTS]

    def _existing_attempt_review_artifacts(self, store: RunStore, attempt: int) -> list[str]:
        return [relative_path for relative_path in self._attempt_review_paths(attempt) if store.exists(relative_path)]

    def _load_proof_status(self, store: RunStore) -> NaturalLanguageProofStatus | None:
        if not store.exists(ENRICHMENT_PROOF_STATUS):
            return None
        payload = store.read_json(ENRICHMENT_PROOF_STATUS)
        obtained = payload.get("obtained")
        if not isinstance(obtained, bool):
            raise ValueError("`01_enrichment/proof_status.json` must contain a boolean `obtained` field.")
        source = str(payload.get("source") or "unknown")
        notes = str(payload.get("notes") or "")
        return NaturalLanguageProofStatus(obtained=obtained, source=source, notes=notes)

    def _natural_language_proof_ready(self, store: RunStore) -> bool:
        proof_status = self._load_proof_status(store)
        return (
            proof_status is not None
            and proof_status.obtained
            and store.exists(ENRICHMENT_NATURAL_LANGUAGE_STATEMENT)
            and store.exists(ENRICHMENT_NATURAL_LANGUAGE_PROOF)
        )

    def _enrichment_stage_ready(self, store: RunStore) -> bool:
        if not self._turn_artifacts_ready(
            store,
            ENRICHMENT_DIR,
            ["handoff.md", "proof_status.json", "natural_language_statement.md"],
        ):
            return False
        proof_status = self._load_proof_status(store)
        if proof_status is None:
            return False
        if proof_status.obtained and not store.exists(ENRICHMENT_NATURAL_LANGUAGE_PROOF):
            raise RuntimeError(
                "Enrichment recorded `obtained: true` without writing `01_enrichment/natural_language_proof.md`."
            )
        return True

    def _reset_checkpoint_surface(self, store: RunStore, stage_dir: str) -> None:
        for relative_path in (f"{stage_dir}/review.md", f"{stage_dir}/decision.json"):
            target = store.path(relative_path)
            if target.exists():
                target.unlink()

    def _render_loop_summary(self, store: RunStore, latest_attempt: int) -> str:
        sections = [
            "# Prove-And-Repair Loop",
            "",
            f"Latest completed attempt: {latest_attempt}",
            "",
            "## Attempts",
        ]
        for attempt in range(1, latest_attempt + 1):
            compile_path = self._attempt_result_path(attempt)
            if not store.exists(compile_path):
                continue
            payload = store.read_json(compile_path)
            status = payload.get("status", "unknown")
            diagnostics = payload.get("diagnostics", [])
            sections.append(f"- attempt {attempt}: {status}")
            if diagnostics:
                sections.append(f"  diagnostics: {' | '.join(str(item) for item in diagnostics)}")
            review_artifacts = self._existing_attempt_review_artifacts(store, attempt)
            if review_artifacts:
                sections.append(f"  review: {' | '.join(review_artifacts)}")
        sections.append("")
        return "\n".join(sections)

    def _render_proof_blocker(self, reason: str) -> str:
        return "\n".join(
            [
                "# Proof Loop Blocked",
                "",
                reason.strip(),
                "",
            ]
        )

    def _checkpoint_text(
        self,
        *,
        title: str,
        summary: str,
        artifact_paths: list[str],
        review_path: str,
        resume_command: str,
        continue_decision: str,
    ) -> str:
        artifact_lines = "\n".join(f"- `{path}`" for path in artifact_paths)
        return "\n".join(
            [
                f"# {title}",
                "",
                summary,
                "",
                "## Review Artifacts",
                artifact_lines,
                "",
                "## Review File",
                f"- `{review_path}`",
                "",
                "## Continue Condition",
                f"Set `decision: {continue_decision}` in the review file when you want Terry to continue.",
                "",
                "## Resume Command",
                f"`{resume_command}`",
                "",
            ]
        )

    def _review_template(self, title: str, continue_decision: str) -> str:
        return "\n".join(
            [
                f"# {title}",
                "",
                "decision: pending",
                "",
                f"Change `decision: pending` to `{continue_decision}` when you want Terry to continue.",
                "Leave the `Notes:` section blank unless you want Terry to receive actual reviewer guidance.",
                "",
                "Notes:",
                "",
            ]
        )

    def _review_requests_continue(self, content: str, continue_decision: str) -> bool:
        for raw_line in content.splitlines():
            line = raw_line.strip()
            if not line.lower().startswith("decision:"):
                continue
            decision_value = line.split(":", 1)[1].strip().lower()
            return decision_value == continue_decision
        return False

    def _meaningful_review_notes_path(
        self,
        store: RunStore,
        relative_path: str | None,
    ) -> str | None:
        if relative_path is None or not store.exists(relative_path):
            return None
        decision = self._parse_review_file(store.read_text(relative_path))
        if decision is None:
            return None
        return self._repo_relative(store.path(relative_path))

    def _resume_command(self, manifest: RunManifest) -> str:
        command = [
            self.terry_command,
            "--repo-root",
            str(self.repo_root.resolve()),
        ]
        lake_path = self._persisted_lake_path()
        if lake_path:
            command.extend(["--lake-path", lake_path])
        command.extend(["resume", manifest.run_id])
        if manifest.agent_config.backend == "command":
            provider_command = (
                shlex.join(manifest.agent_config.command)
                if manifest.agent_config.command
                else "python3 path/to/provider.py"
            )
            command.extend(["--agent-command", provider_command])
        return " ".join(shlex.quote(part) for part in command)

    def _resolve_checkpoint_decision(
        self,
        store: RunStore,
        stage_dir: str,
        *,
        continue_decision: str,
        auto_approve: bool,
    ) -> ReviewDecision | None:
        review_path = f"{stage_dir}/review.md"
        if store.exists(review_path):
            decision = self._parse_review_file(store.read_text(review_path))
            if decision is not None:
                self._write_decision(store, stage_dir, decision)
                return decision

        existing = self._load_decision(store, f"{stage_dir}/decision.json")
        if existing is not None:
            if existing.decision != "pending":
                return existing

        if auto_approve:
            decision = ReviewDecision(continue_decision, utc_now(), "Auto-approved.")
            self._write_decision(store, stage_dir, decision)
            return decision
        return None

    def _write_decision(self, store: RunStore, stage_dir: str, decision: ReviewDecision) -> None:
        store.write_json(f"{stage_dir}/decision.json", decision)

    def _parse_review_file(self, content: str) -> ReviewDecision | None:
        valid_decisions = {"approve", "retry", "reject"}
        lines = content.splitlines()
        decision_value: str | None = None
        notes_lines: list[str] = []
        in_notes = False

        for raw_line in lines:
            line = raw_line.strip()
            if not in_notes and line.lower().startswith("decision:"):
                decision_value = line.split(":", 1)[1].strip().lower()
                continue
            if line.lower() == "notes:":
                in_notes = True
                continue
            if in_notes:
                notes_lines.append(raw_line)

        if decision_value is None or decision_value in {"", "pending"}:
            return None
        if decision_value not in valid_decisions:
            raise ValueError(
                "Unsupported review decision "
                f"`{decision_value}`. Use one of: {', '.join(sorted(valid_decisions))}."
            )
        notes = "\n".join(notes_lines).strip()
        return ReviewDecision(decision=decision_value, updated_at=utc_now(), notes=notes)

    def _save_manifest(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        manifest.updated_at = utc_now()
        store.write_json("manifest.json", manifest)
        return manifest

    def _load_manifest(self, store: RunStore) -> RunManifest:
        payload = store.read_json("manifest.json")
        stage_value = payload["current_stage"]

        agent_config_payload = payload.get("agent_config")
        if isinstance(agent_config_payload, dict):
            agent_config = AgentConfig(**agent_config_payload)
        else:
            agent_name = payload.get("agent_name", "")
            agent_name_value = str(agent_name)
            if agent_name_value.startswith("codex_cli:"):
                model = agent_name_value.split(":", 1)[1]
                agent_config = AgentConfig(
                    backend="codex",
                    codex_model=None if model == "default" else model,
                )
            elif (
                agent_name_value.startswith("subprocess:")
                or (agent_name_value and agent_name_value not in LEGACY_DEMO_AGENT_NAMES)
            ):
                agent_config = AgentConfig(backend="command")
            else:
                agent_config = AgentConfig(backend="demo")

        template_dir = payload.get("template_dir")
        if not template_dir:
            discovered = discover_workspace_template(self.repo_root)
            if discovered is not None:
                template_dir = str(discovered)
            else:
                repo_template = self.repo_root / "lean_workspace_template"
                if repo_template.exists():
                    template_dir = str(repo_template.resolve())
                else:
                    template_dir = str((Path(__file__).resolve().parent / "workspace_template").resolve())

        return RunManifest(
            run_id=payload["run_id"],
            source=SourceRef(
                path=payload["source"]["path"],
                kind=SourceKind(payload["source"]["kind"]),
            ),
            agent_name=payload["agent_name"],
            agent_config=agent_config,
            template_dir=template_dir,
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
            current_stage=RunStage(stage_value),
            lake_path=payload.get("lake_path"),
            workflow_version=payload.get("workflow_version", DEFAULT_WORKFLOW_VERSION),
            workflow_tags=payload.get("workflow_tags", list(DEFAULT_WORKFLOW_TAGS)),
            attempt_count=payload.get("attempt_count", 0),
            latest_error=payload.get("latest_error"),
            final_output_path=payload.get("final_output_path"),
        )

    def _load_decision(self, store: RunStore, relative_path: str) -> ReviewDecision | None:
        if not store.exists(relative_path):
            return None
        payload = store.read_json(relative_path)
        if "decision" in payload:
            return ReviewDecision(**payload)
        if payload.get("approved"):
            return ReviewDecision("approve", payload.get("updated_at", utc_now()), payload.get("notes", ""))
        if "approved" in payload:
            return ReviewDecision("reject", payload.get("updated_at", utc_now()), payload.get("notes", ""))
        return None

    def _checkpoint_surface_missing(self, store: RunStore, stage_dir: str) -> bool:
        return not (
            store.exists(f"{stage_dir}/checkpoint.md")
            and store.exists(f"{stage_dir}/review.md")
        )

    def _attempt_result_path(self, attempt: int) -> str:
        return f"{PROOF_DIR}/attempts/attempt_{attempt:04d}/compile_result.json"

    def _latest_attempt_error(self, store: RunStore, latest_attempt: int) -> str:
        if latest_attempt <= 0:
            return "Unknown failure."
        compile_path = self._attempt_result_path(latest_attempt)
        if not store.exists(compile_path):
            return "Unknown failure."
        payload = store.read_json(compile_path)
        stderr = str(payload.get("stderr", "")).strip()
        status = str(payload.get("status", "Unknown failure."))
        return stderr or status

    def _legacy_artifact_paths(self, store: RunStore, *relative_paths: str | None) -> list[str]:
        resolved: list[str] = []
        for relative_path in relative_paths:
            if relative_path and store.exists(relative_path):
                resolved.append(relative_path)
        return resolved

    def _first_existing_path(self, store: RunStore, *relative_paths: str) -> str | None:
        for relative_path in relative_paths:
            if store.exists(relative_path):
                return relative_path
        return None

    def _write_compile_result(self, store: RunStore, attempt: int, compile_result: CompileAttempt) -> None:
        attempt_dir = f"{PROOF_DIR}/attempts/attempt_{attempt:04d}"
        store.write_json(f"{attempt_dir}/compile_result.json", compile_result)
        store.write_text(f"{attempt_dir}/stdout.txt", compile_result.stdout)
        store.write_text(f"{attempt_dir}/stderr.txt", compile_result.stderr)
        store.write_json(
            f"{attempt_dir}/quality_gate.json",
            {
                "passed": compile_result.quality_gate_passed,
                "checks": ["no_sorry_literals"],
            },
        )
        store.write_text(PROOF_LOOP, self._render_loop_summary(store, attempt))

    def _turn_artifacts_ready(
        self,
        store: RunStore,
        turn_dir: str,
        required_outputs: list[str],
    ) -> bool:
        required_paths = [
            f"{turn_dir}/request.json",
            f"{turn_dir}/prompt.md",
            f"{turn_dir}/response.txt",
        ]
        required_paths.extend(f"{turn_dir}/{relative_path}" for relative_path in required_outputs)
        return all(store.exists(relative_path) for relative_path in required_paths)

    def _clear_turn_artifacts(
        self,
        store: RunStore,
        turn_dir: str,
        required_outputs: list[str],
        *,
        clear_compile_outputs: bool = False,
    ) -> None:
        stale_paths = [
            f"{turn_dir}/request.json",
            f"{turn_dir}/prompt.md",
            f"{turn_dir}/response.txt",
        ]
        stale_paths.extend(f"{turn_dir}/{relative_path}" for relative_path in required_outputs)
        if clear_compile_outputs and turn_dir.startswith(f"{PROOF_DIR}/attempts/"):
            stale_paths.extend(
                [
                    f"{turn_dir}/compile_result.json",
                    f"{turn_dir}/stdout.txt",
                    f"{turn_dir}/stderr.txt",
                    f"{turn_dir}/quality_gate.json",
                ]
            )

        for relative_path in stale_paths:
            target = store.path(relative_path)
            if target.is_dir():
                target.rmdir()
            else:
                target.unlink(missing_ok=True)

    def _load_compile_attempt(self, store: RunStore, relative_path: str) -> CompileAttempt:
        payload = store.read_json(relative_path)
        return CompileAttempt(**payload)

    def _ensure_workspace_template(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        if not isinstance(self.lean_runner, LeanRunner):
            return manifest

        template_path = Path(manifest.template_dir)
        if template_path.exists() and _is_eligible_template(template_path):
            self.lean_runner.template_dir = template_path.resolve()
            return manifest

        packaged_template = (Path(__file__).resolve().parent / "workspace_template").resolve()

        resolution = resolve_workspace_template(
            self.repo_root,
            packaged_template,
            lake_path=self.lean_runner.lake_path,
        )
        self.lean_runner.template_dir = resolution.template_dir
        manifest.template_dir = str(resolution.template_dir.resolve())
        self._save_manifest(store, manifest)
        message = f"Using workspace template from `{resolution.template_dir}` via {resolution.origin}."
        details: dict[str, object] = {"command": resolution.command or []}
        if resolution.warning:
            message = f"{message} {resolution.warning.splitlines()[0]}"
            details["warning"] = resolution.warning
        store.append_log(
            "template_selected",
            message,
            stage="proof",
            details=details,
        )
        return manifest

    def _persisted_lake_path(self) -> str | None:
        if not self.lean_runner.lake_path:
            return None
        configured = Path(self.lean_runner.lake_path).expanduser()
        if configured.is_absolute() or "/" in self.lean_runner.lake_path:
            return str(configured.resolve())
        return self.lean_runner.lake_path

    def _repo_relative(self, path: Path) -> str:
        return str(path.resolve().relative_to(self.repo_root.resolve()))
