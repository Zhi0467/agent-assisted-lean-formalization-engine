from __future__ import annotations

import shutil
import sys
from pathlib import Path

from lean_formalization_engine.models import AgentConfig
from lean_formalization_engine.subprocess_agent import SubprocessFormalizationAgent
from lean_formalization_engine.workflow import FormalizationWorkflow


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    run_id = "demo-command-agent"
    run_root = repo_root / "artifacts" / "runs" / run_id
    if run_root.exists():
        shutil.rmtree(run_root)

    provider_script = repo_root / "examples" / "providers" / "scripted_repair_provider.py"
    command = [sys.executable, str(provider_script)]
    workflow = FormalizationWorkflow(
        repo_root=repo_root,
        agent=SubprocessFormalizationAgent(command),
        agent_config=AgentConfig(backend="command", command=command),
    )
    manifest = workflow.prove(
        source_path=repo_root / "examples" / "inputs" / "zero_add.md",
        run_id=run_id,
        auto_approve=True,
    )
    print(f"Run stage: {manifest.current_stage.value}")
    print(f"Attempts: {manifest.attempt_count}")
    if manifest.final_output_path:
        print(f"Final output: artifacts/runs/{run_id}/{manifest.final_output_path}")
    if manifest.latest_error:
        print(f"Latest error: {manifest.latest_error}")


if __name__ == "__main__":
    main()
