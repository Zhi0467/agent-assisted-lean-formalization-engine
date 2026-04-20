from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lean_formalization_engine.cli import (
    _load_manifest,
    _resolve_agent_command,
    _resolve_lake_path,
    _resume_agent_config,
    build_agent,
    build_agent_with_options,
    build_agent_config,
    render_manifest_summary,
)
from lean_formalization_engine.cli_exec_agent import (
    CliExecFormalizationAgent,
    CodexCliFormalizationAgent,
)
from lean_formalization_engine.models import AgentConfig, BackendStage, RunManifest, RunStage, SourceKind, SourceRef, StageRequest
from lean_formalization_engine.prompt_loader import load_prompt_template
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
        agent_name: str = "codex_cli:default",
        agent_config: dict[str, object] | None = None,
    ) -> Path:
        run_root = repo_root / "artifacts" / "runs" / run_id
        run_root.mkdir(parents=True, exist_ok=True)
        (run_root / "manifest.json").write_text(
            json.dumps(
                {
                    "run_id": run_id,
                    "source": {"path": "input.md", "kind": "markdown"},
                    "agent_name": agent_name,
                    "agent_config": {"backend": "codex"} if agent_config is None else agent_config,
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
        args = Namespace(agent_backend=None, agent_command=None, model=None, codex_model=None)
        config = build_agent_config(args, project_root)
        self.assertEqual(config.backend, "codex")
        self.assertIsNone(config.model)

    def test_build_agent_config_defaults_to_codex_when_available(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(agent_backend=None, agent_command=None, model=None, codex_model=None)
        with patch("lean_formalization_engine.cli.shutil.which", return_value="/usr/bin/codex"):
            config = build_agent_config(args, project_root)
        self.assertEqual(config.backend, "codex")
        self.assertIsNone(config.model)

    def test_build_agent_config_accepts_claude_backend(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(
            agent_backend="claude",
            agent_command=None,
            model="sonnet-test",
            codex_model=None,
        )
        config = build_agent_config(args, project_root)
        self.assertEqual(config.backend, "claude")
        self.assertEqual(config.model, "sonnet-test")

    def test_build_agent_config_accepts_legacy_codex_model_flag(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(agent_backend="codex", agent_command=None, model=None, codex_model="o4")
        config = build_agent_config(args, project_root)
        self.assertEqual(config.backend, "codex")
        self.assertEqual(config.model, "o4")

    def test_build_agent_config_resolves_repo_relative_command(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(
            agent_backend="command",
            agent_command="python3 examples/providers/scripted_repair_provider.py",
            model=None,
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

    def test_build_agent_config_rejects_model_for_command_backend(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(
            agent_backend="command",
            agent_command="python3 examples/providers/scripted_repair_provider.py",
            model="gpt-test",
            codex_model=None,
        )
        with self.assertRaisesRegex(ValueError, "--model"):
            build_agent_config(args, project_root)

    def test_build_agent_config_rejects_command_flag_for_codex_backend(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(
            agent_backend="codex",
            agent_command="python3 examples/providers/scripted_repair_provider.py",
            model="gpt-test",
            codex_model=None,
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

    def test_build_agent_rejects_removed_demo_backend(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with self.assertRaisesRegex(ValueError, "Legacy `demo` backend runs can no longer continue"):
            build_agent_with_options(
                AgentConfig(backend="demo"),
                project_root,
                heartbeat_interval_seconds=60.0,
            )

    def test_missing_codex_agent_raises_when_a_turn_is_requested(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        config = AgentConfig(backend="codex")
        with patch("lean_formalization_engine.cli.shutil.which", return_value=None):
            agent = build_agent(config, project_root)
        with self.assertRaisesRegex(ValueError, "codex"):
            agent.run_stage(
                StageRequest(
                    stage=BackendStage.ENRICHMENT,
                    run_id="sample",
                    repo_root=str(project_root),
                    run_dir="artifacts/runs/sample",
                    output_dir="artifacts/runs/sample/01_enrichment",
                    input_paths={"source": "a", "provenance": "c"},
                    required_outputs=["handoff.md"],
                )
            )

    def test_resume_agent_config_prefers_explicit_command_override(self) -> None:
        manifest = RunManifest(
            run_id="sample",
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
            model=None,
            legacy_model=None,
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
            run_id="sample",
            source=SourceRef(path="input.md", kind=SourceKind.MARKDOWN),
            agent_name="codex_cli:default",
            agent_config=AgentConfig(backend="codex"),
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
            model=None,
            legacy_model=None,
            codex_model=None,
            legacy_codex_model=None,
        )
        repo_root = Path(__file__).resolve().parents[1]
        with self.assertRaisesRegex(ValueError, "keep the backend recorded in the manifest"):
            _resume_agent_config(manifest, args, repo_root)

    def test_resume_agent_config_rejects_removed_demo_backend(self) -> None:
        manifest = RunManifest(
            run_id="sample",
            source=SourceRef(path="input.md", kind=SourceKind.MARKDOWN),
            agent_name="demo",
            agent_config=AgentConfig(backend="demo"),
            template_dir="/tmp/template",
            created_at="2026-04-16T00:00:00Z",
            updated_at="2026-04-16T00:00:00Z",
            current_stage=RunStage.AWAITING_ENRICHMENT_APPROVAL,
        )
        args = Namespace(
            agent_command=None,
            legacy_agent_command=None,
            agent_backend=None,
            legacy_agent_backend=None,
            model=None,
            legacy_model=None,
            codex_model=None,
            legacy_codex_model=None,
        )
        repo_root = Path(__file__).resolve().parents[1]
        with self.assertRaisesRegex(ValueError, "Legacy `demo` backend runs can no longer continue"):
            _resume_agent_config(manifest, args, repo_root)

    def test_codex_agent_uses_workspace_write_and_file_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "sample"
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "01_enrichment").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("source", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text("normalized", encoding="utf-8")
            (run_root / "01_enrichment" / "handoff.md").write_text("# Enrichment\n", encoding="utf-8")
            (run_root / "01_enrichment" / "review.md").write_text("# Review\n", encoding="utf-8")

            request = StageRequest(
                stage=BackendStage.PLAN,
                run_id="sample",
                repo_root=str(repo_root),
                run_dir="artifacts/runs/sample",
                output_dir="artifacts/runs/sample/02_plan",
                input_paths={
                    "source": "artifacts/runs/sample/00_input/source.txt",
                    "enrichment_handoff": "artifacts/runs/sample/01_enrichment/handoff.md",
                    "enrichment_review": "artifacts/runs/sample/01_enrichment/review.md",
                },
                required_outputs=["handoff.md"],
                review_notes_path="artifacts/runs/sample/01_enrichment/review.md",
            )

            def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
                sandbox_root = Path(command[command.index("-C") + 1])
                (sandbox_root / request.output_dir).mkdir(parents=True, exist_ok=True)
                (sandbox_root / request.output_dir / "handoff.md").write_text("# Plan Handoff\n", encoding="utf-8")
                return subprocess.CompletedProcess(
                    args=command,
                    returncode=0,
                    stdout="wrote 02_plan/handoff.md\n",
                    stderr="",
                )

            with patch("lean_formalization_engine.backend_runtime.subprocess.run", side_effect=fake_run) as run_mock:
                agent = CodexCliFormalizationAgent(repo_root=repo_root, model="gpt-test", executable="codex")
                turn = agent.run_stage(request)

            command = run_mock.call_args.args[0]
            prompt = run_mock.call_args.kwargs["input"]
            self.assertIn("--dangerously-bypass-approvals-and-sandbox", command)
            self.assertEqual(command[:6], ["codex", "exec", "--ephemeral", "--skip-git-repo-check", "--dangerously-bypass-approvals-and-sandbox", "-C"])
            self.assertNotEqual(command[6], str(repo_root))
            self.assertIn("Required outputs:", prompt)
            self.assertIn("artifacts/runs/sample/02_plan/handoff.md", prompt)
            self.assertIn("enrichment_handoff", prompt)
            self.assertEqual(turn.raw_response, "wrote 02_plan/handoff.md")
            self.assertEqual((run_root / "02_plan" / "handoff.md").read_text(encoding="utf-8"), "# Plan Handoff\n")

    def test_codex_proof_prompt_carries_review_and_previous_attempt_pointers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            agent = CodexCliFormalizationAgent(repo_root=repo_root)
            request = StageRequest(
                stage=BackendStage.PROOF,
                run_id="sample",
                repo_root=str(repo_root),
                run_dir="artifacts/runs/sample",
                output_dir="artifacts/runs/sample/03_proof/attempts/attempt_0002",
                input_paths={
                    "source": "artifacts/runs/sample/00_input/source.txt",
                    "enrichment_handoff": "artifacts/runs/sample/01_enrichment/handoff.md",
                    "natural_language_statement": "artifacts/runs/sample/01_enrichment/natural_language_statement.md",
                    "natural_language_proof": "artifacts/runs/sample/01_enrichment/natural_language_proof.md",
                    "proof_status": "artifacts/runs/sample/01_enrichment/proof_status.json",
                    "plan_handoff": "artifacts/runs/sample/02_plan/handoff.md",
                    "previous_compile_result": "artifacts/runs/sample/03_proof/attempts/attempt_0001/compile_result.json",
                    "previous_candidate": "artifacts/runs/sample/03_proof/attempts/attempt_0001/candidate.lean",
                    "previous_walkthrough": "artifacts/runs/sample/03_proof/attempts/attempt_0001/review/walkthrough.md",
                    "previous_readable_candidate": "artifacts/runs/sample/03_proof/attempts/attempt_0001/review/readable_candidate.lean",
                    "previous_error_report": "artifacts/runs/sample/03_proof/attempts/attempt_0001/review/error.md",
                },
                required_outputs=["candidate.lean"],
                review_notes_path="artifacts/runs/sample/03_proof/review.md",
                latest_compile_result_path="artifacts/runs/sample/03_proof/attempts/attempt_0001/compile_result.json",
                previous_attempt_dir="artifacts/runs/sample/03_proof/attempts/attempt_0001",
                attempt=2,
                max_attempts=3,
            )

            prompt = agent._build_prompt(request)
            self.assertIn("natural_language_statement", prompt)
            self.assertIn("natural_language_proof", prompt)
            self.assertIn("previous_walkthrough", prompt)
            self.assertIn("previous_readable_candidate", prompt)
            self.assertIn("previous_error_report", prompt)
            self.assertIn("Read any previous walkthrough, readable-candidate, or error-report pointers before repairing.", prompt)

    def test_prompt_templates_are_centralized(self) -> None:
        for template_name in (
            "stage_common.md",
            "stage_enrichment.md",
            "stage_plan.md",
            "stage_proof.md",
            "stage_review.md",
        ):
            self.assertTrue(load_prompt_template(template_name).strip())

    def test_stage_templates_name_core_input_pointers(self) -> None:
        expected_snippets = {
            "stage_enrichment.md": ("`source`", "`provenance`"),
            "stage_plan.md": (
                "`enrichment_handoff`",
                "`natural_language_statement`",
                "`natural_language_proof`",
                "`proof_status`",
                "`relevant_lean_objects`",
            ),
            "stage_proof.md": (
                "`plan_handoff`",
                "`natural_language_statement`",
                "`natural_language_proof`",
                "`relevant_lean_objects`",
            ),
            "stage_review.md": (
                "`plan_handoff`",
                "`natural_language_statement`",
                "`natural_language_proof`",
                "`relevant_lean_objects`",
                "`attempt_candidate`",
                "`attempt_compile_result`",
            ),
        }
        for template_name, snippets in expected_snippets.items():
            template = load_prompt_template(template_name)
            for snippet in snippets:
                self.assertIn(snippet, template)

    def test_runtime_modules_do_not_embed_literal_prompt_strings(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        for relative_path in (
            "src/lean_formalization_engine/cli_exec_agent.py",
        ):
            module = ast.parse((project_root / relative_path).read_text(encoding="utf-8"))
            for node in ast.walk(module):
                if not isinstance(node, ast.Call):
                    continue
                if not isinstance(node.func, ast.Name) or node.func.id != "AgentTurn":
                    continue
                for keyword in node.keywords:
                    if keyword.arg != "prompt":
                        continue
                    self.assertFalse(
                        isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str),
                        f"{relative_path} embeds a literal prompt string instead of loading a template.",
                    )

    def test_codex_agent_only_copies_output_dir_back_to_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            (repo_root / "README.md").write_text("original", encoding="utf-8")
            run_root = repo_root / "artifacts" / "runs" / "sample"
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("source", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text("normalized", encoding="utf-8")
            (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")

            request = StageRequest(
                stage=BackendStage.ENRICHMENT,
                run_id="sample",
                repo_root=str(repo_root),
                run_dir="artifacts/runs/sample",
                output_dir="artifacts/runs/sample/01_enrichment",
                input_paths={
                    "source": "artifacts/runs/sample/00_input/source.txt",
                    "provenance": "artifacts/runs/sample/00_input/provenance.json",
                },
                required_outputs=["handoff.md"],
            )

            def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
                sandbox_root = Path(command[command.index("-C") + 1])
                (sandbox_root / "README.md").write_text("mutated", encoding="utf-8")
                output_dir = sandbox_root / request.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "handoff.md").write_text("# Enrichment\n", encoding="utf-8")
                return subprocess.CompletedProcess(args=command, returncode=0, stdout="ok", stderr="")

            with patch("lean_formalization_engine.backend_runtime.subprocess.run", side_effect=fake_run):
                agent = CodexCliFormalizationAgent(repo_root=repo_root, executable="codex")
                agent.run_stage(request)

            self.assertEqual((repo_root / "README.md").read_text(encoding="utf-8"), "original")
            self.assertEqual((run_root / "01_enrichment" / "handoff.md").read_text(encoding="utf-8"), "# Enrichment\n")

    def test_codex_agent_sandbox_excludes_project_agents_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            (repo_root / "AGENTS.md").write_text("project instructions", encoding="utf-8")
            run_root = repo_root / "artifacts" / "runs" / "sample"
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("source", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text("normalized", encoding="utf-8")
            (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")

            request = StageRequest(
                stage=BackendStage.ENRICHMENT,
                run_id="sample",
                repo_root=str(repo_root),
                run_dir="artifacts/runs/sample",
                output_dir="artifacts/runs/sample/01_enrichment",
                input_paths={
                    "source": "artifacts/runs/sample/00_input/source.txt",
                    "provenance": "artifacts/runs/sample/00_input/provenance.json",
                },
                required_outputs=["handoff.md"],
            )

            def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
                sandbox_root = Path(command[command.index("-C") + 1]).resolve()
                self.assertNotIn(repo_root.resolve(), sandbox_root.parents)
                self.assertFalse((sandbox_root / "AGENTS.md").exists())
                output_dir = sandbox_root / request.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "handoff.md").write_text("# Enrichment\n", encoding="utf-8")
                return subprocess.CompletedProcess(args=command, returncode=0, stdout="ok", stderr="")

            with patch("lean_formalization_engine.backend_runtime.subprocess.run", side_effect=fake_run):
                agent = CodexCliFormalizationAgent(repo_root=repo_root, executable="codex")
                agent.run_stage(request)

    def test_codex_agent_missing_cli_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "sample" / "00_input"
            run_root.mkdir(parents=True, exist_ok=True)
            (run_root / "source.txt").write_text("source", encoding="utf-8")
            (run_root / "normalized.md").write_text("normalized", encoding="utf-8")
            (run_root / "provenance.json").write_text("{}", encoding="utf-8")

            request = StageRequest(
                stage=BackendStage.ENRICHMENT,
                run_id="sample",
                repo_root=str(repo_root),
                run_dir="artifacts/runs/sample",
                output_dir="artifacts/runs/sample/01_enrichment",
                input_paths={
                    "source": "artifacts/runs/sample/00_input/source.txt",
                    "provenance": "artifacts/runs/sample/00_input/provenance.json",
                },
                required_outputs=["handoff.md"],
            )
            with patch(
                "lean_formalization_engine.backend_runtime.subprocess.run",
                side_effect=FileNotFoundError("codex"),
            ):
                agent = CodexCliFormalizationAgent(repo_root=repo_root)
                with self.assertRaisesRegex(RuntimeError, "codex"):
                    agent.run_stage(request)

    def test_codex_agent_emits_heartbeat_for_long_running_exec(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "sample"
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("source", encoding="utf-8")
            (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")

            request = StageRequest(
                stage=BackendStage.ENRICHMENT,
                run_id="sample",
                repo_root=str(repo_root),
                run_dir="artifacts/runs/sample",
                output_dir="artifacts/runs/sample/01_enrichment",
                input_paths={
                    "source": "artifacts/runs/sample/00_input/source.txt",
                    "provenance": "artifacts/runs/sample/00_input/provenance.json",
                },
                required_outputs=["handoff.md"],
            )
            events: list[tuple[str, str, dict[str, object] | None]] = []

            def slow_run(command, **kwargs):  # type: ignore[no-untyped-def]
                time.sleep(0.03)
                sandbox_root = Path(command[command.index("-C") + 1])
                output_dir = sandbox_root / request.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "handoff.md").write_text("# Enrichment\n", encoding="utf-8")
                return subprocess.CompletedProcess(args=command, returncode=0, stdout="ok", stderr="")

            with patch("lean_formalization_engine.backend_runtime.subprocess.run", side_effect=slow_run):
                agent = CodexCliFormalizationAgent(
                    repo_root=repo_root,
                    executable="codex",
                    heartbeat_interval_seconds=0.01,
                )
                agent.run_stage(
                    request,
                    progress_callback=lambda event_type, summary, details=None: events.append(
                        (event_type, summary, details)
                    ),
                )

            event_types = [event_type for event_type, _, _ in events]
            self.assertIn("backend_process_started", event_types)
            self.assertIn("backend_process_heartbeat", event_types)
            self.assertIn("backend_process_completed", event_types)

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
                run_id="sample",
                repo_root=str(repo_root),
                run_dir="artifacts/runs/sample",
                output_dir="artifacts/runs/sample/01_enrichment",
                input_paths={"source": "a", "provenance": "c"},
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
                run_id="sample",
                repo_root=str(repo_root),
                run_dir="artifacts/runs/sample",
                output_dir="artifacts/runs/sample/01_enrichment",
                input_paths={"source": "a", "provenance": "c"},
                required_outputs=["handoff.md"],
            )
            agent = SubprocessFormalizationAgent(["python3", str(provider_script)])
            with self.assertRaises(ProviderResponseError):
                agent.run_stage(request)

    def test_render_manifest_summary_points_at_handoff_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "sample"
            (run_root / "02_plan").mkdir(parents=True, exist_ok=True)
            (run_root / "02_plan" / "checkpoint.md").write_text("# Plan Approval\n", encoding="utf-8")
            (run_root / "02_plan" / "review.md").write_text("# Plan Approval\n", encoding="utf-8")
            (run_root / "logs").mkdir(parents=True, exist_ok=True)
            (run_root / "logs" / "workflow.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {
                                "timestamp": "2026-04-19T00:00:00Z",
                                "event_type": "backend_stage_completed",
                                "summary": "Plan turn completed.",
                                "stage": "plan",
                                "details": {},
                            }
                        ),
                        json.dumps(
                            {
                                "timestamp": "2026-04-19T00:01:00Z",
                                "event_type": "backend_stage_completed",
                                "summary": "Plan rerun completed.",
                                "stage": "plan",
                                "details": {},
                            }
                        ),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            manifest = RunManifest(
                run_id="sample",
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
            self.assertIn("Plan turns: 2", summary)
            self.assertIn("Checkpoint: artifacts/runs/sample/02_plan/checkpoint.md", summary)
            self.assertIn("Review file: artifacts/runs/sample/02_plan/review.md", summary)
            self.assertIn(
                "Decision guide: decision: reject -> rerun the plan stage with your notes",
                summary,
            )
            self.assertIn("Approve with: terry resume sample --workdir", summary)
            self.assertIn("--approve", summary)
            self.assertIn("only edit the review file when you need notes or a rejection", summary)
            self.assertIn("--agent-command", summary)

    def test_render_manifest_summary_uses_proof_attempt_label_during_proof_stages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "sample"
            (run_root / "03_proof").mkdir(parents=True, exist_ok=True)
            (run_root / "03_proof" / "checkpoint.md").write_text("# Proof Blocked\n", encoding="utf-8")
            (run_root / "03_proof" / "review.md").write_text("# Proof Blocked\n", encoding="utf-8")
            manifest = RunManifest(
                run_id="sample",
                source=SourceRef(path="input.md", kind=SourceKind.MARKDOWN),
                agent_name="subprocess:provider.py",
                agent_config=AgentConfig(backend="command", command=["python3", "provider.py"]),
                template_dir="/tmp/template",
                created_at="2026-04-16T00:00:00Z",
                updated_at="2026-04-16T00:00:00Z",
                current_stage=RunStage.PROOF_BLOCKED,
                lake_path="/tmp/lake",
                attempt_count=3,
            )

            summary = render_manifest_summary(manifest, repo_root)

            self.assertIn("Proof attempts: 3", summary)

    def test_load_manifest_uses_workflow_manifest_loader(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "sample"
            run_root.mkdir(parents=True, exist_ok=True)
            payload = {
                "run_id": "sample",
                "source": {"path": "input.md", "kind": "markdown"},
                "agent_name": "codex_cli:default",
                "agent_config": {"backend": "codex"},
                "template_dir": str((repo_root / "lean_workspace_template").resolve()),
                "created_at": "2026-04-16T00:00:00Z",
                "updated_at": "2026-04-16T00:00:00Z",
                "current_stage": "awaiting_plan_approval",
                "attempt_count": 0,
            }
            (run_root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
            manifest = _load_manifest(repo_root, "sample")
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)

    def test_load_manifest_preserves_legacy_demo_backend_name(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "sample"
            run_root.mkdir(parents=True, exist_ok=True)
            payload = {
                "run_id": "sample",
                "source": {"path": "input.md", "kind": "markdown"},
                "agent_name": "demo",
                "template_dir": str((repo_root / "lean_workspace_template").resolve()),
                "created_at": "2026-04-16T00:00:00Z",
                "updated_at": "2026-04-16T00:00:00Z",
                "current_stage": "awaiting_plan_approval",
                "attempt_count": 0,
            }
            (run_root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
            manifest = _load_manifest(repo_root, "sample")
            self.assertEqual(manifest.agent_config.backend, "demo")

    def test_cli_status_json_round_trips_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "sample"
            run_root.mkdir(parents=True, exist_ok=True)
            payload = {
                "run_id": "sample",
                "source": {"path": "input.md", "kind": "markdown"},
                "agent_name": "codex_cli:default",
                "agent_config": {"backend": "codex"},
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
                "sample",
                "--json",
            ]
            result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["run_id"], "sample")
            self.assertEqual(output["current_stage"], "awaiting_enrichment_approval")

    def test_cli_status_accepts_workdir_after_subcommand(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "sample"
            run_root.mkdir(parents=True, exist_ok=True)
            payload = {
                "run_id": "sample",
                "source": {"path": "input.md", "kind": "markdown"},
                "agent_name": "codex_cli:default",
                "agent_config": {"backend": "codex"},
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
                "status",
                "sample",
                "--workdir",
                str(repo_root),
            ]
            result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn(f"Working directory: {repo_root.resolve()}", result.stdout)
            self.assertIn("Resume with: terry resume sample --workdir", result.stdout)

    def test_legacy_status_json_uses_legacy_stage_names(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "sample"
            run_root.mkdir(parents=True, exist_ok=True)
            payload = {
                "run_id": "sample",
                "source": {"path": "input.md", "kind": "markdown"},
                "agent_name": "codex_cli:default",
                "agent_config": {"backend": "codex"},
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
                "sample",
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
            provider_script = project_root / "examples" / "providers" / "scripted_repair_provider.py"
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
                    "command",
                    "--agent-command",
                    f"{sys.executable} {provider_script}",
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
            provider_script = project_root / "examples" / "providers" / "scripted_repair_provider.py"
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
                    "command",
                    "--agent-command",
                    f"{sys.executable} {provider_script}",
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
            provider_script = project_root / "examples" / "providers" / "scripted_repair_provider.py"
            run_root = self._write_manifest(
                repo_root,
                "legacy-enrichment-reject",
                current_stage="awaiting_enrichment_review",
                agent_name="subprocess:scripted_repair_provider.py",
                agent_config={
                    "backend": "command",
                    "command": ["python3", str(provider_script)],
                    "codex_model": None,
                },
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
            provider_script = project_root / "examples" / "providers" / "scripted_repair_provider.py"
            run_root = self._write_manifest(
                repo_root,
                "legacy-plan-reject",
                current_stage="awaiting_plan_review",
                agent_name="subprocess:scripted_repair_provider.py",
                agent_config={
                    "backend": "command",
                    "command": ["python3", str(provider_script)],
                    "codex_model": None,
                },
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
