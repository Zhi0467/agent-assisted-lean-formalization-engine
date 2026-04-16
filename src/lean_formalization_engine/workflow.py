from __future__ import annotations

import shlex
from pathlib import Path

from .agents import FormalizationAgent
from .ingest import ingest_source
from .lean_runner import LeanRunner
from .models import (
    AgentConfig,
    CompileAttempt,
    ContextPack,
    DEFAULT_WORKFLOW_TAGS,
    DEFAULT_WORKFLOW_VERSION,
    EnrichmentReport,
    FormalizationPlan,
    LeanDraft,
    RepairContext,
    ReviewDecision,
    RunManifest,
    RunStage,
    SourceKind,
    SourceRef,
    TheoremExtraction,
    utc_now,
)
from .storage import RunStore
from .template_manager import discover_workspace_template

ENRICHMENT_DIR = "01_enrichment"
PLAN_DIR = "02_plan"
PROOF_DIR = "03_proof"
FINAL_DIR = "04_final"
EXTRACTION_TURN_DIR = f"{ENRICHMENT_DIR}/extraction_turn"
ENRICHMENT_TURN_DIR = f"{ENRICHMENT_DIR}/enrichment_turn"

LEGACY_NORMALIZED_PATH = "01_normalized/normalized.md"
LEGACY_EXTRACTION_JSON = "02_extraction/theorem_extraction.json"
LEGACY_EXTRACTION_MARKDOWN = "02_extraction/extracted.md"
LEGACY_ENRICHMENT_JSON = "03_enrichment/enrichment_report.json"
LEGACY_ENRICHMENT_APPROVED_JSON = "03_enrichment/enrichment_report.approved.json"
LEGACY_ENRICHMENT_HANDOFF = "03_enrichment/handoff.md"
LEGACY_ENRICHMENT_DECISION = "03_enrichment/decision.json"
LEGACY_SPEC_JSON = "04_spec/theorem_spec.json"
LEGACY_SPEC_APPROVED_JSON = "04_spec/theorem_spec.approved.json"
LEGACY_CONTEXT_PACK_JSON = "05_context/context_pack.json"
LEGACY_PLAN_JSON = "06_plan/formalization_plan.json"
LEGACY_PLAN_APPROVED_JSON = "06_plan/formalization_plan.approved.json"
LEGACY_PLAN_DECISION = "06_plan/decision.json"
LEGACY_DRAFT_TEMPLATE = "07_draft/attempt_{attempt:04d}/parsed_output.json"
LEGACY_COMPILE_TEMPLATE = "08_compile/attempt_{attempt:04d}/result.json"
LEGACY_STALL_REPORT = "09_review/stall_report.md"
LEGACY_STALL_DECISION = "09_review/decision.json"
LEGACY_FINAL_CANDIDATE = "10_final/final_candidate.lean"
LEGACY_FINAL_REPORT = "10_final/final_report.md"
LEGACY_FINAL_DECISION = "10_final/decision.json"


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
        self.lean_runner = lean_runner or LeanRunner(repo_root / "lean_workspace_template")

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
            store.append_log(
                "checkpoint_approved",
                "Enrichment checkpoint approved.",
                stage="enrichment",
                details={"notes": decision.notes},
            )
            plan = self._draft_plan(
                store,
                manifest.source,
                store.read_text("00_input/source.txt"),
                auto_approve,
                human_feedback=self._decision_guidance(decision),
            )
            if isinstance(plan, RunManifest):
                return plan
            return self._prove_loop(store, plan, auto_approve=auto_approve)

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
            store.append_log(
                "checkpoint_approved",
                "Plan checkpoint approved.",
                stage="plan",
                details={"notes": decision.notes},
            )
            plan = self._load_plan(store)
            return self._prove_loop(
                store,
                plan,
                auto_approve=auto_approve,
                human_feedback=self._decision_guidance(decision),
            )

        if manifest.current_stage == RunStage.PROVING:
            if self._final_candidate_path(store) is not None:
                if self._resolve_checkpoint_decision(
                    store,
                    FINAL_DIR,
                    continue_decision="approve",
                    auto_approve=auto_approve,
                ):
                    return self._complete_from_candidate(store, manifest)
                return self._pause_for_final(store, manifest)
            plan = self._load_plan(store)
            return self._prove_loop(store, plan, auto_approve=auto_approve)

        if manifest.current_stage == RunStage.PROOF_BLOCKED:
            decision = self._resolve_checkpoint_decision(
                store,
                PROOF_DIR,
                continue_decision="retry",
                auto_approve=auto_approve,
            )
            if decision is None:
                if self._checkpoint_surface_missing(store, PROOF_DIR):
                    return self._pause_for_proof_blocked(
                        store,
                        manifest,
                        reason=(
                            "Terry paused in the prove-and-repair loop.\n\n"
                            "Review the blocker and loop summary, then set `decision: retry` "
                            "when you want exactly one more attempt."
                        ),
                    )
                return manifest
            store.append_log(
                "proof_retry_approved",
                "Human approved one more prove-and-repair attempt.",
                stage="proof",
                details={"notes": decision.notes},
            )
            plan = self._load_plan(store)
            return self._prove_loop(
                store,
                plan,
                auto_approve=auto_approve,
                max_attempts=manifest.attempt_count + 1,
                human_feedback=self._decision_guidance(decision),
            )

        if manifest.current_stage == RunStage.AWAITING_FINAL_APPROVAL:
            decision = self._resolve_checkpoint_decision(
                store,
                FINAL_DIR,
                continue_decision="approve",
                auto_approve=auto_approve,
            )
            if decision is None:
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

        return manifest

    def status(self, run_id: str) -> RunManifest:
        store = RunStore(self.artifacts_root, run_id)
        return self._load_manifest(store)

    def _resume_from_created(
        self,
        store: RunStore,
        manifest: RunManifest,
        *,
        auto_approve: bool,
    ) -> RunManifest:
        source_text = store.read_text("00_input/source.txt")
        normalized_text = store.read_text(
            self._require_existing_path(store, "00_input/normalized.md", LEGACY_NORMALIZED_PATH)
        )

        if self._final_candidate_path(store) is not None:
            if self._resolve_checkpoint_decision(
                store,
                FINAL_DIR,
                continue_decision="approve",
                auto_approve=auto_approve,
            ):
                return self._complete_from_candidate(store, manifest)
            return self._pause_for_final(store, manifest)

        if self._plan_payload_path(store) is not None:
            decision = self._resolve_checkpoint_decision(
                store,
                PLAN_DIR,
                continue_decision="approve",
                auto_approve=auto_approve,
            )
            if decision:
                return self._prove_loop(
                    store,
                    self._load_plan(store),
                    auto_approve=auto_approve,
                    human_feedback=self._decision_guidance(decision),
                )
            return self._pause_for_plan(store, manifest)

        if self._enrichment_payload_path(store) is not None:
            decision = self._resolve_checkpoint_decision(
                store,
                ENRICHMENT_DIR,
                continue_decision="approve",
                auto_approve=auto_approve,
            )
            if decision:
                plan = self._draft_plan(
                    store,
                    manifest.source,
                    source_text,
                    auto_approve,
                    human_feedback=self._decision_guidance(decision),
                )
                if isinstance(plan, RunManifest):
                    return plan
                return self._prove_loop(store, plan, auto_approve=auto_approve)
            return self._pause_for_enrichment(store, manifest)

        if self._extraction_payload_path(store) is None:
            extraction = self.agent.draft_theorem_extraction(
                manifest.source,
                source_text,
                normalized_text,
            )
            self._write_extraction(store, extraction[0], extraction[1])

        enrichment = self._draft_enrichment(store, manifest.source, source_text, auto_approve)
        if isinstance(enrichment, RunManifest):
            return enrichment

        plan = self._draft_plan(store, manifest.source, source_text, auto_approve)
        if isinstance(plan, RunManifest):
            return plan
        return self._prove_loop(store, plan, auto_approve=auto_approve)

    def _draft_enrichment(
        self,
        store: RunStore,
        source_ref: SourceRef,
        source_text: str,
        auto_approve: bool,
    ) -> EnrichmentReport | RunManifest:
        extraction = self._load_extraction(store)
        extraction_markdown = self._render_extraction_markdown(extraction)
        enrichment, turn = self.agent.draft_theorem_enrichment(
            source_ref,
            source_text,
            extraction,
            extraction_markdown,
        )
        self._write_agent_turn(store, ENRICHMENT_TURN_DIR, turn, enrichment)
        store.write_json(f"{ENRICHMENT_DIR}/extraction.json", extraction)
        store.write_text(f"{ENRICHMENT_DIR}/extraction.md", extraction_markdown)
        store.write_json(f"{ENRICHMENT_DIR}/enrichment_report.json", enrichment)
        store.write_text(
            f"{ENRICHMENT_DIR}/handoff.md",
            self._render_enrichment_handoff(extraction, enrichment),
        )
        store.append_log(
            "enrichment_ready",
            "Prepared enrichment handoff and reviewer summary.",
            stage="enrichment",
        )

        if auto_approve:
            self._write_decision(
                store,
                ENRICHMENT_DIR,
                ReviewDecision("approve", utc_now(), "Auto-approved."),
            )
            return enrichment

        manifest = self._load_manifest(store)
        return self._pause_for_enrichment(store, manifest)

    def _draft_plan(
        self,
        store: RunStore,
        source_ref: SourceRef,
        source_text: str,
        auto_approve: bool,
        human_feedback: str | None = None,
    ) -> FormalizationPlan | RunManifest:
        extraction = self._load_extraction(store)
        enrichment = self._load_enrichment(store)
        context_pack = self._build_context_pack(extraction, enrichment, human_feedback=human_feedback)
        store.write_json(f"{PLAN_DIR}/context_pack.json", context_pack)

        plan, turn = self.agent.draft_formalization_plan(
            source_ref,
            source_text,
            extraction,
            enrichment,
            context_pack,
        )
        self._write_agent_turn(store, PLAN_DIR, turn, plan)
        store.write_json(f"{PLAN_DIR}/formalization_plan.json", plan)
        store.write_text(f"{PLAN_DIR}/summary.md", self._render_plan_summary(plan))
        store.append_log(
            "plan_ready",
            "Prepared the merged mathematical-meaning and Lean-plan checkpoint.",
            stage="plan",
            details={"theorem_name": plan.theorem_name},
        )

        if auto_approve:
            self._write_decision(
                store,
                PLAN_DIR,
                ReviewDecision("approve", utc_now(), "Auto-approved."),
            )
            return plan

        manifest = self._load_manifest(store)
        return self._pause_for_plan(store, manifest)

    def _prove_loop(
        self,
        store: RunStore,
        plan: FormalizationPlan,
        *,
        auto_approve: bool,
        max_attempts: int | None = None,
        human_feedback: str | None = None,
    ) -> RunManifest:
        manifest = self._load_manifest(store)
        manifest.current_stage = RunStage.PROVING
        self._save_manifest(store, manifest)
        store.append_log(
            "prove_loop_started",
            "Started the bounded prove-and-repair loop.",
            stage="proof",
            details={
                "attempt_count": manifest.attempt_count,
                "max_attempts": max_attempts or self.max_attempts,
            },
        )

        previous_result = self._load_previous_compile_result(store, manifest)
        previous_draft = self._load_previous_draft(store, manifest)
        attempt_limit = max_attempts or self.max_attempts

        while manifest.attempt_count < attempt_limit:
            attempt = manifest.attempt_count + 1
            repair_context = RepairContext(
                current_attempt=attempt,
                max_attempts=attempt_limit,
                prior_attempts=attempt - 1,
                attempts_remaining=attempt_limit - attempt + 1,
                previous_draft=previous_draft,
                previous_result=previous_result,
                human_feedback=human_feedback,
            )
            store.append_log(
                "prove_attempt_started",
                f"Starting proof attempt {attempt} of {attempt_limit}.",
                stage="proof",
                details={"attempt": attempt},
            )
            draft, turn = self.agent.draft_lean_file(plan, repair_context)
            self._write_attempt(store, attempt, turn, draft)
            compile_result = self.lean_runner.compile_draft(store, draft, attempt)
            self._write_compile_result(store, attempt, compile_result)

            manifest.attempt_count = attempt
            manifest.updated_at = utc_now()

            if compile_result.passed:
                store.append_log(
                    "prove_attempt_passed",
                    f"Attempt {attempt} compiled successfully.",
                    stage="proof",
                    details={"attempt": attempt},
                )
                return self._queue_final_review(store, manifest, draft, compile_result, auto_approve)

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
                        "Fix the toolchain, then set `decision: retry` in the review file to allow "
                        "one more attempt."
                    ),
                )

            manifest.latest_error = compile_result.stderr.strip() or compile_result.status
            self._save_manifest(store, manifest)
            previous_draft = draft
            previous_result = compile_result
            human_feedback = None
            store.append_log(
                "prove_attempt_failed",
                f"Attempt {attempt} failed and Terry is trying the next repair step.",
                stage="proof",
                details={"attempt": attempt, "status": compile_result.status},
            )

        manifest.latest_error = previous_result.stderr.strip() if previous_result else "Unknown failure."
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
                "If you want Terry to take one more attempt on the same locked plan, set "
                "`decision: retry` in the proof review file and keep any guidance in the notes."
            ),
        )

    def _queue_final_review(
        self,
        store: RunStore,
        manifest: RunManifest,
        draft: LeanDraft,
        compile_result: CompileAttempt,
        auto_approve: bool,
    ) -> RunManifest:
        candidate_relative_path = f"{FINAL_DIR}/final_candidate.lean"
        store.write_text(candidate_relative_path, draft.content)
        store.write_text(
            f"{FINAL_DIR}/final_report.md",
            self._render_final_report(draft, compile_result),
        )
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
        candidate_relative_path = self._require_existing_path(
            store,
            f"{FINAL_DIR}/final_candidate.lean",
            LEGACY_FINAL_CANDIDATE,
        )
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
        return self._pause_for_checkpoint(
            store,
            manifest,
            stage=RunStage.AWAITING_ENRICHMENT_APPROVAL,
            stage_dir=ENRICHMENT_DIR,
            title="Enrichment Approval",
            summary="Terry is waiting for enrichment approval before locking the formalization scope.",
            artifact_paths=self._enrichment_artifact_paths(store),
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
            artifact_paths=self._plan_artifact_paths(store),
            continue_decision="approve",
        )

    def _pause_for_proof_blocked(
        self,
        store: RunStore,
        manifest: RunManifest,
        *,
        reason: str,
    ) -> RunManifest:
        blocker_text = reason
        if store.exists(LEGACY_STALL_REPORT):
            blocker_text = store.read_text(LEGACY_STALL_REPORT)
        store.write_text(f"{PROOF_DIR}/blocker.md", self._render_proof_blocker(blocker_text))
        if manifest.attempt_count > 0:
            store.write_text(f"{PROOF_DIR}/loop.md", self._render_loop_summary(store, manifest.attempt_count))
        return self._pause_for_checkpoint(
            store,
            manifest,
            stage=RunStage.PROOF_BLOCKED,
            stage_dir=PROOF_DIR,
            title="Proof Loop Blocked",
            summary="Terry paused inside the prove-and-repair loop and needs explicit permission to retry.",
            artifact_paths=self._proof_artifact_paths(store, manifest),
            continue_decision="retry",
        )

    def _pause_for_final(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        latest_attempt = max(manifest.attempt_count, 1)
        return self._pause_for_checkpoint(
            store,
            manifest,
            stage=RunStage.AWAITING_FINAL_APPROVAL,
            stage_dir=FINAL_DIR,
            title="Final Approval",
            summary="Terry is waiting for final approval of the compiling Lean candidate.",
            artifact_paths=self._final_artifact_paths(store, latest_attempt),
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
        resume_command = self._resume_command(manifest.run_id)

        self._write_decision(
            store,
            stage_dir,
            ReviewDecision("pending", utc_now(), ""),
        )
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

    def _build_context_pack(
        self,
        extraction: TheoremExtraction,
        enrichment: EnrichmentReport,
        *,
        human_feedback: str | None = None,
    ) -> ContextPack:
        notes = [
            f"Title: {extraction.title}",
            f"Recommended scope: {enrichment.recommended_scope}",
            f"Difficulty: {enrichment.difficulty_assessment}",
            "Use the local Terry workspace scaffold before adding extra imports.",
        ]
        notes.extend(
            f"Carry this prerequisite into the plan: {item}"
            for item in enrichment.required_plan_additions
        )
        if human_feedback:
            notes.append(f"Reviewer guidance from the enrichment checkpoint: {human_feedback}")
        return ContextPack(
            recommended_imports=["FormalizationEngineWorkspace.Basic"],
            local_examples=["examples/inputs/zero_add.md"],
            notes=notes,
        )

    def _write_extraction(
        self,
        store: RunStore,
        extraction: TheoremExtraction,
        turn,
    ) -> None:
        self._write_agent_turn(store, EXTRACTION_TURN_DIR, turn, extraction)
        store.write_json(f"{ENRICHMENT_DIR}/extraction.json", extraction)
        store.write_text(f"{ENRICHMENT_DIR}/extraction.md", self._render_extraction_markdown(extraction))
        store.append_log(
            "extraction_ready",
            "Prepared the internal theorem extraction package.",
            stage="enrichment",
        )

    def _write_agent_turn(self, store: RunStore, stage_dir: str, turn, parsed_output) -> None:
        store.write_json(f"{stage_dir}/request.json", turn.request_payload)
        store.write_text(f"{stage_dir}/prompt.md", turn.prompt)
        store.write_json(f"{stage_dir}/raw_response.json", {"raw_response": turn.raw_response})
        store.write_json(f"{stage_dir}/parsed_output.json", parsed_output)

    def _write_attempt(self, store: RunStore, attempt: int, turn, draft: LeanDraft) -> None:
        attempt_dir = f"{PROOF_DIR}/attempts/attempt_{attempt:04d}"
        self._write_agent_turn(store, attempt_dir, turn, draft)
        store.write_text(f"{attempt_dir}/draft.lean", draft.content)

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
        store.write_text(f"{PROOF_DIR}/loop.md", self._render_loop_summary(store, attempt))

    def _render_extraction_markdown(self, extraction: TheoremExtraction) -> str:
        sections = [
            f"# {extraction.title}",
            "",
            "## Informal Statement",
            extraction.informal_statement,
            "",
            "## Definitions",
            *self._render_bullets(extraction.definitions),
            "",
            "## Lemmas",
            *self._render_bullets(extraction.lemmas),
            "",
            "## Propositions",
            *self._render_bullets(extraction.propositions),
            "",
            "## Dependencies",
            *self._render_bullets(extraction.dependencies),
            "",
            "## Notes",
            *self._render_bullets(extraction.notes),
            "",
        ]
        return "\n".join(sections)

    def _render_enrichment_handoff(
        self,
        extraction: TheoremExtraction,
        enrichment: EnrichmentReport,
    ) -> str:
        verdict = "self-contained" if enrichment.self_contained else "not self-contained"
        sections = [
            f"# Enrichment Handoff: {extraction.title}",
            "",
            f"Verdict: The extracted theorem package is {verdict}.",
            "",
            enrichment.human_handoff.strip(),
            "",
            "## Satisfied Prerequisites",
            *self._render_bullets(enrichment.satisfied_prerequisites),
            "",
            "## Missing Prerequisites",
            *self._render_bullets(enrichment.missing_prerequisites),
            "",
            "## Required Plan Additions",
            *self._render_bullets(enrichment.required_plan_additions),
            "",
            "## Recommended Scope",
            enrichment.recommended_scope,
            "",
            "## Difficulty",
            enrichment.difficulty_assessment,
            "",
            "## Open Questions",
            *self._render_bullets(enrichment.open_questions),
            "",
            "## Next Steps",
            *self._render_bullets(enrichment.next_steps),
            "",
        ]
        return "\n".join(sections)

    def _render_plan_summary(self, plan: FormalizationPlan) -> str:
        sections = [
            f"# Plan Summary: {plan.title}",
            "",
            plan.human_summary.strip(),
            "",
            "## Mathematical Meaning",
            f"Assumptions: {', '.join(plan.assumptions) if plan.assumptions else 'none'}",
            f"Conclusion: {plan.conclusion}",
            f"Paraphrase: {plan.paraphrase}",
            "",
            "## Lean Target",
            f"Theorem name: {plan.theorem_name}",
            f"Target statement: {plan.target_statement}",
            "",
            "## Imports",
            *self._render_bullets(plan.imports),
            "",
            "## Proof Sketch",
            *self._render_bullets(plan.proof_sketch),
            "",
            "## Explicit Ambiguities",
            *self._render_bullets(plan.ambiguities),
            "",
            "## Prerequisites To Formalize",
            *self._render_bullets(plan.prerequisites_to_formalize),
            "",
        ]
        return "\n".join(sections)

    def _render_loop_summary(self, store: RunStore, latest_attempt: int) -> str:
        sections = [
            "# Prove-And-Repair Loop",
            "",
            f"Latest completed attempt: {latest_attempt}",
            "",
            "## Attempts",
        ]
        for attempt in range(1, latest_attempt + 1):
            payload = self._load_attempt_result_payload(store, attempt)
            if payload is None:
                continue
            status = payload.get("status", "unknown")
            diagnostics = payload.get("diagnostics", [])
            sections.append(f"- attempt {attempt}: {status}")
            if diagnostics:
                sections.append(f"  diagnostics: {' | '.join(str(item) for item in diagnostics)}")
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

    def _render_final_report(self, draft: LeanDraft, compile_result: CompileAttempt) -> str:
        diagnostics = "\n".join(f"- {line}" for line in compile_result.diagnostics) or "- none"
        return "\n".join(
            [
                "# Final Candidate",
                "",
                f"The theorem `{draft.theorem_name}` compiled successfully.",
                "",
                "## Rationale",
                draft.rationale,
                "",
                "## Compile Diagnostics Snapshot",
                diagnostics,
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

    def _resume_command(self, run_id: str) -> str:
        command = [
            self.terry_command,
            "--repo-root",
            str(self.repo_root.resolve()),
        ]
        lake_path = self._persisted_lake_path()
        if lake_path:
            command.extend(["--lake-path", lake_path])
        command.extend(["resume", run_id])
        return " ".join(shlex.quote(part) for part in command)

    def _resolve_checkpoint_decision(
        self,
        store: RunStore,
        stage_dir: str,
        *,
        continue_decision: str,
        auto_approve: bool,
    ) -> ReviewDecision | None:
        existing = self._load_decision(store, f"{stage_dir}/decision.json")
        if existing is not None and existing.decision == continue_decision:
            return existing

        legacy = self._load_legacy_checkpoint_decision(store, stage_dir, continue_decision)
        if legacy is not None:
            return legacy

        if auto_approve:
            decision = ReviewDecision(continue_decision, utc_now(), "Auto-approved.")
            self._write_decision(store, stage_dir, decision)
            return decision

        review_path = f"{stage_dir}/review.md"
        if not store.exists(review_path):
            return None
        decision = self._parse_review_file(store.read_text(review_path))
        if decision is None or decision.decision != continue_decision:
            return None
        self._write_decision(store, stage_dir, decision)
        return decision

    def _write_decision(self, store: RunStore, stage_dir: str, decision: ReviewDecision) -> None:
        store.write_json(f"{stage_dir}/decision.json", decision)

    def _parse_review_file(self, content: str) -> ReviewDecision | None:
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
        notes = "\n".join(notes_lines).strip()
        return ReviewDecision(decision=decision_value, updated_at=utc_now(), notes=notes)

    def _render_bullets(self, items: list[str]) -> list[str]:
        if not items:
            return ["- none"]
        return [f"- {item}" for item in items]

    def _save_manifest(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        manifest.updated_at = utc_now()
        store.write_json("manifest.json", manifest)
        return manifest

    def _load_manifest(self, store: RunStore) -> RunManifest:
        payload = store.read_json("manifest.json")
        stage_value = payload["current_stage"]
        if stage_value == "awaiting_spec_review":
            raise RuntimeError(
                "This run predates Terry's merged plan checkpoint and cannot be resumed automatically. "
                "Start a fresh Terry run from the same source."
            )
        stage_aliases = {
            "awaiting_enrichment_review": RunStage.AWAITING_ENRICHMENT_APPROVAL,
            "awaiting_plan_review": RunStage.AWAITING_PLAN_APPROVAL,
            "repairing": RunStage.PROVING,
            "awaiting_stall_review": RunStage.PROOF_BLOCKED,
            "awaiting_final_review": RunStage.AWAITING_FINAL_APPROVAL,
        }
        resolved_stage = stage_aliases.get(stage_value, stage_value)

        agent_config_payload = payload.get("agent_config")
        if isinstance(agent_config_payload, dict):
            agent_config = AgentConfig(**agent_config_payload)
        else:
            agent_name = payload.get("agent_name", "")
            if str(agent_name).startswith("codex_cli:"):
                model = str(agent_name).split(":", 1)[1]
                agent_config = AgentConfig(
                    backend="codex",
                    codex_model=None if model == "default" else model,
                )
            elif str(agent_name).startswith("subprocess:"):
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
            current_stage=RunStage(resolved_stage),
            lake_path=payload.get("lake_path"),
            workflow_version=payload.get("workflow_version", DEFAULT_WORKFLOW_VERSION),
            workflow_tags=payload.get("workflow_tags", list(DEFAULT_WORKFLOW_TAGS)),
            attempt_count=payload.get("attempt_count", 0),
            latest_error=payload.get("latest_error"),
            final_output_path=payload.get("final_output_path"),
        )

    def _load_extraction(self, store: RunStore) -> TheoremExtraction:
        return TheoremExtraction(
            **store.read_json(
                self._require_existing_path(
                    store,
                    f"{ENRICHMENT_DIR}/extraction.json",
                    LEGACY_EXTRACTION_JSON,
                )
            )
        )

    def _load_enrichment(self, store: RunStore) -> EnrichmentReport:
        return EnrichmentReport(
            **store.read_json(
                self._require_existing_path(
                    store,
                    f"{ENRICHMENT_DIR}/enrichment_report.json",
                    LEGACY_ENRICHMENT_APPROVED_JSON,
                    LEGACY_ENRICHMENT_JSON,
                )
            )
        )

    def _load_plan(self, store: RunStore) -> FormalizationPlan:
        payload = store.read_json(
            self._require_existing_path(
                store,
                f"{PLAN_DIR}/formalization_plan.json",
                LEGACY_PLAN_APPROVED_JSON,
                LEGACY_PLAN_JSON,
            )
        )
        if "human_summary" in payload:
            return FormalizationPlan(**payload)

        theorem_spec = store.read_json(
            self._require_existing_path(
                store,
                LEGACY_SPEC_APPROVED_JSON,
                LEGACY_SPEC_JSON,
            )
        )
        title = theorem_spec.get("title") or payload.get("theorem_name", "Legacy theorem")
        paraphrase = theorem_spec.get("paraphrase") or theorem_spec.get("informal_statement") or title
        conclusion = theorem_spec.get("conclusion", "")
        assumptions = theorem_spec.get("assumptions", [])
        return FormalizationPlan(
            title=title,
            informal_statement=theorem_spec.get("informal_statement", title),
            assumptions=assumptions,
            conclusion=conclusion,
            symbols=theorem_spec.get("symbols", []),
            ambiguities=theorem_spec.get("ambiguities", []),
            paraphrase=paraphrase,
            theorem_name=payload["theorem_name"],
            imports=payload.get("imports", []),
            prerequisites_to_formalize=payload.get("prerequisites_to_formalize", []),
            helper_definitions=payload.get("helper_definitions", []),
            target_statement=payload.get("target_statement", ""),
            proof_sketch=payload.get("proof_sketch", []),
            human_summary=(
                f"Imported legacy plan for `{payload['theorem_name']}`. "
                f"Assumptions: {', '.join(assumptions) if assumptions else 'none'}. "
                f"Conclusion: {conclusion or 'unspecified'}."
            ),
        )

    def _load_previous_compile_result(
        self,
        store: RunStore,
        manifest: RunManifest,
    ) -> CompileAttempt | None:
        if manifest.attempt_count <= 0:
            return None
        result_path = self._existing_path(
            store,
            f"{PROOF_DIR}/attempts/attempt_{manifest.attempt_count:04d}/compile_result.json",
            LEGACY_COMPILE_TEMPLATE.format(attempt=manifest.attempt_count),
        )
        if result_path is None:
            return None
        return CompileAttempt(**store.read_json(result_path))

    def _load_previous_draft(
        self,
        store: RunStore,
        manifest: RunManifest,
    ) -> LeanDraft | None:
        if manifest.attempt_count <= 0:
            return None
        draft_path = self._existing_path(
            store,
            f"{PROOF_DIR}/attempts/attempt_{manifest.attempt_count:04d}/parsed_output.json",
            LEGACY_DRAFT_TEMPLATE.format(attempt=manifest.attempt_count),
        )
        if draft_path is None:
            return None
        if not store.exists(draft_path):
            return None
        return LeanDraft(**store.read_json(draft_path))

    def _load_decision(self, store: RunStore, relative_path: str) -> ReviewDecision | None:
        if not store.exists(relative_path):
            return None
        payload = store.read_json(relative_path)
        if "decision" in payload:
            return ReviewDecision(**payload)
        if payload.get("approved"):
            return ReviewDecision("approve", payload.get("updated_at", utc_now()), payload.get("notes", ""))
        return None

    def _existing_path(self, store: RunStore, *candidates: str) -> str | None:
        for candidate in candidates:
            if store.exists(candidate):
                return candidate
        return None

    def _require_existing_path(self, store: RunStore, *candidates: str) -> str:
        resolved = self._existing_path(store, *candidates)
        if resolved is None:
            raise FileNotFoundError(f"Missing expected Terry artifact. Tried: {', '.join(candidates)}")
        return resolved

    def _checkpoint_surface_missing(self, store: RunStore, stage_dir: str) -> bool:
        return not (
            store.exists(f"{stage_dir}/checkpoint.md")
            and store.exists(f"{stage_dir}/review.md")
        )

    def _extraction_payload_path(self, store: RunStore) -> str | None:
        return self._existing_path(store, f"{ENRICHMENT_DIR}/extraction.json", LEGACY_EXTRACTION_JSON)

    def _enrichment_payload_path(self, store: RunStore) -> str | None:
        return self._existing_path(
            store,
            f"{ENRICHMENT_DIR}/enrichment_report.json",
            LEGACY_ENRICHMENT_APPROVED_JSON,
            LEGACY_ENRICHMENT_JSON,
        )

    def _plan_payload_path(self, store: RunStore) -> str | None:
        return self._existing_path(
            store,
            f"{PLAN_DIR}/formalization_plan.json",
            LEGACY_PLAN_APPROVED_JSON,
            LEGACY_PLAN_JSON,
        )

    def _final_candidate_path(self, store: RunStore) -> str | None:
        return self._existing_path(store, f"{FINAL_DIR}/final_candidate.lean", LEGACY_FINAL_CANDIDATE)

    def _attempt_result_path(self, store: RunStore, attempt: int) -> str:
        return self._require_existing_path(
            store,
            f"{PROOF_DIR}/attempts/attempt_{attempt:04d}/compile_result.json",
            LEGACY_COMPILE_TEMPLATE.format(attempt=attempt),
        )

    def _load_attempt_result_payload(self, store: RunStore, attempt: int) -> dict[str, object] | None:
        result_path = self._existing_path(
            store,
            f"{PROOF_DIR}/attempts/attempt_{attempt:04d}/compile_result.json",
            LEGACY_COMPILE_TEMPLATE.format(attempt=attempt),
        )
        if result_path is None:
            return None
        return store.read_json(result_path)

    def _collect_artifact_paths(self, store: RunStore, *groups: tuple[str, ...]) -> list[str]:
        paths: list[str] = []
        for group in groups:
            resolved = self._existing_path(store, *group)
            if resolved is not None:
                paths.append(resolved)
        return paths

    def _enrichment_artifact_paths(self, store: RunStore) -> list[str]:
        return self._collect_artifact_paths(
            store,
            (f"{ENRICHMENT_DIR}/handoff.md", LEGACY_ENRICHMENT_HANDOFF),
            (f"{ENRICHMENT_DIR}/enrichment_report.json", LEGACY_ENRICHMENT_JSON),
            (f"{ENRICHMENT_DIR}/extraction.md", LEGACY_EXTRACTION_MARKDOWN),
        )

    def _plan_artifact_paths(self, store: RunStore) -> list[str]:
        if store.exists(f"{PLAN_DIR}/formalization_plan.json"):
            return self._collect_artifact_paths(
                store,
                (f"{PLAN_DIR}/formalization_plan.json",),
                (f"{PLAN_DIR}/summary.md",),
                (f"{PLAN_DIR}/context_pack.json",),
            )
        return self._collect_artifact_paths(
            store,
            (LEGACY_SPEC_APPROVED_JSON, LEGACY_SPEC_JSON),
            (LEGACY_PLAN_JSON, LEGACY_PLAN_APPROVED_JSON),
            (LEGACY_CONTEXT_PACK_JSON,),
        )

    def _proof_artifact_paths(self, store: RunStore, manifest: RunManifest) -> list[str]:
        compile_path = None
        if manifest.attempt_count > 0:
            compile_path = self._existing_path(
                store,
                f"{PROOF_DIR}/attempts/attempt_{manifest.attempt_count:04d}/compile_result.json",
                LEGACY_COMPILE_TEMPLATE.format(attempt=manifest.attempt_count),
            )
        groups: list[tuple[str, ...]] = [
            (f"{PROOF_DIR}/blocker.md", LEGACY_STALL_REPORT),
            (f"{PROOF_DIR}/loop.md",),
        ]
        if compile_path is not None:
            groups.append((compile_path,))
        return self._collect_artifact_paths(store, *groups)

    def _final_artifact_paths(self, store: RunStore, latest_attempt: int) -> list[str]:
        compile_path = self._existing_path(
            store,
            f"{PROOF_DIR}/attempts/attempt_{latest_attempt:04d}/compile_result.json",
            LEGACY_COMPILE_TEMPLATE.format(attempt=latest_attempt),
        )
        groups: list[tuple[str, ...]] = [
            (f"{FINAL_DIR}/final_candidate.lean", LEGACY_FINAL_CANDIDATE),
            (f"{FINAL_DIR}/final_report.md", LEGACY_FINAL_REPORT),
        ]
        if compile_path is not None:
            groups.append((compile_path,))
        return self._collect_artifact_paths(store, *groups)

    def _load_legacy_checkpoint_decision(
        self,
        store: RunStore,
        stage_dir: str,
        continue_decision: str,
    ) -> ReviewDecision | None:
        if stage_dir == ENRICHMENT_DIR:
            if not store.exists(LEGACY_ENRICHMENT_APPROVED_JSON):
                return None
            return self._map_legacy_decision(store, LEGACY_ENRICHMENT_DECISION, continue_decision)
        if stage_dir == PLAN_DIR:
            if not store.exists(LEGACY_PLAN_APPROVED_JSON):
                return None
            return self._map_legacy_decision(store, LEGACY_PLAN_DECISION, continue_decision)
        if stage_dir == PROOF_DIR and store.exists(LEGACY_STALL_DECISION):
            return self._map_legacy_decision(store, LEGACY_STALL_DECISION, continue_decision)
        if stage_dir == FINAL_DIR and store.exists(LEGACY_FINAL_DECISION):
            return self._map_legacy_decision(store, LEGACY_FINAL_DECISION, continue_decision)
        return None

    def _map_legacy_decision(
        self,
        store: RunStore,
        relative_path: str,
        continue_decision: str,
    ) -> ReviewDecision | None:
        decision = self._load_decision(store, relative_path)
        if decision is None:
            return ReviewDecision(continue_decision, utc_now(), "Imported from legacy workflow.")
        if decision.decision not in {"approve", continue_decision}:
            return None
        return ReviewDecision(continue_decision, decision.updated_at, decision.notes)

    def _persisted_lake_path(self) -> str | None:
        if not self.lean_runner.lake_path:
            return None
        configured = Path(self.lean_runner.lake_path).expanduser()
        if configured.is_absolute() or "/" in self.lean_runner.lake_path:
            return str(configured.resolve())
        return self.lean_runner.lake_path

    def _decision_guidance(self, decision: ReviewDecision | None) -> str | None:
        if decision is None:
            return None
        notes = decision.notes.strip()
        if notes in {"", "Auto-approved.", "Imported from legacy workflow."}:
            return None
        return notes
