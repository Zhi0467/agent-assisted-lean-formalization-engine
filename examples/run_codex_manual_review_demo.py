from __future__ import annotations

import json
import shutil
from pathlib import Path

from lean_formalization_engine.codex_agent import CodexCliFormalizationAgent
from lean_formalization_engine.models import RunManifest, RunStage
from lean_formalization_engine.workflow import FormalizationWorkflow


def _read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _expect_stage(manifest: RunManifest, expected: RunStage, label: str) -> None:
    if manifest.current_stage != expected:
        raise RuntimeError(
            f"{label} expected stage {expected.value}, got {manifest.current_stage.value}."
        )


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
    _expect_stage(manifest, RunStage.AWAITING_SPEC_REVIEW, "spec review")
    theorem_spec = _read_json(run_root / "02_spec" / "theorem_spec.json")
    print(f"Spec review: {theorem_spec['title']}")
    print(f"Conclusion: {theorem_spec['conclusion']}")
    workflow.approve_spec(
        run_id,
        notes="Spec matches the intended right-add-zero theorem and symbols.",
    )

    manifest = workflow.resume(run_id, auto_approve=False)
    _expect_stage(manifest, RunStage.AWAITING_PLAN_REVIEW, "plan review")
    plan = _read_json(run_root / "04_plan" / "formalization_plan.json")
    print(f"Plan review: {plan['theorem_name']}")
    print(f"Target: {plan['target_statement']}")
    workflow.approve_plan(
        run_id,
        notes="Plan uses the expected import, theorem target, and Nat.add_zero proof route.",
    )

    manifest = workflow.resume(run_id, auto_approve=False)
    _expect_stage(manifest, RunStage.AWAITING_FINAL_REVIEW, "final review")
    print(f"Compile attempts before final review: {manifest.attempt_count}")
    candidate_path = run_root / "08_final" / "final_candidate.lean"
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
