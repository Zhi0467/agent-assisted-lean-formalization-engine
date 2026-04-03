from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lean_formalization_engine.demo_agent import DemoFormalizationAgent
from lean_formalization_engine.lean_runner import LeanRunner
from lean_formalization_engine.models import RunStatus, SourceKind, SourceRef
from lean_formalization_engine.storage import ArtifactStore
from lean_formalization_engine.workflow import FormalizationWorkflow, WorkflowOptions


class DemoWorkflowTest(unittest.TestCase):
    def test_demo_workflow_reaches_final_or_waiting(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ArtifactStore(Path(tmp_dir) / "runs")
            workflow = FormalizationWorkflow(
                store=store,
                agent=DemoFormalizationAgent(),
                lean_runner=LeanRunner(repo_root / "lean_workspace_template"),
            )
            manifest = workflow.run(
                run_id="demo_test",
                source=SourceRef(
                    path=str(repo_root / "examples" / "inputs" / "zero_add.md"),
                    kind=SourceKind.MARKDOWN,
                    label="zero_add",
                ),
                options=WorkflowOptions(
                    auto_approve_spec=True,
                    auto_approve_plan=True,
                    auto_finalize=True,
                ),
            )
            self.assertIn(manifest.status, {RunStatus.COMPLETED, RunStatus.WAITING_HUMAN})
            self.assertTrue((store.root / "demo_test" / "manifest.json").exists())
            self.assertTrue((store.root / "demo_test" / "04_draft" / "draft_0001.lean").exists())


if __name__ == "__main__":
    unittest.main()
