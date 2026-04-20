from __future__ import annotations

import inspect
import shutil
import shlex
import time
from pathlib import Path
from typing import Any, Callable

from .agents import FormalizationAgent
from .backend_runtime import is_transient_backend_failure
from .ingest import detect_source_kind
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


def _agent_config_from_payload(payload: dict[str, Any]) -> AgentConfig:
    """Build an AgentConfig, migrating legacy field names (`codex_model`)."""
    normalized = dict(payload)
    legacy_model = normalized.pop("codex_model", None)
    if "model" not in normalized and legacy_model is not None:
        normalized["model"] = legacy_model
    allowed = {"backend", "command", "model"}
    filtered = {key: value for key, value in normalized.items() if key in allowed}
    return AgentConfig(**filtered)

ENRICHMENT_HANDOFF = f"{ENRICHMENT_DIR}/handoff.md"
ENRICHMENT_PROOF_STATUS = f"{ENRICHMENT_DIR}/proof_status.json"
ENRICHMENT_NATURAL_LANGUAGE_STATEMENT = f"{ENRICHMENT_DIR}/natural_language_statement.md"
ENRICHMENT_NATURAL_LANGUAGE_PROOF = f"{ENRICHMENT_DIR}/natural_language_proof.md"
ENRICHMENT_RELEVANT_LEAN_OBJECTS = f"{ENRICHMENT_DIR}/relevant_lean_objects.md"
ENRICHMENT_PREREQUISITES_DIR = f"{ENRICHMENT_DIR}/prerequisites"
PLAN_HANDOFF = f"{PLAN_DIR}/handoff.md"
PLAN_DEPENDENCY_GRAPH = f"{PLAN_DIR}/dependency_graph.md"
PROOF_BLOCKER = f"{PROOF_DIR}/blocker.md"
PROOF_LOOP = f"{PROOF_DIR}/loop.md"
FINAL_CANDIDATE = f"{FINAL_DIR}/final_candidate.lean"
ATTEMPT_REVIEW_DIR = "review"
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


