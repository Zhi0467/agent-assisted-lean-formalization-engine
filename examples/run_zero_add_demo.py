from __future__ import annotations

import shutil
from pathlib import Path

from lean_formalization_engine.demo_agent import DemoFormalizationAgent
from lean_formalization_engine.workflow import FormalizationWorkflow


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    run_id = "demo-zero-add"
    run_root = repo_root / "artifacts" / "runs" / run_id
    if run_root.exists():
        shutil.rmtree(run_root)

    workflow = FormalizationWorkflow(repo_root=repo_root, agent=DemoFormalizationAgent())
    manifest = workflow.run(
        source_path=repo_root / "examples" / "inputs" / "zero_add.md",
        run_id=run_id,
        auto_approve=True,
    )
    print(f"Run stage: {manifest.current_stage.value}")
    print(f"Final output: {manifest.final_output_path}")
    if manifest.latest_error:
        print(f"Latest error: {manifest.latest_error}")


if __name__ == "__main__":
    main()
