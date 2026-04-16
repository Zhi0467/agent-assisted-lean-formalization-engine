from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from lean_formalization_engine.cli import (
    _load_manifest,
    _resolve_agent_command,
    build_agent,
    build_agent_config,
    render_manifest_summary,
)
from lean_formalization_engine.codex_agent import CodexCliFormalizationAgent
from lean_formalization_engine.models import AgentConfig, RunManifest, RunStage, SourceKind, SourceRef
from lean_formalization_engine.subprocess_agent import SubprocessFormalizationAgent
from lean_formalization_engine.template_manager import resolve_workspace_template


class CodexAgentTest(unittest.TestCase):
    def test_build_agent_config_defaults_to_codex_backend(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(
            agent_backend=None,
            agent_command=None,
            codex_model=None,
        )

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

    def test_resolve_agent_command_preserves_python_module_invocation(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        resolved = _resolve_agent_command(["python3", "-m", "examples"], project_root)
        self.assertEqual(resolved, ["python3", "-m", "examples"])

    def test_build_agent_uses_stored_command_backend(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        config = AgentConfig(
            backend="command",
            command=["python3", str(project_root / "examples" / "providers" / "scripted_repair_provider.py")],
        )

        agent = build_agent(config, project_root)

        self.assertIsInstance(agent, SubprocessFormalizationAgent)
        self.assertEqual(agent.command, config.command)

    def test_codex_agent_invokes_read_only_exec_and_parses_output(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        agent = CodexCliFormalizationAgent(
            repo_root=project_root,
            model="gpt-5.4-mini",
        )
        captured: dict[str, object] = {}

        def fake_run(command, input, capture_output, text, check):  # type: ignore[no-untyped-def]
            captured["command"] = command
            captured["input"] = input
            output_path = Path(command[command.index("-o") + 1])
            output_path.write_text(
                json.dumps(
                    {
                        "title": "Zero-add on natural numbers",
                        "informal_statement": "0 + n = n",
                        "definitions": ["Nat"],
                        "lemmas": ["Nat.zero_add"],
                        "propositions": [],
                        "dependencies": ["Nat.zero_add"],
                        "notes": [],
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "lean_formalization_engine.codex_agent.subprocess.run",
            side_effect=fake_run,
        ):
            extraction, turn = agent.draft_theorem_extraction(
                SourceRef(path="examples/inputs/zero_add.md", kind=SourceKind.MARKDOWN),
                "For every natural number n, 0 + n = n.\n",
                "For every natural number n, 0 + n = n.\n",
            )

        command = captured["command"]
        self.assertIsInstance(command, list)
        assert isinstance(command, list)
        self.assertEqual(command[0], "codex")
        self.assertIn("-s", command)
        self.assertIn("read-only", command)
        self.assertIn("--output-schema", command)
        self.assertIn("-o", command)
        self.assertIn("For every natural number", str(captured["input"]))
        self.assertEqual(extraction.title, "Zero-add on natural numbers")
        self.assertEqual(turn.request_payload["stage"], "draft_theorem_extraction")
        self.assertEqual(turn.request_payload["model"], "gpt-5.4-mini")

    def test_codex_agent_surfaces_missing_cli(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        agent = CodexCliFormalizationAgent(repo_root=project_root)

        with patch(
            "lean_formalization_engine.codex_agent.subprocess.run",
            side_effect=FileNotFoundError("codex"),
        ):
            with self.assertRaisesRegex(RuntimeError, "codex"):
                agent.draft_theorem_extraction(
                    SourceRef(path="x.md", kind=SourceKind.MARKDOWN),
                    "Theorem text.\n",
                    "Theorem text.\n",
                )

    def test_template_resolution_initializes_when_missing(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        package_template_dir = project_root / "lean_workspace_template"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            fake_lake = temp_root / "lake"
            fake_lake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import pathlib",
                        "import sys",
                        "",
                        "def main() -> int:",
                        "    if sys.argv[1:4] != ['new', 'lean_workspace_template', 'math']:",
                        "        print(sys.argv[1:], file=sys.stderr)",
                        "        return 1",
                        "    target = pathlib.Path.cwd() / 'lean_workspace_template'",
                        "    target.mkdir(parents=True, exist_ok=True)",
                        "    (target / 'lakefile.toml').write_text('name = \"Scratch\"\\n[[require]]\\nname = \"mathlib\"\\n', encoding='utf-8')",
                        "    return 0",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake.chmod(0o755)

            resolution = resolve_workspace_template(
                temp_root,
                package_template_dir,
                lake_path=str(fake_lake),
            )

            self.assertEqual(resolution.origin, "initialized")
            self.assertTrue((resolution.template_dir / "FormalizationEngineWorkspace" / "Basic.lean").exists())
            self.assertEqual(resolution.command, [str(fake_lake), "new", "lean_workspace_template", "math"])

    def test_render_manifest_summary_mentions_checkpoint(self) -> None:
        repo_root = Path("/tmp/terry")
        manifest = RunManifest(
            run_id="zero-add",
            source=SourceRef(path="examples/inputs/zero_add.md", kind=SourceKind.MARKDOWN),
            agent_name="demo_zero_add_agent",
            agent_config=AgentConfig(backend="demo"),
            template_dir="/tmp/terry/lean_workspace_template",
            created_at="2026-04-16T00:00:00Z",
            updated_at="2026-04-16T00:01:00Z",
            current_stage=RunStage.AWAITING_PLAN_APPROVAL,
        )

        summary = render_manifest_summary(manifest, repo_root)

        self.assertIn("Stage: awaiting_plan_approval", summary)
        self.assertIn("Review file: artifacts/runs/zero-add/02_plan/review.md", summary)
        self.assertIn("Resume with: terry resume zero-add", summary)

    def test_load_manifest_falls_back_for_legacy_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "legacy"
            run_root.mkdir(parents=True)
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "demo_zero_add_agent",
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "created",
                    }
                ),
                encoding="utf-8",
            )

            manifest = _load_manifest(repo_root, "legacy")

            self.assertEqual(manifest.run_id, "legacy")
            self.assertEqual(manifest.agent_config.backend, "demo")
