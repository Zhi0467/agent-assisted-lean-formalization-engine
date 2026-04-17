from __future__ import annotations

import shutil
from pathlib import Path

from lean_formalization_engine.codex_agent import CodexCliFormalizationAgent
from lean_formalization_engine.models import AgentConfig, RunManifest, RunStage
from lean_formalization_engine.workflow import FormalizationWorkflow

EXPECTED_GOAL_FRAGMENT = "n + 0 = n"


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


def validate_enrichment_handoff(content: str) -> None:
    if "self-contained" not in content.lower():
        raise RuntimeError("Enrichment review failed: theorem should be marked self-contained.")
    if "missing prerequisites: none" not in content.lower():
        raise RuntimeError("Enrichment review failed: unexpected missing prerequisites.")


def validate_plan_handoff(content: str) -> None:
    lowered = content.lower()
    if EXPECTED_GOAL_FRAGMENT not in content:
        raise RuntimeError("Plan review failed: expected the right-add-zero target to stay in scope.")
    if "nat" not in lowered:
        raise RuntimeError("Plan review failed: the theorem should still stay over Nat.")
    if "proof" not in lowered:
        raise RuntimeError("Plan review failed: expected some proof guidance in the handoff.")


def validate_final_candidate(content: str) -> None:
    if EXPECTED_GOAL_FRAGMENT not in content:
        raise RuntimeError("Final review failed: candidate drifted away from right-add-zero.")
    if "theorem" not in content and "example" not in content:
        raise RuntimeError("Final review failed: expected a Lean declaration in the candidate.")
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
    validate_enrichment_handoff((run_root / "01_enrichment" / "handoff.md").read_text(encoding="utf-8"))
    _write_review_decision(
        run_root / "01_enrichment" / "review.md",
        "approve",
        "The theorem is self-contained over Nat and ready for plan approval.",
    )

    manifest = workflow.resume(run_id, auto_approve=False)
    _expect_stage(manifest, RunStage.AWAITING_PLAN_APPROVAL, "plan review")
    validate_plan_handoff((run_root / "02_plan" / "handoff.md").read_text(encoding="utf-8"))
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
