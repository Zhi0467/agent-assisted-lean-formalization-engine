from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from lean_formalization_engine.cli import (
    _load_manifest,
    _resolve_agent_command,
    _resolve_lake_path,
    _resume_agent_config,
    build_agent,
    build_agent_config,
    render_manifest_summary,
)
from lean_formalization_engine.codex_agent import CodexCliFormalizationAgent
from lean_formalization_engine.models import AgentConfig, BackendStage, RunManifest, RunStage, SourceKind, SourceRef, StageRequest
from lean_formalization_engine.subprocess_agent import ProviderResponseError, SubprocessFormalizationAgent
from lean_formalization_engine.template_manager import discover_workspace_template, resolve_workspace_template


class CliAndBackendSurfaceTest(unittest.TestCase):
    def _write_manifest(
        self,
        repo_root: Path,
        run_id: str,
        *,
        current_stage: str,
        attempt_count: int = 0,
    ) -> Path:
        run_root = repo_root / "artifacts" / "runs" / run_id
        run_root.mkdir(parents=True, exist_ok=True)
        (run_root / "manifest.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "source": {"path": "input.md", "kind": "markdown"},
                    "agent_name": "demo_zero_add_agent",
                    "agent_config": {"backend": "demo"},
                    "template_dir": str((repo_root / "lean_workspace_template").resolve()),
                    "created_at": "2026-04-16T00:00:00Z",
                    "updated_at": "2026-04-16T00:00:00Z",
                    "current_stage": current_stage,
                    "attempt_count": attempt_count,
                }
            ),
            encoding="utf-8",
        )
        return run_root

    def _write_basic_legacy_inputs(self, run_root: Path) -> None:
        (run_root / "00_input").mkdir(parents=True, exist_ok=True)
        (run_root / "00_input" / "source.txt").write_text(
            "For every natural number n, 0 + n = n.\n",
            encoding="utf-8",
        )
        (run_root / "00_input" / "normalized.md").write_text(
            "For every natural number n, 0 + n = n.\n",
            encoding="utf-8",
        )
        (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")

    def test_build_agent_config_defaults_to_codex_without_codex(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(agent_backend=None, agent_command=None, codex_model=None)
        config = build_agent_config(args, project_root)
        self.assertEqual(config.backend, "codex")
        self.assertIsNone(config.codex_model)

    def test_build_agent_config_defaults_to_codex_when_available(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(agent_backend=None, agent_command=None, codex_model=None)
        with patch("lean_formalization_engine.cli.shutil.which", return_value="/usr/bin/codex"):
            config = build_agent_config(args, project_root)
        self.assertEqual(config.backend, "codex")
        self.assertIsNone(config.codex_model)

    def test_build_agent_config_resolves_repo_relative_command(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(
            agent_backend="command",
            agent_command="python3 examples/providers/scripted_repair_provider.py",
            codex_model=None,
        )
        config = build_agent_config(args, project_root)
        self.assertEqual(config.backend, "command")
        self.assertEqual(
            config.command,
            [
                "python3",
                str(project_root / "examples" / "providers" / "scripted_repair_provider.py"),
            ],
        )

    def test_build_agent_config_rejects_codex_model_for_command_backend(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(
            agent_backend="command",
            agent_command="python3 examples/providers/scripted_repair_provider.py",
            codex_model="gpt-test",
        )
        with self.assertRaisesRegex(ValueError, "--codex-model"):
            build_agent_config(args, project_root)

    def test_build_agent_config_rejects_command_flags_for_demo_backend(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(
            agent_backend="demo",
            agent_command="python3 examples/providers/scripted_repair_provider.py",
            codex_model=None,
        )
        with self.assertRaisesRegex(ValueError, "--agent-command"):
            build_agent_config(args, project_root)

    def test_build_agent_config_rejects_command_flag_for_codex_backend(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(
            agent_backend="codex",
            agent_command="python3 examples/providers/scripted_repair_provider.py",
            codex_model="gpt-test",
        )
        with self.assertRaisesRegex(ValueError, "--agent-command"):
            build_agent_config(args, project_root)

    def test_resolve_agent_command_preserves_python_module_invocation(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        resolved = _resolve_agent_command(["python3", "-m", "examples"], project_root)
        self.assertEqual(resolved, ["python3", "-m", "examples"])

    def test_resolve_lake_path_anchors_repo_relative_executable(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        resolved = _resolve_lake_path("tools/lake", project_root)
        self.assertEqual(resolved, str((project_root / "tools" / "lake").resolve()))

    def test_build_agent_uses_stored_command_backend(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        config = AgentConfig(
            backend="command",
            command=["python3", str(project_root / "examples" / "providers" / "scripted_repair_provider.py")],
        )
        agent = build_agent(config, project_root)
        self.assertIsInstance(agent, SubprocessFormalizationAgent)
        self.assertEqual(agent.command, config.command)

    def test_missing_codex_agent_raises_when_a_turn_is_requested(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        config = AgentConfig(backend="codex")
        with patch("lean_formalization_engine.cli.shutil.which", return_value=None):
            agent = build_agent(config, project_root)
        with self.assertRaisesRegex(ValueError, "codex"):
            agent.run_stage(
                StageRequest(
                    stage=BackendStage.ENRICHMENT,
                    run_id="demo",
                    repo_root=str(project_root),
                    run_dir="artifacts/runs/demo",
                    output_dir="artifacts/runs/demo/01_enrichment",
                    input_paths={"source": "a", "normalized_source": "b", "provenance": "c"},
                    required_outputs=["handoff.md"],
                )
            )

    def test_resume_agent_config_prefers_explicit_command_override(self) -> None:
        manifest = RunManifest(
            run_id="demo",
            source=SourceRef(path="input.md", kind=SourceKind.MARKDOWN),
            agent_name="subprocess:provider.py",
            agent_config=AgentConfig(backend="command", command=["python3", "/tmp/stale.py"]),
            template_dir="/tmp/template",
            created_at="2026-04-16T00:00:00Z",
            updated_at="2026-04-16T00:00:00Z",
            current_stage=RunStage.AWAITING_PLAN_APPROVAL,
        )
        args = Namespace(
            agent_command="python3 examples/providers/scripted_repair_provider.py",
            legacy_agent_command=None,
            agent_backend="command",
            legacy_agent_backend=None,
            codex_model=None,
            legacy_codex_model=None,
        )
        repo_root = Path(__file__).resolve().parents[1]
        config = _resume_agent_config(manifest, args, repo_root)
        self.assertEqual(
            config.command,
            ["python3", str(repo_root / "examples" / "providers" / "scripted_repair_provider.py")],
        )

    def test_resume_agent_config_rejects_backend_switch(self) -> None:
        manifest = RunManifest(
            run_id="demo",
            source=SourceRef(path="input.md", kind=SourceKind.MARKDOWN),
            agent_name="demo_zero_add_agent",
            agent_config=AgentConfig(backend="demo"),
            template_dir="/tmp/template",
            created_at="2026-04-16T00:00:00Z",
            updated_at="2026-04-16T00:00:00Z",
            current_stage=RunStage.AWAITING_ENRICHMENT_APPROVAL,
        )
        args = Namespace(
            agent_command="python3 examples/providers/scripted_repair_provider.py",
            legacy_agent_command=None,
            agent_backend="command",
            legacy_agent_backend=None,
            codex_model=None,
            legacy_codex_model=None,
        )
        repo_root = Path(__file__).resolve().parents[1]
        with self.assertRaisesRegex(ValueError, "keep the backend recorded in the manifest"):
            _resume_agent_config(manifest, args, repo_root)

    def test_codex_agent_uses_workspace_write_and_file_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "demo"
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "01_enrichment").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("source", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text("normalized", encoding="utf-8")
            (run_root / "01_enrichment" / "handoff.md").write_text("# Enrichment\n", encoding="utf-8")
            (run_root / "01_enrichment" / "review.md").write_text("# Review\n", encoding="utf-8")

            request = StageRequest(
                stage=BackendStage.PLAN,
                run_id="demo",
                repo_root=str(repo_root),
                run_dir="artifacts/runs/demo",
                output_dir="artifacts/runs/demo/02_plan",
                input_paths={
                    "source": "artifacts/runs/demo/00_input/source.txt",
                    "normalized_source": "artifacts/runs/demo/00_input/normalized.md",
                    "enrichment_handoff": "artifacts/runs/demo/01_enrichment/handoff.md",
                    "enrichment_review": "artifacts/runs/demo/01_enrichment/review.md",
                },
                required_outputs=["handoff.md"],
                review_notes_path="artifacts/runs/demo/01_enrichment/review.md",
            )

            def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
                sandbox_root = Path(command[5])
                (sandbox_root / request.output_dir).mkdir(parents=True, exist_ok=True)
                (sandbox_root / request.output_dir / "handoff.md").write_text("# Plan Handoff\n", encoding="utf-8")
                return subprocess.CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout="wrote 02_plan/handoff.md\n",
                    stderr="",
                )

            with patch("lean_formalization_engine.codex_agent.subprocess.run", side_effect=fake_run) as run_mock:
                agent = CodexCliFormalizationAgent(repo_root=repo_root, model="gpt-test", executable="codex")
                turn = agent.run_stage(request)

            command = run_mock.call_args.args[0]
            prompt = run_mock.call_args.kwargs["input"]
            self.assertIn("workspace-write", command)
            self.assertEqual(command[:5], ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "-C"])
            self.assertNotEqual(command[5], str(repo_root))
            self.assertIn("Required outputs:", prompt)
            self.assertIn("artifacts/runs/demo/02_plan/handoff.md", prompt)
            self.assertIn("enrichment_handoff", prompt)
            self.assertEqual(turn.raw_response, "wrote 02_plan/handoff.md")
            self.assertEqual((run_root / "02_plan" / "handoff.md").read_text(encoding="utf-8"), "# Plan Handoff\n")

    def test_codex_agent_only_copies_output_dir_back_to_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            (repo_root / "README.md").write_text("original", encoding="utf-8")
            run_root = repo_root / "artifacts" / "runs" / "demo"
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("source", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text("normalized", encoding="utf-8")
            (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")

            request = StageRequest(
                stage=BackendStage.ENRICHMENT,
                run_id="demo",
                repo_root=str(repo_root),
                run_dir="artifacts/runs/demo",
                output_dir="artifacts/runs/demo/01_enrichment",
                input_paths={
                    "source": "artifacts/runs/demo/00_input/source.txt",
                    "normalized_source": "artifacts/runs/demo/00_input/normalized.md",
                    "provenance": "artifacts/runs/demo/00_input/provenance.json",
                },
                required_outputs=["handoff.md"],
            )

            def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
                sandbox_root = Path(command[5])
                (sandbox_root / "README.md").write_text("mutated", encoding="utf-8")
                output_dir = sandbox_root / request.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "handoff.md").write_text("# Enrichment\n", encoding="utf-8")
                return subprocess.CompletedProcess(args=command, returncode=0, stdout="ok", stderr="")

            with patch("lean_formalization_engine.codex_agent.subprocess.run", side_effect=fake_run):
                agent = CodexCliFormalizationAgent(repo_root=repo_root, executable="codex")
                agent.run_stage(request)

            self.assertEqual((repo_root / "README.md").read_text(encoding="utf-8"), "original")
            self.assertEqual((run_root / "01_enrichment" / "handoff.md").read_text(encoding="utf-8"), "# Enrichment\n")

    def test_codex_agent_missing_cli_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "demo" / "00_input"
            run_root.mkdir(parents=True, exist_ok=True)
            (run_root / "source.txt").write_text("source", encoding="utf-8")
            (run_root / "normalized.md").write_text("normalized", encoding="utf-8")
            (run_root / "provenance.json").write_text("{}", encoding="utf-8")

            request = StageRequest(
                stage=BackendStage.ENRICHMENT,
                run_id="demo",
                repo_root=str(repo_root),
                run_dir="artifacts/runs/demo",
                output_dir="artifacts/runs/demo/01_enrichment",
                input_paths={
                    "source": "artifacts/runs/demo/00_input/source.txt",
                    "normalized_source": "artifacts/runs/demo/00_input/normalized.md",
                    "provenance": "artifacts/runs/demo/00_input/provenance.json",
                },
                required_outputs=["handoff.md"],
            )
            with patch(
                "lean_formalization_engine.codex_agent.subprocess.run",
                side_effect=FileNotFoundError("codex"),
            ):
                agent = CodexCliFormalizationAgent(repo_root=repo_root)
                with self.assertRaisesRegex(RuntimeError, "codex"):
                    agent.run_stage(request)

    def test_subprocess_agent_passes_file_request_and_reads_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            provider_script = repo_root / "provider.py"
            provider_script.write_text(
                "\n".join(
                    [
                        "from __future__ import annotations",
                        "import json",
                        "import pathlib",
                        "import sys",
                        "",
                        "request = json.load(sys.stdin)",
                        "repo_root = pathlib.Path(request['repo_root'])",
                        "output_dir = repo_root / request['output_dir']",
                        "output_dir.mkdir(parents=True, exist_ok=True)",
                        "(output_dir / 'handoff.md').write_text('# ok\\n', encoding='utf-8')",
                        "json.dump({'prompt': 'stage prompt', 'raw_response': request['stage']}, sys.stdout)",
                        "",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            request = StageRequest(
                stage=BackendStage.ENRICHMENT,
                run_id="demo",
                repo_root=str(repo_root),
                run_dir="artifacts/runs/demo",
                output_dir="artifacts/runs/demo/01_enrichment",
                input_paths={"source": "a", "normalized_source": "b", "provenance": "c"},
                required_outputs=["handoff.md"],
            )
            agent = SubprocessFormalizationAgent(["python3", str(provider_script)])
            turn = agent.run_stage(request)
            self.assertEqual(turn.prompt, "stage prompt")
            self.assertEqual(turn.raw_response, "enrichment")

    def test_subprocess_agent_requires_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            provider_script = repo_root / "provider.py"
            provider_script.write_text(
                "import json, sys\njson.dump({'raw_response': 'missing prompt'}, sys.stdout)\n",
                encoding="utf-8",
            )
            request = StageRequest(
                stage=BackendStage.ENRICHMENT,
                run_id="demo",
                repo_root=str(repo_root),
                run_dir="artifacts/runs/demo",
                output_dir="artifacts/runs/demo/01_enrichment",
                input_paths={"source": "a", "normalized_source": "b", "provenance": "c"},
                required_outputs=["handoff.md"],
            )
            agent = SubprocessFormalizationAgent(["python3", str(provider_script)])
            with self.assertRaises(ProviderResponseError):
                agent.run_stage(request)

    def test_render_manifest_summary_points_at_handoff_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "demo"
            (run_root / "02_plan").mkdir(parents=True, exist_ok=True)
            (run_root / "02_plan" / "checkpoint.md").write_text("# Plan Approval\n", encoding="utf-8")
            (run_root / "02_plan" / "review.md").write_text("# Plan Approval\n", encoding="utf-8")
            manifest = RunManifest(
                run_id="demo",
                source=SourceRef(path="input.md", kind=SourceKind.MARKDOWN),
                agent_name="subprocess:provider.py",
                agent_config=AgentConfig(backend="command", command=["python3", "provider.py"]),
                template_dir="/tmp/template",
                created_at="2026-04-16T00:00:00Z",
                updated_at="2026-04-16T00:00:00Z",
                current_stage=RunStage.AWAITING_PLAN_APPROVAL,
                lake_path="/tmp/lake",
                attempt_count=0,
            )
            summary = render_manifest_summary(manifest, repo_root)
            self.assertIn("Checkpoint: artifacts/runs/demo/02_plan/checkpoint.md", summary)
            self.assertIn("Review file: artifacts/runs/demo/02_plan/review.md", summary)
            self.assertIn("--agent-command", summary)

    def test_load_manifest_uses_workflow_manifest_loader(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "demo"
            run_root.mkdir(parents=True, exist_ok=True)
            payload = {
                "run_id": "demo",
                "source": {"path": "input.md", "kind": "markdown"},
                "agent_name": "demo_zero_add_agent",
                "agent_config": {"backend": "demo"},
                "template_dir": str((repo_root / "lean_workspace_template").resolve()),
                "created_at": "2026-04-16T00:00:00Z",
                "updated_at": "2026-04-16T00:00:00Z",
                "current_stage": "awaiting_plan_approval",
                "attempt_count": 0,
            }
            (run_root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
            manifest = _load_manifest(repo_root, "demo")
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)

    def test_cli_status_json_round_trips_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "demo"
            run_root.mkdir(parents=True, exist_ok=True)
            payload = {
                "run_id": "demo",
                "source": {"path": "input.md", "kind": "markdown"},
                "agent_name": "demo_zero_add_agent",
                "agent_config": {"backend": "demo"},
                "template_dir": str((repo_root / "lean_workspace_template").resolve()),
                "created_at": "2026-04-16T00:00:00Z",
                "updated_at": "2026-04-16T00:00:00Z",
                "current_stage": "awaiting_enrichment_approval",
                "attempt_count": 0,
            }
            (run_root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            command = [
                sys.executable,
                "-m",
                "lean_formalization_engine",
                "--repo-root",
                str(repo_root),
                "status",
                "demo",
                "--json",
            ]
            result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["run_id"], "demo")
            self.assertEqual(output["current_stage"], "awaiting_enrichment_approval")

    def test_legacy_status_json_uses_legacy_stage_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "demo"
            run_root.mkdir(parents=True, exist_ok=True)
            payload = {
                "run_id": "demo",
                "source": {"path": "input.md", "kind": "markdown"},
                "agent_name": "demo_zero_add_agent",
                "agent_config": {"backend": "demo"},
                "template_dir": str((repo_root / "lean_workspace_template").resolve()),
                "created_at": "2026-04-16T00:00:00Z",
                "updated_at": "2026-04-16T00:00:00Z",
                "current_stage": "awaiting_plan_approval",
                "attempt_count": 0,
            }
            (run_root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")

            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            command = [
                sys.executable,
                "-m",
                "lean_formalization_engine",
                "--repo-root",
                str(repo_root),
                "status",
                "--run-id",
                "demo",
            ]
            result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["current_stage"], "awaiting_spec_review")
            self.assertNotIn("agent_config", output)
            self.assertNotIn("template_dir", output)

    def test_legacy_approve_enrichment_command_sets_terry_review_and_resume_advances(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            source_path = project_root / "examples" / "inputs" / "zero_add.md"
            env = {**os.environ, "PYTHONPATH": str(project_root / "src")}

            prove_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lean_formalization_engine",
                    "--repo-root",
                    str(repo_root),
                    "prove",
                    str(source_path),
                    "--run-id",
                    "legacy-approve",
                    "--agent-backend",
                    "demo",
                ],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(prove_result.returncode, 0, prove_result.stderr)

            approve_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lean_formalization_engine",
                    "--repo-root",
                    str(repo_root),
                    "approve-enrichment",
                    "--run-id",
                    "legacy-approve",
                    "--notes",
                    "Looks good.",
                ],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(approve_result.returncode, 0, approve_result.stderr)
            self.assertEqual(json.loads(approve_result.stdout)["current_stage"], "awaiting_spec_review")
            self.assertEqual(
                json.loads(
                    (
                        repo_root
                        / "artifacts"
                        / "runs"
                        / "legacy-approve"
                        / "01_enrichment"
                        / "decision.json"
                    ).read_text(encoding="utf-8")
                )["decision"],
                "approve",
            )

    def test_legacy_approve_spec_targets_merged_plan_checkpoint(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            source_path = project_root / "examples" / "inputs" / "zero_add.md"
            env = {**os.environ, "PYTHONPATH": str(project_root / "src")}

            prove_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lean_formalization_engine",
                    "--repo-root",
                    str(repo_root),
                    "--lake-path",
                    "/definitely/missing/lake",
                    "prove",
                    str(source_path),
                    "--run-id",
                    "compat-spec",
                    "--agent-backend",
                    "demo",
                ],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(prove_result.returncode, 0, prove_result.stderr)

            approve_enrichment = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lean_formalization_engine",
                    "--repo-root",
                    str(repo_root),
                    "approve-enrichment",
                    "--run-id",
                    "compat-spec",
                    "--notes",
                    "Looks good.",
                ],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(approve_enrichment.returncode, 0, approve_enrichment.stderr)

            to_plan = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lean_formalization_engine",
                    "--repo-root",
                    str(repo_root),
                    "--lake-path",
                    "/definitely/missing/lake",
                    "resume",
                    "compat-spec",
                ],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(to_plan.returncode, 0, to_plan.stderr)
            self.assertIn("Stage: awaiting_plan_approval", to_plan.stdout)

            approve_spec = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lean_formalization_engine",
                    "--repo-root",
                    str(repo_root),
                    "approve-spec",
                    "--run-id",
                    "compat-spec",
                    "--notes",
                    "Legacy spec approval should unlock the merged plan checkpoint.",
                ],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(approve_spec.returncode, 0, approve_spec.stderr)
            self.assertEqual(json.loads(approve_spec.stdout)["current_stage"], "awaiting_stall_review")
            self.assertEqual(
                json.loads(
                    (
                        repo_root
                        / "artifacts"
                        / "runs"
                        / "compat-spec"
                        / "02_plan"
                        / "decision.json"
                    ).read_text(encoding="utf-8")
                )["decision"],
                "approve",
            )

    def test_legacy_approve_enrichment_overrides_rejected_legacy_review(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = self._write_manifest(
                repo_root,
                "legacy-enrichment-reject",
                current_stage="awaiting_enrichment_review",
            )
            self._write_basic_legacy_inputs(run_root)
            (run_root / "03_enrichment").mkdir(parents=True, exist_ok=True)
            (run_root / "03_enrichment" / "handoff.md").write_text("# Legacy enrichment\n", encoding="utf-8")
            (run_root / "03_enrichment" / "review.md").write_text(
                "# Legacy Enrichment Review\n\ndecision: reject\n\nNotes:\nnot yet\n",
                encoding="utf-8",
            )

            env = {**os.environ, "PYTHONPATH": str(project_root / "src")}
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lean_formalization_engine",
                    "--repo-root",
                    str(repo_root),
                    "approve-enrichment",
                    "--run-id",
                    "legacy-enrichment-reject",
                    "--notes",
                    "Proceed.",
                ],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["current_stage"], "awaiting_spec_review")
            self.assertIn(
                "decision: approve",
                (run_root / "03_enrichment" / "review.md").read_text(encoding="utf-8"),
            )

    def test_legacy_approve_plan_overrides_rejected_legacy_review(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = self._write_manifest(
                repo_root,
                "legacy-plan-reject",
                current_stage="awaiting_plan_review",
            )
            self._write_basic_legacy_inputs(run_root)
            (run_root / "06_plan").mkdir(parents=True, exist_ok=True)
            (run_root / "06_plan" / "formalization_plan.json").write_text("{}", encoding="utf-8")
            (run_root / "06_plan" / "review.md").write_text(
                "# Legacy Plan Review\n\ndecision: reject\n\nNotes:\nnot yet\n",
                encoding="utf-8",
            )

            env = {**os.environ, "PYTHONPATH": str(project_root / "src")}
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lean_formalization_engine",
                    "--repo-root",
                    str(repo_root),
                    "--lake-path",
                    "/definitely/missing/lake",
                    "approve-plan",
                    "--run-id",
                    "legacy-plan-reject",
                    "--notes",
                    "Proceed.",
                ],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["current_stage"], "awaiting_stall_review")
            self.assertIn(
                "decision: approve",
                (run_root / "06_plan" / "review.md").read_text(encoding="utf-8"),
            )

    def test_legacy_approve_final_overrides_rejected_legacy_review(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = self._write_manifest(
                repo_root,
                "legacy-final-reject",
                current_stage="awaiting_final_review",
            )
            (run_root / "10_final").mkdir(parents=True, exist_ok=True)
            (run_root / "10_final" / "final_candidate.lean").write_text(
                "theorem x : True := by\n  trivial\n",
                encoding="utf-8",
            )
            (run_root / "10_final" / "review.md").write_text(
                "# Legacy Final Review\n\ndecision: reject\n\nNotes:\nnot yet\n",
                encoding="utf-8",
            )

            env = {**os.environ, "PYTHONPATH": str(project_root / "src")}
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lean_formalization_engine",
                    "--repo-root",
                    str(repo_root),
                    "approve-final",
                    "--run-id",
                    "legacy-final-reject",
                    "--notes",
                    "Proceed.",
                ],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["current_stage"], "completed")
            self.assertIn(
                "decision: approve",
                (run_root / "10_final" / "review.md").read_text(encoding="utf-8"),
            )

    def test_resume_final_approval_succeeds_without_codex_cli(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "final-only"
            (run_root / "04_final").mkdir(parents=True, exist_ok=True)
            (run_root / "04_final" / "final_candidate.lean").write_text(
                "theorem x : True := by\n  trivial\n",
                encoding="utf-8",
            )
            (run_root / "04_final" / "compile_result.json").write_text("{}", encoding="utf-8")
            (run_root / "04_final" / "provenance.json").write_text("{}", encoding="utf-8")
            (run_root / "04_final" / "review.md").write_text(
                "# Final Approval\n\ndecision: approve\n\nNotes:\n\n",
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "final-only",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "codex_cli:default",
                        "agent_config": {"backend": "codex", "command": None, "codex_model": None},
                        "template_dir": str(
                            (
                                project_root
                                / "src"
                                / "lean_formalization_engine"
                                / "workspace_template"
                            ).resolve()
                        ),
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_final_approval",
                        "attempt_count": 1,
                    }
                ),
                encoding="utf-8",
            )

            env = {**os.environ, "PYTHONPATH": str(project_root / "src"), "PATH": "/usr/bin:/bin"}
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lean_formalization_engine",
                    "--repo-root",
                    str(repo_root),
                    "resume",
                    "final-only",
                ],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Stage: completed", result.stdout)

    def test_cli_prove_without_codex_cli_fails_before_creating_run(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            source_path = repo_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")

            env = {**os.environ, "PYTHONPATH": str(project_root / "src"), "PATH": "/usr/bin:/bin"}
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "lean_formalization_engine",
                    "--repo-root",
                    str(repo_root),
                    "prove",
                    str(source_path),
                    "--run-id",
                    "missing-codex",
                ],
                cwd=project_root,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("codex", result.stderr)
            self.assertFalse((repo_root / "artifacts" / "runs" / "missing-codex").exists())

    def test_discover_workspace_template_rejects_ambiguous_depth_one_matches(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            package_template = Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            shutil.copytree(package_template, repo_root / "alpha" / "lean_workspace_template")
            shutil.copytree(package_template, repo_root / "beta" / "lean_workspace_template")

            with self.assertRaisesRegex(RuntimeError, "multiple eligible `lean_workspace_template`"):
                discover_workspace_template(repo_root)

    def test_resolve_workspace_template_cleans_partial_directory_after_failed_init(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            package_template = Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            fake_lake = repo_root / "lake"
            fake_lake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import pathlib",
                        "import sys",
                        "",
                        "target = pathlib.Path.cwd() / 'lean_workspace_template'",
                        "target.mkdir(parents=True, exist_ok=True)",
                        "(target / 'partial.txt').write_text('partial', encoding='utf-8')",
                        "print('network failed', file=sys.stderr)",
                        "raise SystemExit(1)",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake.chmod(0o755)

            with self.assertRaisesRegex(RuntimeError, "Failed to initialize `lean_workspace_template`"):
                resolve_workspace_template(
                    repo_root,
                    package_template,
                    lake_path=str(fake_lake),
                )

            self.assertFalse((repo_root / "lean_workspace_template").exists())

    def test_resolve_workspace_template_preserves_initialized_version_pins(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            package_template = Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            fake_lake = repo_root / "lake"
            fake_lake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import pathlib",
                        "import sys",
                        "",
                        "target = pathlib.Path.cwd() / 'lean_workspace_template'",
                        "target.mkdir(parents=True, exist_ok=True)",
                        "(target / 'lean-toolchain').write_text('leanprover/lean4:v4.31.0\\n', encoding='utf-8')",
                        "(target / 'lakefile.toml').write_text(",
                        "    '[package]\\nname = \"lean_workspace_template\"\\n[[require]]\\nname = \"mathlib\"\\nscope = \"leanprover-community\"\\nrev = \"v4.31.0\"\\n',",
                        "    encoding='utf-8',",
                        ")",
                        "print('ok')",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake.chmod(0o755)

            resolution = resolve_workspace_template(
                repo_root,
                package_template,
                lake_path=str(fake_lake),
            )

            self.assertEqual(resolution.origin, "initialized")
            target_dir = repo_root / "lean_workspace_template"
            self.assertEqual(
                (target_dir / "lean-toolchain").read_text(encoding="utf-8"),
                "leanprover/lean4:v4.31.0\n",
            )
            lakefile_text = (target_dir / "lakefile.toml").read_text(encoding="utf-8")
            self.assertIn('name = "FormalizationEngineWorkspace"', lakefile_text)
            self.assertIn('rev = "v4.31.0"', lakefile_text)