def _approvable_stage_dir(stage: "RunStage") -> str | None:
    """Return the stage directory whose decision.json can be flipped to approve.

    Proof-blocked and non-handoff stages (CREATED, PROVING, COMPLETED, FAILED)
    are intentionally excluded — proof-blocked runs continue via `terry retry`,
    and the others have no pending handoff to approve.
    """
    return {
        RunStage.AWAITING_ENRICHMENT_APPROVAL: ENRICHMENT_DIR,
        RunStage.AWAITING_PLAN_APPROVAL: PLAN_DIR,
        RunStage.AWAITING_FINAL_APPROVAL: FINAL_DIR,
        RunStage.LEGACY_AWAITING_ENRICHMENT_REVIEW: LEGACY_ENRICHMENT_DIR,
        RunStage.LEGACY_AWAITING_SPEC_REVIEW: LEGACY_SPEC_DIR,
        RunStage.LEGACY_AWAITING_PLAN_REVIEW: LEGACY_PLAN_DIR,
        RunStage.LEGACY_AWAITING_FINAL_REVIEW: LEGACY_FINAL_DIR,
    }.get(stage)


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
        event_sink: Callable[[dict[str, Any]], None] | None = None,
        max_backend_retries: int = 3,
        backend_retry_backoff_seconds: float = 0.5,
    ):
        self.repo_root = repo_root
        self.agent = agent
        self.agent_config = agent_config
        self.max_attempts = max_attempts
        self.terry_command = terry_command
        self.event_sink = event_sink
        self.max_backend_retries = max_backend_retries
        self.backend_retry_backoff_seconds = backend_retry_backoff_seconds
        self.artifacts_root = repo_root / "artifacts"
        self.lean_runner = lean_runner or LeanRunner(
            repo_root / "lean_workspace_template",
            repo_root=repo_root,
        )

    def _workflow_tags(self, *, divide_and_conquer: bool) -> list[str]:
        tags = list(DEFAULT_WORKFLOW_TAGS)
        if divide_and_conquer and "divide-and-conquer" not in tags:
            tags.append("divide-and-conquer")
        return tags

    def _enrichment_required_outputs(self, manifest: RunManifest) -> list[str]:
        outputs = ["handoff.md", "proof_status.json", "natural_language_statement.md"]
        if manifest.divide_and_conquer:
            outputs.append("prerequisites")
        return outputs

    def _plan_required_outputs(self, manifest: RunManifest) -> list[str]:
        outputs = ["handoff.md"]
        if manifest.divide_and_conquer:
            outputs.append("dependency_graph.md")
        return outputs

    def prove(
        self,
        source_path: Path,
        run_id: str,
        auto_approve: bool = False,
        *,
        divide_and_conquer: bool = False,
    ) -> RunManifest:
        store = self._store(run_id)
        source_ref = SourceRef(
            path=self._display_path(source_path),
            kind=detect_source_kind(source_path),
        )
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
            workflow_tags=self._workflow_tags(divide_and_conquer=divide_and_conquer),
            divide_and_conquer=divide_and_conquer,
        )
        self._save_manifest(store, manifest)

        source_snapshot_relative_path = self._snapshot_source_input(store, source_path)
        store.write_json(
            "00_input/provenance.json",
            {
                "source": source_ref,
                "source_snapshot_path": source_snapshot_relative_path,
            },
        )
        store.append_log(
            "source_snapshot_ready",
            f"Captured the original theorem source at `{source_snapshot_relative_path}`.",
            stage="input",
            details={"source_kind": source_ref.kind, "snapshot_path": source_snapshot_relative_path},
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
        store = self._store(run_id)
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
                    rerun=True,
                )
            store.append_log(
                "checkpoint_approved",
                "Enrichment checkpoint approved.",
                stage="enrichment",
                details={"notes": decision.notes},
            )
            if not self._natural_language_proof_ready(store):
                store.append_log(
                    "enrichment_rerun_requested",
                    "Enrichment approval supplied missing-proof guidance; Terry is rerunning enrichment before planning.",
                    stage="enrichment",
                    details={"notes": decision.notes},
                )
                return self._run_enrichment_stage(
                    store,
                    manifest,
                    auto_approve=auto_approve,
                    review_notes_relative_path=f"{ENRICHMENT_DIR}/review.md",
                    rerun=True,
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
                self._ensure_attempt_review_ready(
                    store,
                    manifest,
                    manifest.attempt_count,
                    review_notes_relative_path=self._default_attempt_review_notes_path(store),
                )
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

    def approve_current_checkpoint(self, run_id: str, notes: str = "") -> RunManifest:
        """Record an `approve` decision for the run's currently paused handoff.

        This lets `terry resume --approve` approve an open handoff without
        requiring the human to edit `review.md`. The run must be paused at an
        approvable handoff (enrichment, plan, or final); proof-blocked runs
        continue through `terry retry` instead.
        """
        store = self._store(run_id)
        manifest = self._load_manifest(store)
        stage_dir = _approvable_stage_dir(manifest.current_stage)
        if stage_dir is None:
            if manifest.current_stage in {
                RunStage.PROOF_BLOCKED,
                RunStage.LEGACY_AWAITING_STALL_REVIEW,
            }:
                raise ValueError(
                    f"Run `{run_id}` is proof-blocked. `--approve` is not valid here; "
                    f"run `terry retry {run_id} --attempts N` to grant more attempts."
                )
            raise ValueError(
                f"Run `{run_id}` is in `{manifest.current_stage.value}`, "
                "which has no open handoff to approve."
            )
        decision = ReviewDecision("approve", utc_now(), notes)
        self._write_decision(store, stage_dir, decision)
        store.append_log(
            "checkpoint_approved_via_cli",
            f"Human approved the {manifest.current_stage.value} checkpoint via `terry resume --approve`.",
            stage=manifest.current_stage.value,
            details={"stage_dir": stage_dir, "notes": notes},
        )
        return manifest

    def retry(self, run_id: str, extra_attempts: int = 3, auto_approve: bool = False) -> RunManifest:
        store = self._store(run_id)
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
        store = self._store(run_id)
        return self._load_manifest(store)

    def review_attempt(self, run_id: str, attempt: int | None = None) -> int:
        store = self._store(run_id)
        manifest = self._load_manifest(store)
        selected_attempt = manifest.attempt_count if attempt is None else attempt
        if selected_attempt <= 0:
            raise ValueError("Terry review needs a completed proof attempt.")
        self._run_attempt_review(store, manifest, selected_attempt)
        return selected_attempt

    def _store(self, run_id: str) -> RunStore:
        return RunStore(self.artifacts_root, run_id, event_sink=self.event_sink)

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

        if self._turn_artifacts_ready(store, PLAN_DIR, self._plan_required_outputs(manifest)):
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
                if not self._natural_language_proof_ready(store):
                    return self._run_enrichment_stage(
                        store,
                        manifest,
                        auto_approve=auto_approve,
                        review_notes_relative_path=f"{ENRICHMENT_DIR}/review.md",
                        rerun=True,
                    )
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
                    rerun=True,
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
        rerun: bool = False,
    ) -> RunManifest:
        request = self._build_stage_request(
            store,
            manifest,
            stage=BackendStage.ENRICHMENT,
            output_dir=ENRICHMENT_DIR,
            required_outputs=self._enrichment_required_outputs(manifest),
            review_notes_relative_path=review_notes_relative_path,
            stale_output_paths=(
                self._existing_stage_outputs(
                    store,
                    ENRICHMENT_HANDOFF,
                    ENRICHMENT_PROOF_STATUS,
                    ENRICHMENT_NATURAL_LANGUAGE_STATEMENT,
                    ENRICHMENT_NATURAL_LANGUAGE_PROOF,
                    ENRICHMENT_RELEVANT_LEAN_OBJECTS,
                    ENRICHMENT_PREREQUISITES_DIR,
                )
                if rerun
                else None
            ),
        )
        self._run_backend_stage(
            store,
            request,
            ENRICHMENT_DIR,
            extra_stale_outputs=[
                ENRICHMENT_NATURAL_LANGUAGE_PROOF.removeprefix(f"{ENRICHMENT_DIR}/"),
                ENRICHMENT_RELEVANT_LEAN_OBJECTS.removeprefix(f"{ENRICHMENT_DIR}/"),
                ENRICHMENT_PREREQUISITES_DIR.removeprefix(f"{ENRICHMENT_DIR}/"),
            ],
            backend_attempt_limit=1 if rerun else None,
        )
        proof_status = self._load_proof_status(store)
        if proof_status is None:
            raise RuntimeError("Enrichment stage did not write a valid `01_enrichment/proof_status.json`.")
        if not store.exists(ENRICHMENT_NATURAL_LANGUAGE_STATEMENT):
            raise RuntimeError("Enrichment stage did not write `01_enrichment/natural_language_statement.md`.")
        if manifest.divide_and_conquer and not self._prerequisites_dir_ready(store):
            raise RuntimeError(
                "Divide-and-conquer mode requires a non-empty `01_enrichment/prerequisites/` directory "
                "before Terry can leave enrichment."
            )
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
                "divide_and_conquer": manifest.divide_and_conquer,
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
        proof_ready = self._natural_language_proof_ready(store)
        if manifest.divide_and_conquer and not self._prerequisites_dir_ready(store):
            raise RuntimeError(
                "Terry cannot start the divide-and-conquer plan stage without "
                "`01_enrichment/prerequisites/`."
            )
        legacy_plan_rerun = (
            force_rerun
            and not allow_missing_proof
            and not proof_ready
            and store.exists(PLAN_HANDOFF)
        )
        if not allow_missing_proof and not legacy_plan_rerun and not proof_ready:
            raise RuntimeError(
                "Terry cannot start the plan stage without `01_enrichment/natural_language_statement.md`, "
                "`01_enrichment/natural_language_proof.md`, and `01_enrichment/proof_status.json` "
                "reporting `obtained: true`."
            )

        if not force_rerun and self._turn_artifacts_ready(
            store,
            PLAN_DIR,
            self._plan_required_outputs(manifest),
        ):
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
                required_outputs=self._plan_required_outputs(manifest),
                review_notes_relative_path=review_notes_relative_path,
                stale_output_paths=(
                    self._existing_stage_outputs(store, PLAN_HANDOFF, PLAN_DEPENDENCY_GRAPH)
                    if force_rerun
                    else None
                ),
            )
            self._run_backend_stage(
                store,
                request,
                PLAN_DIR,
                backend_attempt_limit=1 if force_rerun else None,
            )
            if manifest.divide_and_conquer and not store.exists(PLAN_DEPENDENCY_GRAPH):
                raise RuntimeError(
                    "Divide-and-conquer mode requires `02_plan/dependency_graph.md` before Terry can leave plan."
                )
            store.append_log(
                "plan_ready",
                "Prepared the backend-owned plan handoff.",
                stage="plan",
                details={"divide_and_conquer": manifest.divide_and_conquer},
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
        if manifest.divide_and_conquer:
            if not self._prerequisites_dir_ready(store):
                raise RuntimeError(
                    "Divide-and-conquer mode requires `01_enrichment/prerequisites/` before Terry can prove."
                )
            if not store.exists(PLAN_DEPENDENCY_GRAPH):
                raise RuntimeError(
                    "Divide-and-conquer mode requires `02_plan/dependency_graph.md` before Terry can prove."
                )
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

            store.append_log(
                "compile_started",
                f"Compiling proof attempt {attempt}.",
                stage="proof",
                details={"attempt": attempt, "candidate_path": candidate_relative_path},
            )
            compile_result = self.lean_runner.compile_candidate(store, candidate_relative_path, attempt)
            self._write_compile_result(store, attempt, compile_result)
            store.append_log(
                "compile_finished",
                f"Finished compiling proof attempt {attempt} with status `{compile_result.status}`.",
                stage="proof",
                details={
                    "attempt": attempt,
                    "passed": compile_result.passed,
                    "missing_toolchain": compile_result.missing_toolchain,
                    "command": compile_result.command,
                },
            )
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
        *,
        extra_stale_outputs: list[str] | None = None,
        backend_attempt_limit: int | None = None,
    ) -> AgentTurn:
        max_backend_attempts = max(
            backend_attempt_limit if backend_attempt_limit is not None else self.max_backend_retries,
            1,
        )
        for backend_attempt in range(1, max_backend_attempts + 1):
            self._clear_turn_artifacts(
                store,
                turn_dir,
                request.required_outputs,
                extra_stale_outputs=extra_stale_outputs,
                clear_compile_outputs=request.stage == BackendStage.PROOF,
            )
            store.append_log(
                "backend_stage_started",
                (
                    f"Dispatching backend `{request.stage.value}` turn "
                    f"(attempt {backend_attempt}/{max_backend_attempts})."
                ),
                stage=request.stage.value,
                details={
                    "backend_attempt": backend_attempt,
                    "max_backend_attempts": max_backend_attempts,
                    "output_dir": request.output_dir,
                    "required_outputs": request.required_outputs,
                },
            )
            start_time = time.monotonic()
            try:
                turn = self._invoke_agent_run_stage(store, request, backend_attempt)
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

                store.append_log(
                    "backend_stage_completed",
                    f"Backend `{request.stage.value}` turn finished successfully.",
                    stage=request.stage.value,
                    details={
                        "backend_attempt": backend_attempt,
                        "elapsed_seconds": round(time.monotonic() - start_time, 3),
                    },
                )
                return turn
            except Exception as exc:
                elapsed_seconds = round(time.monotonic() - start_time, 3)
                failure_message = str(exc).strip() or exc.__class__.__name__
                transient = is_transient_backend_failure(failure_message)
                store.append_log(
                    "backend_stage_failed",
                    f"Backend `{request.stage.value}` turn failed on attempt {backend_attempt}.",
                    stage=request.stage.value,
                    details={
                        "backend_attempt": backend_attempt,
                        "elapsed_seconds": elapsed_seconds,
                        "transient": transient,
                        "error": failure_message,
                    },
                )
                if transient and backend_attempt < max_backend_attempts:
                    delay_seconds = round(self.backend_retry_backoff_seconds * backend_attempt, 2)
                    store.append_log(
                        "backend_stage_retrying",
                        (
                            f"Transient backend failure during `{request.stage.value}`; "
                            f"retrying after {delay_seconds:.2f}s."
                        ),
                        stage=request.stage.value,
                        details={
                            "backend_attempt": backend_attempt,
                            "next_backend_attempt": backend_attempt + 1,
                            "sleep_seconds": delay_seconds,
                        },
                    )
                    time.sleep(delay_seconds)
                    continue
                raise
        raise RuntimeError(f"Backend `{request.stage.value}` turn failed unexpectedly.")

    def _invoke_agent_run_stage(
        self,
        store: RunStore,
        request: StageRequest,
        backend_attempt: int,
    ) -> AgentTurn:
        run_stage = self.agent.run_stage
        try:
            signature = inspect.signature(run_stage)
        except (TypeError, ValueError):  # pragma: no cover - defensive
            signature = None

        if signature is None:
            return run_stage(request)

        parameters = signature.parameters
        if "progress_callback" not in parameters and not any(
            parameter.kind == inspect.Parameter.VAR_KEYWORD
            for parameter in parameters.values()
        ):
            return run_stage(request)

        def _progress_callback(event_type: str, summary: str, details: dict[str, Any] | None = None) -> None:
            payload = dict(details or {})
            payload.setdefault("backend_attempt", backend_attempt)
            store.append_log(event_type, summary, stage=request.stage.value, details=payload)

        return run_stage(request, progress_callback=_progress_callback)

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
        if store.exists(ENRICHMENT_RELEVANT_LEAN_OBJECTS):
            artifact_paths.append(ENRICHMENT_RELEVANT_LEAN_OBJECTS)
        if manifest.divide_and_conquer and self._prerequisites_dir_ready(store):
            artifact_paths.append(ENRICHMENT_PREREQUISITES_DIR)
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
        artifact_paths = [PLAN_HANDOFF]
        if manifest.divide_and_conquer and store.exists(PLAN_DEPENDENCY_GRAPH):
            artifact_paths.append(PLAN_DEPENDENCY_GRAPH)
        return self._pause_for_checkpoint(
            store,
            manifest,
            stage=RunStage.AWAITING_PLAN_APPROVAL,
            stage_dir=PLAN_DIR,
            title="Plan Approval",
            summary="Terry is waiting for the merged plan approval before starting the prove-and-repair loop.",
            artifact_paths=artifact_paths,
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
        continue_command = self._continue_command(manifest, continue_decision)
        quick_approve_command = self._quick_approve_command(manifest)

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
                self._review_template(
                    title,
                    stage,
                    continue_decision,
                    continue_command=continue_command,
                    quick_approve_command=quick_approve_command,
                ),
            )
        store.write_text(
            checkpoint_path,
            self._checkpoint_text(
                title=title,
                stage=stage,
                summary=summary,
                artifact_paths=artifact_paths,
                review_path=review_path,
                continue_command=continue_command,
                continue_decision=continue_decision,
                quick_approve_command=quick_approve_command,
            ),
        )
        log_details: dict[str, Any] = {
            "checkpoint_path": checkpoint_path,
            "review_path": review_path,
            "continue_command": continue_command,
            "artifact_paths": artifact_paths,
        }
        if quick_approve_command is not None:
            log_details["quick_approve_command"] = quick_approve_command
        store.append_log(
            "checkpoint_opened",
            summary,
            stage=stage.value,
            details=log_details,
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
        stale_output_paths: list[str] | None = None,
    ) -> StageRequest:
        source_relative_path = self._source_input_relative_path(store)
        if source_relative_path is None:
            raise FileNotFoundError("Missing Terry source snapshot under `00_input/`.")
        input_paths = {
            "source": self._repo_relative(store.path(source_relative_path)),
            "provenance": self._repo_relative(store.path("00_input/provenance.json")),
        }
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
                "relevant_lean_objects",
                ENRICHMENT_RELEVANT_LEAN_OBJECTS,
            )
            if manifest.divide_and_conquer:
                self._maybe_add_input_path(
                    store,
                    input_paths,
                    "prerequisites_dir",
                    ENRICHMENT_PREREQUISITES_DIR,
                )
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
            if manifest.divide_and_conquer:
                self._maybe_add_input_path(
                    store,
                    input_paths,
                    "dependency_graph",
                    PLAN_DEPENDENCY_GRAPH,
                )
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
                    previous_review_path = f"{previous_attempt_dir}/{ATTEMPT_REVIEW_DIR}/{filename}"
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
            stale_output_paths=list(stale_output_paths or []),
            divide_and_conquer=manifest.divide_and_conquer,
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
        review_dir = f"{attempt_dir}/{ATTEMPT_REVIEW_DIR}"
        request = self._build_stage_request(
            store,
            manifest,
            stage=BackendStage.REVIEW,
            output_dir=review_dir,
            required_outputs=ATTEMPT_REVIEW_OUTPUTS,
            review_notes_relative_path=review_notes_relative_path,
            latest_compile_result_path=compile_path,
            attempt=attempt,
            max_attempts=max_attempts or manifest.attempt_count or self.max_attempts,
        )
        try:
            store.append_log(
                "attempt_review_started",
                f"Generating review artifacts for proof attempt {attempt}.",
                stage="proof",
                details={"attempt": attempt},
            )
            self._run_backend_stage(store, request, review_dir)
            store.append_log(
                "attempt_review_ready",
                f"Wrote Terry review artifacts for attempt {attempt}.",
                stage="proof",
                details={"attempt": attempt},
            )
        except Exception as exc:
            compile_result = self._load_compile_attempt(store, compile_path)
            self._write_fallback_attempt_review(store, attempt, compile_result, exc)
            store.append_log(
                "attempt_review_fallback",
                f"Fell back to Terry-generated review artifacts for attempt {attempt}.",
                stage="proof",
                details={"attempt": attempt, "reason": str(exc)},
            )

    def _ensure_attempt_review_ready(
        self,
        store: RunStore,
        manifest: RunManifest,
        attempt: int,
        *,
        review_notes_relative_path: str | None = None,
    ) -> None:
        if len(self._existing_attempt_review_artifacts(store, attempt)) == len(ATTEMPT_REVIEW_OUTPUTS):
            return
        self._run_attempt_review(
            store,
            manifest,
            attempt,
            review_notes_relative_path=review_notes_relative_path,
            max_attempts=manifest.attempt_count or self.max_attempts,
        )

    def _default_attempt_review_notes_path(self, store: RunStore) -> str | None:
        for relative_path in (f"{PROOF_DIR}/review.md", f"{PLAN_DIR}/review.md"):
            if self._meaningful_review_notes_path(store, relative_path) is not None:
                return relative_path
        return None

    def _write_fallback_attempt_review(
        self,
        store: RunStore,
        attempt: int,
        compile_result: CompileAttempt,
        failure: Exception,
    ) -> None:
        attempt_dir = f"{PROOF_DIR}/attempts/attempt_{attempt:04d}"
        candidate_text = store.read_text(f"{attempt_dir}/candidate.lean").strip()
        walkthrough = "\n".join(
            [
                "# Attempt Walkthrough",
                "",
                "Terry generated this fallback walkthrough because the configured review worker did not complete.",
                "Read `candidate.lean` together with the compile result to inspect the proof attempt.",
                "",
            ]
        )
        readable_candidate = "\n".join(
            [
                "-- Terry compatibility fallback for attempt review.",
                candidate_text,
                "",
            ]
        )
        error_lines = [
            "# Error Report",
            "",
            f"Compile status: {compile_result.status}.",
        ]
        if compile_result.passed:
            error_lines.append("This attempt compiled cleanly.")
        elif compile_result.diagnostics:
            error_lines.append(
                "Diagnostics: " + " | ".join(str(item) for item in compile_result.diagnostics)
            )
        if str(failure).strip():
            error_lines.extend(
                [
                    "",
                    "Review fallback reason:",
                    str(failure).strip(),
                ]
            )
        error_lines.append("")
        review_dir = f"{attempt_dir}/{ATTEMPT_REVIEW_DIR}"
        store.write_text(f"{review_dir}/{ATTEMPT_WALKTHROUGH}", walkthrough)
        store.write_text(f"{review_dir}/{ATTEMPT_READABLE_CANDIDATE}", readable_candidate)
        store.write_text(f"{review_dir}/{ATTEMPT_ERROR_REPORT}", "\n".join(error_lines))

    def _attempt_review_paths(self, attempt: int) -> list[str]:
        attempt_dir = f"{PROOF_DIR}/attempts/attempt_{attempt:04d}"
        review_dir = f"{attempt_dir}/{ATTEMPT_REVIEW_DIR}"
        return [f"{review_dir}/{relative_path}" for relative_path in ATTEMPT_REVIEW_OUTPUTS]

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
        manifest = self._load_manifest(store)
        if not self._turn_artifacts_ready(
            store,
            ENRICHMENT_DIR,
            self._enrichment_required_outputs(manifest),
        ):
            return False
        proof_status = self._load_proof_status(store)
        if proof_status is None:
            return False
        if proof_status.obtained and not store.exists(ENRICHMENT_NATURAL_LANGUAGE_PROOF):
            raise RuntimeError(
                "Enrichment recorded `obtained: true` without writing `01_enrichment/natural_language_proof.md`."
            )
        if manifest.divide_and_conquer and not self._prerequisites_dir_ready(store):
            raise RuntimeError(
                "Enrichment recorded divide-and-conquer mode without a non-empty "
                "`01_enrichment/prerequisites/` directory."
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
        stage: RunStage,
        summary: str,
        artifact_paths: list[str],
        review_path: str,
        continue_command: str,
        continue_decision: str,
        quick_approve_command: str | None = None,
    ) -> str:
        artifact_lines = "\n".join(f"- `{path}`" for path in artifact_paths)
        decision_lines = "\n".join(self._review_decision_lines(stage, continue_decision))
        lines = [
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
            "## Review Decisions",
            decision_lines,
            "",
        ]
        if quick_approve_command is not None:
            lines.extend(
                [
                    "## Quick Approve",
                    "If you have no notes, approve without editing the review file:",
                    f"`{quick_approve_command}`",
                    "",
                    "## Continue Command (after editing the review file)",
                    f"`{continue_command}`",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "## Continue Command",
                    f"`{continue_command}`",
                    "",
                ]
            )
        return "\n".join(lines)

    def _review_template(
        self,
        title: str,
        stage: RunStage,
        continue_decision: str,
        *,
        continue_command: str,
        quick_approve_command: str | None = None,
    ) -> str:
        lines = [
            f"# {title}",
            "",
            "decision: pending",
            "",
        ]
        if quick_approve_command is not None:
            lines.extend(
                [
                    "You only need to edit this file if you want to leave reviewer notes "
                    "or reject the handoff.",
                    "To approve with no comments, skip this file and run:",
                    f"`{quick_approve_command}`",
                    "",
                    "Otherwise, change `decision: pending` below to one of the values below.",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    "Change `decision: pending` to one of the values below when you are ready.",
                    "",
                ]
            )
        lines.extend(
            [
                "Review decisions:",
                *self._review_decision_lines(stage, continue_decision),
                "",
                "After editing this file, run:",
                f"`{continue_command}`",
                "",
                "Leave the `Notes:` section blank unless you want Terry to receive actual reviewer guidance.",
                "",
                "Notes:",
                "",
            ]
        )
        return "\n".join(lines)

    def _review_decision_lines(self, stage: RunStage, continue_decision: str) -> list[str]:
        if stage == RunStage.AWAITING_ENRICHMENT_APPROVAL:
            return [
                "- `approve`: Terry continues only when the enrichment proof gate is satisfied.",
                "- `reject`: Terry reruns enrichment with the notes below.",
            ]
        if stage == RunStage.AWAITING_PLAN_APPROVAL:
            return [
                "- `approve`: Terry enters the bounded prove-and-repair loop.",
                "- `reject`: Terry reruns the plan stage with the notes below.",
            ]
        if stage == RunStage.AWAITING_FINAL_APPROVAL:
            return [
                "- `approve`: Terry writes `04_final/final.lean` and completes the run.",
                "- `reject`: Terry stays paused at final.",
            ]
        if stage == RunStage.PROOF_BLOCKED:
            return [
                "- `retry`: Terry passes the notes below into the next `terry retry` proof turn.",
                "- `reject`: ignored here; proof-blocked runs continue only through `terry retry`.",
            ]
        return [
            f"- `{continue_decision}`: Terry continues.",
            "- `reject`: Terry stays paused.",
        ]

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

    def _prerequisites_dir_ready(self, store: RunStore) -> bool:
        prerequisites_dir = store.path(ENRICHMENT_PREREQUISITES_DIR)
        return prerequisites_dir.is_dir() and any(prerequisites_dir.iterdir())

    def _existing_stage_outputs(self, store: RunStore, *relative_paths: str) -> list[str]:
        return [
            self._repo_relative(store.path(relative_path))
            for relative_path in relative_paths
            if store.exists(relative_path)
        ]

    def _continue_command(self, manifest: RunManifest, continue_decision: str) -> str:
        if continue_decision == "retry":
            return self._retry_command(manifest)
        return self._resume_command(manifest)

    def _resume_command(self, manifest: RunManifest, *, approve: bool = False) -> str:
        command = [
            self.terry_command,
            "--repo-root",
            str(self.repo_root.resolve()),
        ]
        lake_path = self._persisted_lake_path()
        if lake_path:
            command.extend(["--lake-path", lake_path])
        command.extend(["resume", manifest.run_id])
        if approve:
            command.append("--approve")
        if manifest.agent_config.backend == "command":
            provider_command = (
                shlex.join(manifest.agent_config.command)
                if manifest.agent_config.command
                else "python3 path/to/provider.py"
            )
            command.extend(["--agent-command", provider_command])
        return " ".join(shlex.quote(part) for part in command)

    def _quick_approve_command(self, manifest: RunManifest) -> str | None:
        if _approvable_stage_dir(manifest.current_stage) is None:
            return None
        return self._resume_command(manifest, approve=True)

    def _retry_command(self, manifest: RunManifest, extra_attempts: int = 3) -> str:
        command = [
            self.terry_command,
            "--repo-root",
            str(self.repo_root.resolve()),
        ]
        lake_path = self._persisted_lake_path()
        if lake_path:
            command.extend(["--lake-path", lake_path])
        command.extend(["retry", manifest.run_id, "--attempts", str(extra_attempts)])
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
                if decision.decision in {continue_decision, "reject"}:
                    return decision
                return None

        existing = self._load_decision(store, f"{stage_dir}/decision.json")
        if existing is not None:
            if existing.decision != "pending":
                if existing.decision in {continue_decision, "reject"}:
                    return existing
                return None

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
            agent_config = _agent_config_from_payload(agent_config_payload)
        else:
            agent_name = payload.get("agent_name", "")
            agent_name_value = str(agent_name)
            if agent_name_value.startswith(("codex_cli:", "codex:", "claude:")):
                backend, _, model = agent_name_value.partition(":")
                if backend == "codex_cli":
                    backend = "codex"
                agent_config = AgentConfig(
                    backend=backend,
                    model=None if model in {"", "default"} else model,
                )
            elif (
                agent_name_value in {"demo", "demo_agent", "demo_formalization_agent"}
                or agent_name_value.startswith("demo:")
            ):
                agent_config = AgentConfig(backend="demo")
            else:
                agent_config = AgentConfig(backend="command")

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
        workflow_tags = payload.get("workflow_tags", list(DEFAULT_WORKFLOW_TAGS))
        divide_and_conquer = payload.get("divide_and_conquer")
        if divide_and_conquer is None:
            divide_and_conquer = "divide-and-conquer" in workflow_tags

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
            workflow_tags=workflow_tags,
            divide_and_conquer=bool(divide_and_conquer),
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

    def _source_input_relative_path(self, store: RunStore) -> str | None:
        input_dir = store.path("00_input")
        if not input_dir.exists():
            return None
        candidates = sorted(
            path
            for path in input_dir.iterdir()
            if path.is_file() and path.name != "provenance.json"
        )
        if not candidates:
            return None
        preferred = next((path for path in candidates if path.name == "source.txt"), None)
        chosen = preferred or candidates[0]
        return str(chosen.relative_to(store.run_root))

    def _snapshot_source_input(self, store: RunStore, source_path: Path) -> str:
        suffix = source_path.suffix.lower()
        snapshot_name = f"source{suffix}" if suffix else "source"
        relative_path = f"00_input/{snapshot_name}"
        destination = store.path(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, destination)
        return relative_path

    def _display_path(self, path: Path) -> str:
        resolved_path = path.resolve()
        try:
            return str(resolved_path.relative_to(self.repo_root.resolve()))
        except ValueError:
            return str(resolved_path)

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
        extra_stale_outputs: list[str] | None = None,
        clear_compile_outputs: bool = False,
    ) -> None:
        stale_paths = [
            f"{turn_dir}/request.json",
            f"{turn_dir}/prompt.md",
            f"{turn_dir}/response.txt",
        ]
        stale_paths.extend(f"{turn_dir}/{relative_path}" for relative_path in required_outputs)
        if extra_stale_outputs:
            stale_paths.extend(f"{turn_dir}/{relative_path}" for relative_path in extra_stale_outputs)
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
                shutil.rmtree(target)
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
