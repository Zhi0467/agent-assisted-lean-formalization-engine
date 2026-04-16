from __future__ import annotations

import json
import shutil
from pathlib import Path

from lean_formalization_engine.codex_agent import CodexCliFormalizationAgent
from lean_formalization_engine.models import AgentConfig, RunManifest, RunStage
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


def _write_review_decision(path: Path, decision: str, notes: str) -> None:
    path.write_text(
        "\n".join(
            [
                f"# {path.parent.name} review",
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

    assumptions = [str(item) for item in plan.get("assumptions", [])]
    if "n : Nat" not in assumptions:
        raise RuntimeError("Plan review failed: natural-number assumption is missing.")

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
        agent_config=AgentConfig(backend="codex"),
    )
    source_path = repo_root / "examples" / "inputs" / "right_add_zero.md"

    manifest = workflow.prove(
        source_path=source_path,
        run_id=run_id,
        auto_approve=False,
    )
    _expect_stage(manifest, RunStage.AWAITING_ENRICHMENT_APPROVAL, "enrichment review")
    enrichment_report = _read_json(run_root / "01_enrichment" / "enrichment_report.json")
    validate_enrichment_report(enrichment_report)
    _write_review_decision(
        run_root / "01_enrichment" / "review.md",
        "approve",
        "The theorem is self-contained over Nat and ready for plan approval.",
    )

    manifest = workflow.resume(run_id, auto_approve=False)
    _expect_stage(manifest, RunStage.AWAITING_PLAN_APPROVAL, "plan review")
    plan = _read_json(run_root / "02_plan" / "formalization_plan.json")
    validate_formalization_plan(plan)
    _write_review_decision(
        run_root / "02_plan" / "review.md",
        "approve",
        "The theorem statement, imports, and proof route are all correct.",
    )

    manifest = workflow.resume(run_id, auto_approve=False)
    _expect_stage(manifest, RunStage.AWAITING_FINAL_APPROVAL, "final review")
    candidate_path = run_root / "04_final" / "final_candidate.lean"
    validate_final_candidate(candidate_path.read_text(encoding="utf-8"))
    _write_review_decision(
        run_root / "04_final" / "review.md",
        "approve",
        "The compiling Lean file matches the approved plan.",
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
