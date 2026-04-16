from __future__ import annotations

import json
import shutil
from pathlib import Path

from lean_formalization_engine.codex_agent import CodexCliFormalizationAgent
from lean_formalization_engine.models import RunManifest, RunStage
from lean_formalization_engine.workflow import FormalizationWorkflow

EXPECTED_IMPORT = "FormalizationEngineWorkspace.Basic"
EXPECTED_TARGET_STATEMENT = "theorem right_add_zero_nat (n : Nat) : n + 0 = n"


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _expect_stage(manifest: RunManifest, expected: RunStage, label: str) -> None:
    if manifest.current_stage != expected:
        raise RuntimeError(
            f"{label} expected stage {expected.value}, got {manifest.current_stage.value}."
        )


def _normalize_text(value: str) -> str:
    return "".join(character for character in value.lower() if character.isalnum())


def validate_theorem_spec(theorem_spec: dict[str, object]) -> None:
    conclusion = _normalize_text(str(theorem_spec.get("conclusion", "")))
    if _normalize_text("n + 0 = n") not in conclusion:
        raise RuntimeError("Spec review failed: conclusion does not match `n + 0 = n`.")

    assumptions = theorem_spec.get("assumptions", [])
    symbols = theorem_spec.get("symbols", [])
    context_text = _normalize_text(
        " ".join(str(item) for item in [*assumptions, *symbols])
    )
    if "nat" not in context_text:
        raise RuntimeError("Spec review failed: natural-number context is missing.")

    ambiguities = theorem_spec.get("ambiguities", [])
    if ambiguities:
        raise RuntimeError("Spec review failed: live Codex surfaced ambiguities.")


def validate_enrichment_report(enrichment_report: dict[str, object]) -> None:
    if not enrichment_report.get("self_contained"):
        raise RuntimeError("Enrichment review failed: theorem should be self-contained.")

    missing = [str(item) for item in enrichment_report.get("missing_prerequisites", [])]
    if missing:
        raise RuntimeError("Enrichment review failed: unexpected missing prerequisites.")


def validate_formalization_plan(plan: dict[str, object]) -> None:
    if plan.get("theorem_name") != "right_add_zero_nat":
        raise RuntimeError("Plan review failed: unexpected theorem name.")
    if plan.get("target_statement") != EXPECTED_TARGET_STATEMENT:
        raise RuntimeError("Plan review failed: unexpected target statement.")

    imports = [str(item) for item in plan.get("imports", [])]
    if EXPECTED_IMPORT not in imports:
        raise RuntimeError("Plan review failed: expected import is missing.")

    proof_sketch = " ".join(str(item) for item in plan.get("proof_sketch", []))
    if "Nat.add_zero" not in proof_sketch:
        raise RuntimeError("Plan review failed: proof sketch does not use `Nat.add_zero`.")


def validate_final_candidate(content: str) -> None:
    if EXPECTED_IMPORT not in content:
        raise RuntimeError("Final review failed: expected import is missing.")
    if EXPECTED_TARGET_STATEMENT not in content:
        raise RuntimeError("Final review failed: theorem statement drifted.")
    if "Nat.add_zero" not in content:
        raise RuntimeError("Final review failed: proof does not use `Nat.add_zero`.")
    if "sorry" in content:
        raise RuntimeError("Final review failed: candidate still contains `sorry`.")


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    run_id = "demo-codex-manual-right-add"
    run_root = repo_root / "artifacts" / "runs" / run_id
    if run_root.exists():
        shutil.rmtree(run_root)

    workflow = FormalizationWorkflow(
        repo_root=repo_root,
        agent=CodexCliFormalizationAgent(repo_root=repo_root),
    )
    source_path = repo_root / "examples" / "inputs" / "right_add_zero.md"

    manifest = workflow.run(
        source_path=source_path,
        run_id=run_id,
        auto_approve=False,
    )
    _expect_stage(manifest, RunStage.AWAITING_ENRICHMENT_REVIEW, "enrichment review")
    enrichment_report = _read_json(run_root / "03_enrichment" / "enrichment_report.json")
    validate_enrichment_report(enrichment_report)
    print(f"Enrichment review: self_contained={enrichment_report['self_contained']}")
    workflow.approve_enrichment(
        run_id,
        notes="Enrichment confirms the theorem is self-contained over Nat.",
    )

    manifest = workflow.resume(run_id, auto_approve=False)
    _expect_stage(manifest, RunStage.AWAITING_SPEC_REVIEW, "spec review")
    theorem_spec = _read_json(run_root / "04_spec" / "theorem_spec.json")
    validate_theorem_spec(theorem_spec)
    print(f"Spec review: {theorem_spec['title']}")
    print(f"Conclusion: {theorem_spec['conclusion']}")
    workflow.approve_spec(
        run_id,
        notes="Spec matches the intended right-add-zero theorem and symbols.",
    )

    manifest = workflow.resume(run_id, auto_approve=False)
    _expect_stage(manifest, RunStage.AWAITING_PLAN_REVIEW, "plan review")
    plan = _read_json(run_root / "06_plan" / "formalization_plan.json")
    validate_formalization_plan(plan)
    print(f"Plan review: {plan['theorem_name']}")
    print(f"Target: {plan['target_statement']}")
    workflow.approve_plan(
        run_id,
        notes="Plan uses the expected import, theorem target, and Nat.add_zero proof route.",
    )

    manifest = workflow.resume(run_id, auto_approve=False)
    _expect_stage(manifest, RunStage.AWAITING_FINAL_REVIEW, "final review")
    print(f"Compile attempts before final review: {manifest.attempt_count}")
    candidate_path = run_root / "10_final" / "final_candidate.lean"
    validate_final_candidate(candidate_path.read_text(encoding="utf-8"))
    print(f"Final review candidate: {candidate_path.relative_to(repo_root)}")
    workflow.approve_final(
        run_id,
        notes="Final Lean file matches the intended theorem and compiles cleanly.",
    )

    manifest = workflow.resume(run_id, auto_approve=False)
    _expect_stage(manifest, RunStage.COMPLETED, "completion")
    if manifest.final_output_path is None:
        raise RuntimeError("Completed manual demo without a final output path.")
    print(f"Run stage: {manifest.current_stage.value}")
    print(f"Attempts: {manifest.attempt_count}")
    print(f"Final output: artifacts/runs/{run_id}/{manifest.final_output_path}")


if __name__ == "__main__":
    main()
