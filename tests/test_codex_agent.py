from __future__ import annotations

import json
import subprocess
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from lean_formalization_engine.cli import build_agent
from lean_formalization_engine.codex_agent import CodexCliFormalizationAgent
from lean_formalization_engine.models import SourceKind, SourceRef


class CodexAgentTest(unittest.TestCase):
    def test_build_agent_selects_codex_backend(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        args = Namespace(
            agent_backend="codex",
            codex_model="gpt-5.4-mini",
            agent_command=None,
        )

        agent = build_agent(args, project_root)

        self.assertIsInstance(agent, CodexCliFormalizationAgent)
        self.assertEqual(agent.model, "gpt-5.4-mini")

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
                        "assumptions": ["n : Nat"],
                        "conclusion": "0 + n = n",
                        "symbols": ["0", "+", "Nat"],
                        "ambiguities": [],
                        "paraphrase": "Adding zero on the left returns the same natural number.",
                    }
                ),
                encoding="utf-8",
            )
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch(
            "lean_formalization_engine.codex_agent.subprocess.run",
            side_effect=fake_run,
        ):
            theorem_spec, turn = agent.draft_theorem_spec(
                SourceRef(path="examples/inputs/zero_add.md", kind=SourceKind.MARKDOWN),
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
        self.assertEqual(theorem_spec.title, "Zero-add on natural numbers")
        self.assertEqual(turn.request_payload["stage"], "draft_theorem_spec")
        self.assertEqual(turn.request_payload["model"], "gpt-5.4-mini")
        self.assertIn("Adding zero on the left", turn.raw_response)

    def test_codex_agent_surfaces_exec_failures(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        agent = CodexCliFormalizationAgent(repo_root=project_root)

        with patch(
            "lean_formalization_engine.codex_agent.subprocess.run",
            return_value=subprocess.CompletedProcess(
                ["codex"],
                1,
                "stdout details",
                "stderr details",
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "draft_theorem_spec"):
                agent.draft_theorem_spec(
                    SourceRef(path="x.md", kind=SourceKind.MARKDOWN),
                    "Theorem text.\n",
                )
