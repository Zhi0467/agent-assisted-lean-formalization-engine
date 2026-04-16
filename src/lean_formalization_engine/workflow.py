from __future__ import annotations

from pathlib import Path

from .agents import FormalizationAgent
from .ingest import ingest_source
from .lean_runner import LeanRunner
from .models import (
    CompileAttempt,
    ContextPack,
    DEFAULT_WORKFLOW_TAGS,
    DEFAULT_WORKFLOW_VERSION,
    EnrichmentReport,
    FormalizationPlan,
    HumanDecision,
    LeanDraft,
    RepairContext,
    RunManifest,
    RunStage,
    SourceKind,
    SourceRef,
    TheoremExtraction,
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
        self.lean_runner = lean_runner or LeanRunner(repo_root / "lean_workspace_template")

    def run(self, source_path: Path, run_id: str, auto_approve: bool = False) -> RunManifest:
        store = RunStore(self.artifacts_root, run_id)
        source_ref, ingested = ingest_source(source_path, repo_root=self.repo_root)
        store.ensure_new()
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

        self._draft_extraction(store, source_ref, ingested.raw_text, ingested.normalized_text)
        enrichment = self._draft_enrichment(
            store,
            source_ref,
            ingested.raw_text,
            auto_approve=auto_approve,
        )
        if isinstance(enrichment, RunManifest):
            return enrichment

        theorem_spec = self._draft_spec(
            store,
            source_ref,
            ingested.raw_text,
            auto_approve=auto_approve,
        )
        if isinstance(theorem_spec, RunManifest):
            return theorem_spec

        self._build_context_pack(store, theorem_spec, enrichment)
        plan = self._draft_plan(store, auto_approve=auto_approve)
        if isinstance(plan, RunManifest):
            return plan
        return self._compile_loop(store, plan, auto_approve=auto_approve)

    def resume(self, run_id: str, auto_approve: bool = False) -> RunManifest:
        store = RunStore(self.artifacts_root, run_id)
        manifest = self._load_manifest(store)

        if manifest.current_stage == RunStage.CREATED:
            return self._resume_created_run(store, manifest, auto_approve=auto_approve)

        if manifest.current_stage == RunStage.AWAITING_ENRICHMENT_REVIEW:
            if auto_approve:
                self._seed_enrichment_approval(store)
            if not store.exists("03_enrichment/enrichment_report.approved.json"):
                return manifest
            source_text = store.path("00_input/source.txt").read_text(encoding="utf-8")
            theorem_spec = self._draft_spec(
                store,
                manifest.source,
                source_text,
                auto_approve=auto_approve,
            )
            if isinstance(theorem_spec, RunManifest):
                return theorem_spec
            enrichment = self._load_enrichment(store, approved=True)
            self._build_context_pack(store, theorem_spec, enrichment)
            plan = self._draft_plan(store, auto_approve=auto_approve)
            if isinstance(plan, RunManifest):
                return plan
            return self._compile_loop(store, plan, auto_approve=auto_approve)

        if manifest.current_stage == RunStage.AWAITING_SPEC_REVIEW:
            if auto_approve:
                self._seed_spec_approval(store)
            if not store.exists("04_spec/theorem_spec.approved.json"):
                return manifest
            theorem_spec = self._load_theorem_spec(store, approved=True)
            enrichment = self._load_enrichment(store, approved=True)
            self._build_context_pack(store, theorem_spec, enrichment)
            plan = self._draft_plan(store, auto_approve=auto_approve)
            if isinstance(plan, RunManifest):
                return plan
            return self._compile_loop(store, plan, auto_approve=auto_approve)

        if manifest.current_stage == RunStage.AWAITING_PLAN_REVIEW:
            if auto_approve:
                self._seed_plan_approval(store)
            if not store.exists("06_plan/formalization_plan.approved.json"):
                return manifest
            plan = self._load_plan(store, approved=True)
            return self._compile_loop(store, plan, auto_approve=auto_approve)

        if manifest.current_stage == RunStage.REPAIRING:
            plan = self._load_plan(store, approved=True)
            return self._compile_loop(store, plan, auto_approve=auto_approve)

        if manifest.current_stage == RunStage.AWAITING_STALL_REVIEW:
            plan = self._load_plan(store, approved=True)
            previous_result = self._load_previous_compile_result(store, manifest)
            if previous_result is None:
                return manifest

            next_attempt_limit = max(self.max_attempts, manifest.attempt_count + 1)
            if previous_result.missing_toolchain:
                return self._compile_loop(
                    store,
                    plan,
                    auto_approve=auto_approve,
                    max_attempts=next_attempt_limit,
                )

            if auto_approve:
                self._seed_stall_approval(store)
            stall_decision = self._load_decision(store, "09_review/decision.json")
            if stall_decision is None or not stall_decision.approved:
                return manifest
            if stall_decision.updated_at < manifest.updated_at:
                return manifest
            return self._compile_loop(
                store,
                plan,
                auto_approve=auto_approve,
                max_attempts=next_attempt_limit,
            )

        if manifest.current_stage == RunStage.AWAITING_FINAL_REVIEW:
            if auto_approve:
                self._seed_final_approval(store)
            if not self._decision_is_approved(store, "10_final/decision.json"):
                return manifest
            return self._complete_from_candidate(store, manifest)

        return manifest

    def approve_enrichment(self, run_id: str, notes: str = "Approved by CLI.") -> None:
        store = RunStore(self.artifacts_root, run_id)
        payload = store.read_json("03_enrichment/enrichment_report.json")
        store.write_json("03_enrichment/enrichment_report.approved.json", payload)
        store.write_json(
            "03_enrichment/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes=notes),
        )

    def approve_spec(self, run_id: str, notes: str = "Approved by CLI.") -> None:
        store = RunStore(self.artifacts_root, run_id)
        payload = store.read_json("04_spec/theorem_spec.json")
        store.write_json("04_spec/theorem_spec.approved.json", payload)
        store.write_json(
            "04_spec/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes=notes),
        )

    def approve_plan(self, run_id: str, notes: str = "Approved by CLI.") -> None:
        store = RunStore(self.artifacts_root, run_id)
        payload = store.read_json("06_plan/formalization_plan.json")
        store.write_json("06_plan/formalization_plan.approved.json", payload)
        store.write_json(
            "06_plan/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes=notes),
        )

    def approve_final(self, run_id: str, notes: str = "Approved by CLI.") -> None:
        store = RunStore(self.artifacts_root, run_id)
        store.write_json(
            "10_final/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes=notes),
        )

    def approve_stall(self, run_id: str, notes: str = "Approved one more repair attempt.") -> None:
        store = RunStore(self.artifacts_root, run_id)
        store.write_json(
            "09_review/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes=notes),
        )

    def status(self, run_id: str) -> RunManifest:
        store = RunStore(self.artifacts_root, run_id)
        return self._load_manifest(store)

    def _draft_extraction(
        self,
        store: RunStore,
        source_ref: SourceRef,
        source_text: str,
        normalized_text: str,
    ) -> TheoremExtraction:
        extraction, extraction_turn = self.agent.draft_theorem_extraction(
            source_ref,
            source_text,
            normalized_text,
        )
        self._write_agent_turn(store, "02_extraction", extraction_turn, extraction)
        store.write_json("02_extraction/theorem_extraction.json", extraction)
        store.write_text(
            "02_extraction/extracted.md",
            self._render_extraction_markdown(extraction),
        )
        return extraction

    def _draft_enrichment(
        self,
        store: RunStore,
        source_ref: SourceRef,
        source_text: str,
        auto_approve: bool,
    ) -> EnrichmentReport | RunManifest:
        extraction = self._load_extraction(store)
        extraction_markdown = store.path("02_extraction/extracted.md").read_text(encoding="utf-8")
        enrichment, enrichment_turn = self.agent.draft_theorem_enrichment(
            source_ref,
            source_text,
            extraction,
            extraction_markdown,
        )
        self._write_agent_turn(store, "03_enrichment", enrichment_turn, enrichment)
        store.write_json("03_enrichment/enrichment_report.json", enrichment)
        store.write_text(
            "03_enrichment/handoff.md",
            self._render_enrichment_handoff(extraction, enrichment),
        )

        if auto_approve:
            self._seed_enrichment_approval(store)

        if not store.exists("03_enrichment/enrichment_report.approved.json"):
            manifest = self._load_manifest(store)
            manifest.current_stage = RunStage.AWAITING_ENRICHMENT_REVIEW
            return self._save_manifest(store, manifest)

        return self._load_enrichment(store, approved=True)

    def _draft_spec(
        self,
        store: RunStore,
        source_ref: SourceRef,
        source_text: str,
        auto_approve: bool,
    ) -> TheoremSpec | RunManifest:
        extraction = self._load_extraction(store)
        enrichment = self._load_enrichment(store, approved=True)
        theorem_spec, spec_turn = self.agent.draft_theorem_spec(
            source_ref,
            source_text,
            extraction,
            enrichment,
        )
        self._write_agent_turn(store, "04_spec", spec_turn, theorem_spec)
        store.write_json("04_spec/theorem_spec.json", theorem_spec)

        if auto_approve:
            self._seed_spec_approval(store)

        if not store.exists("04_spec/theorem_spec.approved.json"):
            manifest = self._load_manifest(store)
            manifest.current_stage = RunStage.AWAITING_SPEC_REVIEW
            return self._save_manifest(store, manifest)

        return self._load_theorem_spec(store, approved=True)

    def _draft_plan(self, store: RunStore, auto_approve: bool) -> FormalizationPlan | RunManifest:
        theorem_spec = self._load_theorem_spec(store, approved=True)
        enrichment = self._load_enrichment(store, approved=True)
        context_payload = store.read_json("05_context/context_pack.json")
        context_pack = ContextPack(**context_payload)
        plan, plan_turn = self.agent.draft_formalization_plan(
            theorem_spec,
            context_pack,
            enrichment,
        )
        self._write_agent_turn(store, "06_plan", plan_turn, plan)
        store.write_json("06_plan/formalization_plan.json", plan)

        if auto_approve:
            self._seed_plan_approval(store)

        if not store.exists("06_plan/formalization_plan.approved.json"):
            manifest = self._load_manifest(store)
            manifest.current_stage = RunStage.AWAITING_PLAN_REVIEW
            return self._save_manifest(store, manifest)

        return self._load_plan(store, approved=True)

    def _resume_created_run(
        self,
        store: RunStore,
        manifest: RunManifest,
        auto_approve: bool,
    ) -> RunManifest:
        source_text = store.path("00_input/source.txt").read_text(encoding="utf-8")
        normalized_text = store.path("01_normalized/normalized.md").read_text(encoding="utf-8")

        if store.exists("06_plan/formalization_plan.approved.json"):
            plan = self._load_plan(store, approved=True)
            return self._compile_loop(store, plan, auto_approve=auto_approve)

        if store.exists("06_plan/formalization_plan.json"):
            if auto_approve:
                self._seed_plan_approval(store)
            if not store.exists("06_plan/formalization_plan.approved.json"):
                manifest.current_stage = RunStage.AWAITING_PLAN_REVIEW
                return self._save_manifest(store, manifest)
            plan = self._load_plan(store, approved=True)
            return self._compile_loop(store, plan, auto_approve=auto_approve)

        if store.exists("04_spec/theorem_spec.approved.json"):
            theorem_spec = self._load_theorem_spec(store, approved=True)
            enrichment = self._load_enrichment(store, approved=True)
            if not store.exists("05_context/context_pack.json"):
                self._build_context_pack(store, theorem_spec, enrichment)
            plan = self._draft_plan(store, auto_approve=auto_approve)
            if isinstance(plan, RunManifest):
                return plan
            return self._compile_loop(store, plan, auto_approve=auto_approve)

        if store.exists("04_spec/theorem_spec.json"):
            if auto_approve:
                self._seed_spec_approval(store)
            if not store.exists("04_spec/theorem_spec.approved.json"):
                manifest.current_stage = RunStage.AWAITING_SPEC_REVIEW
                return self._save_manifest(store, manifest)
            theorem_spec = self._load_theorem_spec(store, approved=True)
            enrichment = self._load_enrichment(store, approved=True)
            self._build_context_pack(store, theorem_spec, enrichment)
            plan = self._draft_plan(store, auto_approve=auto_approve)
            if isinstance(plan, RunManifest):
                return plan
            return self._compile_loop(store, plan, auto_approve=auto_approve)

        if store.exists("03_enrichment/enrichment_report.approved.json"):
            theorem_spec = self._draft_spec(
                store,
                manifest.source,
                source_text,
                auto_approve=auto_approve,
            )
            if isinstance(theorem_spec, RunManifest):
                return theorem_spec
            enrichment = self._load_enrichment(store, approved=True)
            self._build_context_pack(store, theorem_spec, enrichment)
            plan = self._draft_plan(store, auto_approve=auto_approve)
            if isinstance(plan, RunManifest):
                return plan
            return self._compile_loop(store, plan, auto_approve=auto_approve)

        if store.exists("03_enrichment/enrichment_report.json"):
            if auto_approve:
                self._seed_enrichment_approval(store)
            if not store.exists("03_enrichment/enrichment_report.approved.json"):
                manifest.current_stage = RunStage.AWAITING_ENRICHMENT_REVIEW
                return self._save_manifest(store, manifest)
            theorem_spec = self._draft_spec(
                store,
                manifest.source,
                source_text,
                auto_approve=auto_approve,
            )
            if isinstance(theorem_spec, RunManifest):
                return theorem_spec
            enrichment = self._load_enrichment(store, approved=True)
            self._build_context_pack(store, theorem_spec, enrichment)
            plan = self._draft_plan(store, auto_approve=auto_approve)
            if isinstance(plan, RunManifest):
                return plan
            return self._compile_loop(store, plan, auto_approve=auto_approve)

        if not store.exists("02_extraction/theorem_extraction.json"):
            self._draft_extraction(store, manifest.source, source_text, normalized_text)

        enrichment = self._draft_enrichment(
            store,
            manifest.source,
            source_text,
            auto_approve=auto_approve,
        )
        if isinstance(enrichment, RunManifest):
            return enrichment

        theorem_spec = self._draft_spec(
            store,
            manifest.source,
            source_text,
            auto_approve=auto_approve,
        )
        if isinstance(theorem_spec, RunManifest):
            return theorem_spec

        self._build_context_pack(store, theorem_spec, enrichment)
        plan = self._draft_plan(store, auto_approve=auto_approve)
        if isinstance(plan, RunManifest):
            return plan
        return self._compile_loop(store, plan, auto_approve=auto_approve)

    def _compile_loop(
        self,
        store: RunStore,
        plan: FormalizationPlan,
        auto_approve: bool,
        max_attempts: int | None = None,
    ) -> RunManifest:
        manifest = self._load_manifest(store)
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
            )
            draft, draft_turn = self.agent.draft_lean_file(plan, repair_context)
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
                    "09_review/stall_report.md",
                    "Lean toolchain is unavailable, so the run stopped before proving the compile gate.\n\n"
                    "Install Lean via elan, then resume the run or rerun the example.\n",
                )
                return manifest

            manifest.current_stage = RunStage.REPAIRING
            manifest.latest_error = compile_result.stderr.strip() or compile_result.status
            self._save_manifest(store, manifest)
            previous_draft = draft
            previous_result = compile_result

        manifest.current_stage = RunStage.AWAITING_STALL_REVIEW
        manifest.latest_error = previous_result.stderr.strip() if previous_result else "Unknown failure."
        self._save_manifest(store, manifest)
        store.write_text(
            "09_review/stall_report.md",
            "The compile loop hit the retry cap.\n\n"
            "Next action should be one of:\n"
            "- revise the enrichment handoff\n"
            "- revise the theorem spec\n"
            "- revise the formalization plan\n"
            "- allow one more targeted repair attempt\n",
        )
        return manifest

    def _build_context_pack(
        self,
        store: RunStore,
        theorem_spec: TheoremSpec,
        enrichment: EnrichmentReport,
    ) -> ContextPack:
        notes = [
            f"Title: {theorem_spec.title}",
            f"Recommended scope: {enrichment.recommended_scope}",
            f"Difficulty: {enrichment.difficulty_assessment}",
            "Start from repo-local examples before adding retrieval or external corpora.",
        ]
        notes.extend(
            f"Carry this prerequisite into the plan: {item}"
            for item in enrichment.required_plan_additions
        )
        context_pack = ContextPack(
            recommended_imports=["FormalizationEngineWorkspace.Basic"],
            local_examples=["examples/inputs/zero_add.md"],
            notes=notes,
        )
        store.write_json("05_context/context_pack.json", context_pack)
        return context_pack

    def _queue_final_review(
        self,
        store: RunStore,
        manifest: RunManifest,
        draft: LeanDraft,
        auto_approve: bool,
    ) -> RunManifest:
        candidate_relative_path = "10_final/final_candidate.lean"
        store.write_text(candidate_relative_path, draft.content)
        store.write_text(
            "10_final/final_report.md",
            "Candidate Lean file passed the compile gate and the no-`sorry` quality check.\n",
        )
        store.write_json(
            "10_final/provenance.json",
            {
                "agent_name": self.agent.name,
                "candidate_path": candidate_relative_path,
                "generated_at": utc_now(),
            },
        )
        if auto_approve:
            self._seed_final_approval(store)
        if not self._decision_is_approved(store, "10_final/decision.json"):
            manifest.current_stage = RunStage.AWAITING_FINAL_REVIEW
            manifest.final_output_path = candidate_relative_path
            return self._save_manifest(store, manifest)
        return self._complete_from_candidate(store, manifest)

    def _complete_from_candidate(self, store: RunStore, manifest: RunManifest) -> RunManifest:
        candidate_relative_path = "10_final/final_candidate.lean"
        final_relative_path = "10_final/final.lean"
        candidate_path = store.path(candidate_relative_path)
        store.write_text(final_relative_path, candidate_path.read_text(encoding="utf-8"))
        manifest.current_stage = RunStage.COMPLETED
        manifest.updated_at = utc_now()
        manifest.final_output_path = final_relative_path
        manifest.latest_error = None
        return self._save_manifest(store, manifest)

    def _seed_enrichment_approval(self, store: RunStore) -> None:
        payload = store.read_json("03_enrichment/enrichment_report.json")
        store.write_json("03_enrichment/enrichment_report.approved.json", payload)
        store.write_json(
            "03_enrichment/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes="Auto-approved."),
        )

    def _seed_spec_approval(self, store: RunStore) -> None:
        payload = store.read_json("04_spec/theorem_spec.json")
        store.write_json("04_spec/theorem_spec.approved.json", payload)
        store.write_json(
            "04_spec/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes="Auto-approved."),
        )

    def _seed_plan_approval(self, store: RunStore) -> None:
        payload = store.read_json("06_plan/formalization_plan.json")
        store.write_json("06_plan/formalization_plan.approved.json", payload)
        store.write_json(
            "06_plan/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes="Auto-approved."),
        )

    def _seed_final_approval(self, store: RunStore) -> None:
        store.write_json(
            "10_final/decision.json",
            HumanDecision(approved=True, updated_at=utc_now(), notes="Auto-approved."),
        )

    def _seed_stall_approval(self, store: RunStore) -> None:
        store.write_json(
            "09_review/decision.json",
            HumanDecision(
                approved=True,
                updated_at=utc_now(),
                notes="Auto-approved one more repair attempt.",
            ),
        )

    def _write_agent_turn(self, store: RunStore, stage_dir: str, turn, parsed_output) -> None:
        store.write_json(f"{stage_dir}/request.json", turn.request_payload)
        store.write_text(f"{stage_dir}/prompt.md", turn.prompt)
        store.write_json(f"{stage_dir}/raw_response.json", {"raw_response": turn.raw_response})
        store.write_json(f"{stage_dir}/parsed_output.json", parsed_output)

    def _write_attempt(self, store: RunStore, attempt: int, turn, draft: LeanDraft) -> None:
        attempt_dir = f"07_draft/attempt_{attempt:04d}"
        self._write_agent_turn(store, attempt_dir, turn, draft)
        store.write_text(f"{attempt_dir}/draft.lean", draft.content)

    def _write_compile_result(self, store: RunStore, attempt: int, compile_result: CompileAttempt) -> None:
        attempt_dir = f"08_compile/attempt_{attempt:04d}"
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
            workflow_version=payload.get("workflow_version", DEFAULT_WORKFLOW_VERSION),
            workflow_tags=payload.get("workflow_tags", list(DEFAULT_WORKFLOW_TAGS)),
            attempt_count=payload.get("attempt_count", 0),
            latest_error=payload.get("latest_error"),
            final_output_path=payload.get("final_output_path"),
        )

    def _load_extraction(self, store: RunStore) -> TheoremExtraction:
        payload = store.read_json("02_extraction/theorem_extraction.json")
        return TheoremExtraction(**payload)

    def _load_enrichment(self, store: RunStore, approved: bool) -> EnrichmentReport:
        filename = (
            "03_enrichment/enrichment_report.approved.json"
            if approved
            else "03_enrichment/enrichment_report.json"
        )
        payload = store.read_json(filename)
        return EnrichmentReport(**payload)

    def _load_theorem_spec(self, store: RunStore, approved: bool) -> TheoremSpec:
        filename = (
            "04_spec/theorem_spec.approved.json"
            if approved
            else "04_spec/theorem_spec.json"
        )
        payload = store.read_json(filename)
        return TheoremSpec(**payload)

    def _load_plan(self, store: RunStore, approved: bool) -> FormalizationPlan:
        filename = (
            "06_plan/formalization_plan.approved.json"
            if approved
            else "06_plan/formalization_plan.json"
        )
        payload = store.read_json(filename)
        return FormalizationPlan(**payload)

    def _load_previous_compile_result(
        self,
        store: RunStore,
        manifest: RunManifest,
    ) -> CompileAttempt | None:
        if manifest.attempt_count <= 0:
            return None
        result_path = f"08_compile/attempt_{manifest.attempt_count:04d}/result.json"
        if not store.exists(result_path):
            return None
        payload = store.read_json(result_path)
        return CompileAttempt(**payload)

    def _load_previous_draft(
        self,
        store: RunStore,
        manifest: RunManifest,
    ) -> LeanDraft | None:
        if manifest.attempt_count <= 0:
            return None
        draft_path = f"07_draft/attempt_{manifest.attempt_count:04d}/parsed_output.json"
        if not store.exists(draft_path):
            return None
        payload = store.read_json(draft_path)
        return LeanDraft(**payload)

    def _load_decision(self, store: RunStore, relative_path: str) -> HumanDecision | None:
        if not store.exists(relative_path):
            return None
        payload = store.read_json(relative_path)
        return HumanDecision(**payload)

    def _decision_is_approved(self, store: RunStore, relative_path: str) -> bool:
        decision = self._load_decision(store, relative_path)
        return bool(decision and decision.approved)
