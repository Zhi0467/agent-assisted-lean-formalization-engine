from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

from lean_formalization_engine.cli import (
    _load_manifest,
    _resolve_agent_command,
    _resume_agent_config,
    build_agent,
    build_agent_config,
    build_parser,
    render_manifest_summary,
)
from lean_formalization_engine.codex_agent import CodexCliFormalizationAgent
from lean_formalization_engine.lean_runner import LeanRunner
from lean_formalization_engine.models import (
    AgentConfig,
    ContextPack,
    EnrichmentReport,
    RunManifest,
    RunStage,
    SourceKind,
    SourceRef,
    TheoremExtraction,
)
from lean_formalization_engine.subprocess_agent import (
    SubprocessFormalizationAgent,
    _legacy_theorem_spec_payload,
)
from lean_formalization_engine.template_manager import resolve_workspace_template
from lean_formalization_engine.workflow import FormalizationWorkflow


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

    def test_subprocess_plan_payload_keeps_legacy_theorem_spec_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            provider_script = repo_root / "old_provider.py"
            provider_script.write_text(
                "\n".join(
                    [
                        "from __future__ import annotations",
                        "import json",
                        "import sys",
                        "",
                        "def main() -> int:",
                        "    request = json.load(sys.stdin)",
                        "    if request['stage'] == 'draft_theorem_spec':",
                        "        raise RuntimeError('Unsupported stage: draft_theorem_spec')",
                        "    theorem_spec = request['theorem_spec']",
                        "    parsed_output = {",
                        "        'title': theorem_spec['title'],",
                        "        'informal_statement': theorem_spec['informal_statement'],",
                        "        'assumptions': theorem_spec['assumptions'],",
                        "        'conclusion': theorem_spec['conclusion'],",
                        "        'symbols': theorem_spec['symbols'],",
                        "        'ambiguities': theorem_spec['ambiguities'],",
                        "        'paraphrase': theorem_spec['paraphrase'],",
                        "        'theorem_name': 'legacy_zero_add',",
                        "        'imports': ['FormalizationEngineWorkspace.Basic'],",
                        "        'prerequisites_to_formalize': request['enrichment']['required_plan_additions'],",
                        "        'helper_definitions': [],",
                        "        'target_statement': 'theorem legacy_zero_add (n : Nat) : 0 + n = n',",
                        "        'proof_sketch': ['Use Nat.zero_add.'],",
                        "        'human_summary': 'Legacy provider compatibility.',",
                        "    }",
                        "    json.dump({'prompt': 'legacy', 'raw_response': 'legacy', 'parsed_output': parsed_output}, sys.stdout)",
                        "    return 0",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            provider_script.chmod(0o755)

            agent = SubprocessFormalizationAgent(["python3", str(provider_script)])
            for statement in [
                "For every natural number n, 0 + n = n.",
                "For every natural number n: 0 + n = n.",
                "For all n : Nat, 0 + n = n.",
                "Given n : Nat, 0 + n = n.",
                "For every natural number `n`, adding zero on the left gives back `n`.\n\nTarget statement: `0 + n = n`.",
                "For every natural number n, adding zero on the left gives back n.\nTarget statement: n + 0 = n.",
            ]:
                with self.subTest(statement=statement):
                    plan, _ = agent.draft_formalization_plan(
                        SourceRef(path="input.md", kind=SourceKind.MARKDOWN),
                        statement + "\n",
                        TheoremExtraction(
                            title="Zero add",
                            informal_statement=statement,
                            definitions=["Nat"],
                            lemmas=["Nat.zero_add"],
                            propositions=[],
                            dependencies=["Nat.zero_add"],
                            notes=[],
                        ),
                        EnrichmentReport(
                            self_contained=True,
                            satisfied_prerequisites=["Nat.zero_add exists."],
                            missing_prerequisites=[],
                            required_plan_additions=[],
                            recommended_scope="Keep the theorem over Nat.",
                            difficulty_assessment="easy",
                            open_questions=[],
                            next_steps=["Approve the merged plan."],
                            human_handoff="Everything needed is already present.",
                        ),
                        ContextPack(
                            recommended_imports=["FormalizationEngineWorkspace.Basic"],
                            local_examples=["examples/inputs/zero_add.md"],
                            notes=["Use Nat.zero_add."],
                        ),
                    )

                    self.assertEqual(plan.theorem_name, "legacy_zero_add")
                    self.assertEqual(plan.title, "Zero add")
                    self.assertEqual(plan.assumptions, ["n : Nat"])
                    if "Target statement: n + 0 = n" in statement:
                        self.assertEqual(plan.conclusion, "n + 0 = n")
                    else:
                        self.assertEqual(plan.conclusion, "0 + n = n")
                    self.assertEqual(plan.symbols, ["Nat", "0", "+", "="])

    def test_subprocess_plan_payload_prefers_real_legacy_theorem_spec(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            provider_script = repo_root / "old_provider.py"
            provider_script.write_text(
                "\n".join(
                    [
                        "from __future__ import annotations",
                        "import json",
                        "import sys",
                        "",
                        "def main() -> int:",
                        "    request = json.load(sys.stdin)",
                        "    stage = request['stage']",
                        "    if stage == 'draft_theorem_spec':",
                        "        parsed_output = {",
                        "            'title': 'Zero add',",
                        "            'informal_statement': request['extraction']['informal_statement'],",
                        "            'assumptions': ['n : Nat'],",
                        "            'conclusion': '0 + n = n',",
                        "            'symbols': ['Nat', '0', '+', '='],",
                        "            'ambiguities': [],",
                        "            'paraphrase': 'Adding zero on the left returns n.',",
                        "        }",
                        "        json.dump({'prompt': 'legacy-spec', 'raw_response': 'legacy-spec', 'parsed_output': parsed_output}, sys.stdout)",
                        "        return 0",
                        "    theorem_spec = request['theorem_spec']",
                        "    parsed_output = {",
                        "        'title': theorem_spec['title'],",
                        "        'informal_statement': theorem_spec['informal_statement'],",
                        "        'assumptions': theorem_spec['assumptions'],",
                        "        'conclusion': theorem_spec['conclusion'],",
                        "        'symbols': theorem_spec['symbols'],",
                        "        'ambiguities': theorem_spec['ambiguities'],",
                        "        'paraphrase': theorem_spec['paraphrase'],",
                        "        'theorem_name': 'legacy_zero_add',",
                        "        'imports': ['FormalizationEngineWorkspace.Basic'],",
                        "        'prerequisites_to_formalize': request['enrichment']['required_plan_additions'],",
                        "        'helper_definitions': [],",
                        "        'target_statement': 'theorem legacy_zero_add (n : Nat) : 0 + n = n',",
                        "        'proof_sketch': ['Use Nat.zero_add.'],",
                        "        'human_summary': 'Legacy provider compatibility.',",
                        "    }",
                        "    json.dump({'prompt': 'legacy-plan', 'raw_response': 'legacy-plan', 'parsed_output': parsed_output}, sys.stdout)",
                        "    return 0",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            provider_script.chmod(0o755)

            agent = SubprocessFormalizationAgent(["python3", str(provider_script)])
            plan, _ = agent.draft_formalization_plan(
                SourceRef(path="input.md", kind=SourceKind.MARKDOWN),
                "For every natural number n, adding zero on the left gives back n.\n",
                TheoremExtraction(
                    title="Zero add",
                    informal_statement="For every natural number n, adding zero on the left gives back n.",
                    definitions=["Nat"],
                    lemmas=["Nat.zero_add"],
                    propositions=[],
                    dependencies=["Nat.zero_add"],
                    notes=[],
                ),
                EnrichmentReport(
                    self_contained=True,
                    satisfied_prerequisites=["Nat.zero_add exists."],
                    missing_prerequisites=[],
                    required_plan_additions=[],
                    recommended_scope="Keep the theorem over Nat.",
                    difficulty_assessment="easy",
                    open_questions=[],
                    next_steps=["Approve the merged plan."],
                    human_handoff="Everything needed is already present.",
                ),
                ContextPack(
                    recommended_imports=["FormalizationEngineWorkspace.Basic"],
                    local_examples=["examples/inputs/zero_add.md"],
                    notes=["Use Nat.zero_add."],
                ),
            )

            self.assertEqual(plan.assumptions, ["n : Nat"])
            self.assertEqual(plan.conclusion, "0 + n = n")
            self.assertEqual(plan.symbols, ["Nat", "0", "+", "="])

    def test_subprocess_plan_payload_tolerates_unknown_legacy_spec_stage_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            provider_script = repo_root / "new_provider.py"
            provider_script.write_text(
                "\n".join(
                    [
                        "from __future__ import annotations",
                        "import json",
                        "import sys",
                        "",
                        "def main() -> int:",
                        "    request = json.load(sys.stdin)",
                        "    if request['stage'] == 'draft_theorem_spec':",
                        "        print('Unknown stage draft_theorem_spec', file=sys.stderr)",
                        "        raise SystemExit(1)",
                        "    theorem_spec = request['theorem_spec']",
                        "    parsed_output = {",
                        "        'title': theorem_spec['title'],",
                        "        'informal_statement': theorem_spec['informal_statement'],",
                        "        'assumptions': theorem_spec['assumptions'],",
                        "        'conclusion': theorem_spec['conclusion'],",
                        "        'symbols': theorem_spec['symbols'],",
                        "        'ambiguities': theorem_spec['ambiguities'],",
                        "        'paraphrase': theorem_spec['paraphrase'],",
                        "        'theorem_name': 'legacy_zero_add',",
                        "        'imports': ['FormalizationEngineWorkspace.Basic'],",
                        "        'prerequisites_to_formalize': request['enrichment']['required_plan_additions'],",
                        "        'helper_definitions': [],",
                        "        'target_statement': 'theorem legacy_zero_add (n : Nat) : 0 + n = n',",
                        "        'proof_sketch': ['Use Nat.zero_add.'],",
                        "        'human_summary': 'Legacy provider compatibility.',",
                        "    }",
                        "    json.dump({'prompt': 'legacy-plan', 'raw_response': 'legacy-plan', 'parsed_output': parsed_output}, sys.stdout)",
                        "    return 0",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            provider_script.chmod(0o755)

            agent = SubprocessFormalizationAgent(["python3", str(provider_script)])
            plan, _ = agent.draft_formalization_plan(
                SourceRef(path="input.md", kind=SourceKind.MARKDOWN),
                "For all n : Nat, 0 + n = n.\n",
                TheoremExtraction(
                    title="Zero add",
                    informal_statement="For all n : Nat, 0 + n = n.",
                    definitions=["Nat"],
                    lemmas=["Nat.zero_add"],
                    propositions=[],
                    dependencies=["Nat.zero_add"],
                    notes=[],
                ),
                EnrichmentReport(
                    self_contained=True,
                    satisfied_prerequisites=["Nat.zero_add exists."],
                    missing_prerequisites=[],
                    required_plan_additions=[],
                    recommended_scope="Keep the theorem over Nat.",
                    difficulty_assessment="easy",
                    open_questions=[],
                    next_steps=["Approve the merged plan."],
                    human_handoff="Everything needed is already present.",
                ),
                ContextPack(
                    recommended_imports=["FormalizationEngineWorkspace.Basic"],
                    local_examples=["examples/inputs/zero_add.md"],
                    notes=["Use Nat.zero_add."],
                ),
            )

            self.assertEqual(plan.assumptions, ["n : Nat"])
            self.assertEqual(plan.conclusion, "0 + n = n")

    def test_resume_cli_accepts_agent_command_for_legacy_command_runs(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        provider_script = project_root / "examples" / "providers" / "scripted_repair_provider.py"
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "legacy-command"
            (run_root / "00_input").mkdir(parents=True)
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-command",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "subprocess:scripted_repair_provider.py",
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "created",
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "00_input" / "source.txt").write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )
            (run_root / "00_input" / "normalized.md").write_text(
                "For every natural number n, adding zero on the left gives back n.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "lean_formalization_engine.cli",
                    "--repo-root",
                    str(repo_root),
                    "resume",
                    "legacy-command",
                    "--agent-command",
                    f"python3 {provider_script}",
                ],
                cwd=project_root,
                env={**os.environ, "PYTHONPATH": "src"},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("awaiting_enrichment_approval", result.stdout)
            manifest_payload = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest_payload["agent_config"]["backend"], "command")
            self.assertEqual(
                manifest_payload["agent_config"]["command"],
                ["python3", str(provider_script)],
            )

    def test_load_manifest_infers_unknown_legacy_agent_name_as_command_backend(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "legacy-custom"
            run_root.mkdir(parents=True)
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-custom",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "my-custom-provider",
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "created",
                    }
                ),
                encoding="utf-8",
            )

            manifest = _load_manifest(repo_root, "legacy-custom")
            self.assertEqual(manifest.agent_config.backend, "command")

            resumed_config = _resume_agent_config(
                manifest,
                Namespace(agent_command="python3 provider.py"),
                repo_root,
            )
            self.assertEqual(resumed_config.backend, "command")
            self.assertEqual(resumed_config.command, ["python3", "provider.py"])

    def test_resume_agent_config_allows_overriding_persisted_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            new_provider = repo_root / "providers" / "new_provider.py"
            new_provider.parent.mkdir(parents=True)
            new_provider.write_text("print('provider')\n", encoding="utf-8")
            manifest = RunManifest(
                run_id="legacy-command",
                source=SourceRef(path="input.md", kind=SourceKind.MARKDOWN),
                agent_name="subprocess:old_provider.py",
                agent_config=AgentConfig(
                    backend="command",
                    command=["python3", "/old/provider.py"],
                ),
                template_dir=str(repo_root / "lean_workspace_template"),
                created_at="2026-04-16T00:00:00Z",
                updated_at="2026-04-16T00:01:00Z",
                current_stage=RunStage.CREATED,
            )

            resumed_config = _resume_agent_config(
                manifest,
                Namespace(agent_command="python3 providers/new_provider.py"),
                repo_root,
            )

            self.assertEqual(
                resumed_config.command,
                ["python3", str(new_provider)],
            )

    def test_resume_cli_final_approval_does_not_require_legacy_command(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "legacy-command-final"
            run_root.mkdir(parents=True)
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-command-final",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "subprocess:old_provider.py",
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_final_review",
                        "attempt_count": 1,
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "10_final").mkdir(parents=True)
            (run_root / "10_final" / "final_candidate.lean").write_text(
                "import FormalizationEngineWorkspace.Basic\n",
                encoding="utf-8",
            )
            (run_root / "10_final" / "final_report.md").write_text(
                "Legacy final report.\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "lean_formalization_engine.cli",
                    "--repo-root",
                    str(repo_root),
                    "resume",
                    "legacy-command-final",
                    "--auto-approve",
                ],
                cwd=project_root,
                env={**os.environ, "PYTHONPATH": "src"},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("completed", result.stdout)
            self.assertTrue((run_root / "04_final" / "final.lean").exists())

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

    def test_template_resolution_falls_back_to_packaged_template_without_lake(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        package_template_dir = project_root / "lean_workspace_template"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)

            resolution = resolve_workspace_template(
                temp_root,
                package_template_dir,
                lake_path="/definitely/missing/lake",
            )

            self.assertEqual(resolution.origin, "packaged")
            self.assertEqual(resolution.command, [])
            self.assertEqual(resolution.template_dir, package_template_dir.resolve())

    def test_template_resolution_preserves_existing_ineligible_template(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        package_template_dir = project_root / "lean_workspace_template"
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            target_dir = temp_root / "lean_workspace_template"
            (target_dir / "FormalizationEngineWorkspace").mkdir(parents=True)
            (target_dir / "lakefile.toml").write_text(
                'name = "Scratch"\n[[require]]\nname = "mathlib"\n',
                encoding="utf-8",
            )
            (target_dir / "stale.txt").write_text("stale", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "already exists"):
                resolve_workspace_template(
                    temp_root,
                    package_template_dir,
                )

            self.assertTrue((target_dir / "stale.txt").exists())

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
        self.assertIn(
            f"Resume with: terry --repo-root {repo_root.resolve()} resume zero-add",
            summary,
        )

    def test_render_manifest_summary_prefers_existing_legacy_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "legacy-final"
            (run_root / "10_final").mkdir(parents=True)
            (run_root / "10_final" / "final_report.md").write_text("# Final report\n", encoding="utf-8")
            (run_root / "10_final" / "decision.json").write_text(
                '{"approved": false}\n',
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-final",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "repair_resume_agent",
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_final_review",
                        "attempt_count": 1,
                    }
                ),
                encoding="utf-8",
            )

            manifest = _load_manifest(repo_root, "legacy-final")
            summary = render_manifest_summary(manifest, repo_root)

            self.assertIn("Stage: awaiting_final_approval", summary)
            self.assertIn("Checkpoint: artifacts/runs/legacy-final/10_final/final_report.md", summary)
            self.assertIn("Review file: artifacts/runs/legacy-final/10_final/decision.json", summary)

    def test_render_manifest_summary_includes_agent_command_for_legacy_command_run(self) -> None:
        repo_root = Path("/tmp/terry")
        manifest = RunManifest(
            run_id="legacy-command",
            source=SourceRef(path="examples/inputs/zero_add.md", kind=SourceKind.MARKDOWN),
            agent_name="my-custom-provider",
            agent_config=AgentConfig(backend="command"),
            template_dir="/tmp/terry/lean_workspace_template",
            created_at="2026-04-16T00:00:00Z",
            updated_at="2026-04-16T00:01:00Z",
            current_stage=RunStage.AWAITING_ENRICHMENT_APPROVAL,
        )

        summary = render_manifest_summary(manifest, repo_root)

        self.assertIn("--agent-command", summary)
        self.assertIn("python3 path/to/provider.py", summary)

    def test_render_manifest_summary_prefers_legacy_spec_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "legacy-spec"
            (run_root / "04_spec").mkdir(parents=True)
            (run_root / "04_spec" / "theorem_spec.json").write_text(
                '{"title": "Zero add"}\n',
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-spec",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "repair_resume_agent",
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_spec_review",
                    }
                ),
                encoding="utf-8",
            )

            manifest = _load_manifest(repo_root, "legacy-spec")
            summary = render_manifest_summary(manifest, repo_root)

            self.assertIn("Checkpoint: artifacts/runs/legacy-spec/04_spec/theorem_spec.json", summary)
            self.assertIn("Review file: artifacts/runs/legacy-spec/04_spec/review.md", summary)

    def test_render_manifest_summary_prefers_legacy_plan_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "legacy-plan"
            (run_root / "04_spec").mkdir(parents=True)
            (run_root / "06_plan").mkdir(parents=True)
            (run_root / "04_spec" / "theorem_spec.json").write_text(
                '{"title": "Zero add"}\n',
                encoding="utf-8",
            )
            (run_root / "06_plan" / "formalization_plan.json").write_text(
                '{"theorem_name": "zero_add_legacy"}\n',
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-plan",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "repair_resume_agent",
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_plan_review",
                    }
                ),
                encoding="utf-8",
            )

            manifest = _load_manifest(repo_root, "legacy-plan")
            summary = render_manifest_summary(manifest, repo_root)

            self.assertIn("Checkpoint: artifacts/runs/legacy-plan/06_plan/formalization_plan.json", summary)
            self.assertIn("Review file: artifacts/runs/legacy-plan/06_plan/decision.json", summary)

    def test_build_parser_accepts_hidden_legacy_approve_commands(self) -> None:
        parser = build_parser()

        for command in [
            "approve-enrichment",
            "approve-spec",
            "approve-plan",
            "approve-final",
            "approve-stall",
        ]:
            with self.subTest(command=command):
                args = parser.parse_args([command, "--run-id", "legacy-run"])
                self.assertEqual(args.command, command)
                self.assertEqual(args.run_id, "legacy-run")

    def test_legacy_run_command_remains_supported(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            source_path = project_root / "examples" / "inputs" / "zero_add.md"

            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "lean_formalization_engine.cli",
                    "--repo-root",
                    str(repo_root),
                    "--lake-path",
                    "/definitely/missing/lake",
                    "--agent-backend",
                    "demo",
                    "run",
                    "--source",
                    str(source_path),
                    "--run-id",
                    "legacy-run",
                    "--auto-approve",
                ],
                cwd=project_root,
                env={**os.environ, "PYTHONPATH": "src"},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["run_id"], "legacy-run")
            self.assertEqual(payload["current_stage"], "proof_blocked")

    def test_legacy_resume_and_status_flags_remain_supported(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "awaiting-enrichment"
            (run_root / "01_enrichment").mkdir(parents=True)
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "awaiting-enrichment",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "demo_zero_add_agent",
                        "agent_config": {"backend": "demo", "command": None, "codex_model": None},
                        "template_dir": str(repo_root / "missing-template"),
                        "lake_path": "/definitely/missing/lake",
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_enrichment_approval",
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "01_enrichment" / "checkpoint.md").write_text("# checkpoint\n", encoding="utf-8")
            (run_root / "01_enrichment" / "review.md").write_text(
                "# review\n\ndecision: pending\n\nNotes:\n\n",
                encoding="utf-8",
            )

            status_result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "lean_formalization_engine.cli",
                    "--repo-root",
                    str(repo_root),
                    "status",
                    "--run-id",
                    "awaiting-enrichment",
                ],
                cwd=project_root,
                env={**os.environ, "PYTHONPATH": "src"},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(status_result.returncode, 0, status_result.stderr)
            self.assertEqual(json.loads(status_result.stdout)["current_stage"], "awaiting_enrichment_approval")

            resume_result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "lean_formalization_engine.cli",
                    "--repo-root",
                    str(repo_root),
                    "resume",
                    "--run-id",
                    "awaiting-enrichment",
                ],
                cwd=project_root,
                env={**os.environ, "PYTHONPATH": "src"},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(resume_result.returncode, 0, resume_result.stderr)
            self.assertEqual(json.loads(resume_result.stdout)["current_stage"], "awaiting_enrichment_approval")

    def test_legacy_approve_enrichment_command_advances_terry_run(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            source_path = project_root / "examples" / "inputs" / "zero_add.md"

            prove_result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "lean_formalization_engine.cli",
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
                env={**os.environ, "PYTHONPATH": "src"},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(prove_result.returncode, 0, prove_result.stderr)
            self.assertIn("Stage: awaiting_enrichment_approval", prove_result.stdout)

            approve_result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "lean_formalization_engine.cli",
                    "--repo-root",
                    str(repo_root),
                    "approve-enrichment",
                    "--run-id",
                    "legacy-approve",
                    "--notes",
                    "Looks good.",
                ],
                cwd=project_root,
                env={**os.environ, "PYTHONPATH": "src"},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(approve_result.returncode, 0, approve_result.stderr)
            self.assertEqual(json.loads(approve_result.stdout)["current_stage"], "awaiting_enrichment_approval")
            self.assertEqual(
                json.loads((repo_root / "artifacts" / "runs" / "legacy-approve" / "01_enrichment" / "decision.json").read_text(encoding="utf-8"))[
                    "decision"
                ],
                "approve",
            )

            resume_result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "lean_formalization_engine.cli",
                    "--repo-root",
                    str(repo_root),
                    "resume",
                    "--run-id",
                    "legacy-approve",
                ],
                cwd=project_root,
                env={**os.environ, "PYTHONPATH": "src"},
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(resume_result.returncode, 0, resume_result.stderr)
            self.assertEqual(json.loads(resume_result.stdout)["current_stage"], "awaiting_plan_approval")

    def test_legacy_theorem_spec_payload_keeps_all_quantified_binders(self) -> None:
        payload = _legacy_theorem_spec_payload(
            TheoremExtraction(
                title="Commute add",
                informal_statement="For every natural numbers m and n, m + n = n + m.",
                definitions=["Nat"],
                lemmas=["Nat.add_comm"],
                propositions=[],
                dependencies=["Nat.add_comm"],
                notes=[],
            )
        )

        self.assertEqual(payload["assumptions"], ["m : Nat", "n : Nat"])
        self.assertEqual(payload["conclusion"], "m + n = n + m")

    def test_legacy_theorem_spec_payload_accepts_qualified_binders(self) -> None:
        payload = _legacy_theorem_spec_payload(
            TheoremExtraction(
                title="Positive commute add",
                informal_statement="For every positive integers m and n, m + n = n + m.",
                definitions=["Int"],
                lemmas=[],
                propositions=[],
                dependencies=[],
                notes=[],
            )
        )

        self.assertEqual(payload["assumptions"], ["m : Int", "n : Int"])
        self.assertEqual(payload["conclusion"], "m + n = n + m")

    def test_legacy_theorem_spec_payload_accepts_qualified_binders_with_explicit_type(self) -> None:
        payload = _legacy_theorem_spec_payload(
            TheoremExtraction(
                title="Positive commute add",
                informal_statement="For every positive integers m and n : Int, m + n = n + m.",
                definitions=["Int"],
                lemmas=[],
                propositions=[],
                dependencies=[],
                notes=[],
            )
        )

        self.assertEqual(payload["assumptions"], ["m : Int", "n : Int"])
        self.assertEqual(payload["conclusion"], "m + n = n + m")

    def test_legacy_theorem_spec_payload_accepts_typed_separator_without_comma(self) -> None:
        payload = _legacy_theorem_spec_payload(
            TheoremExtraction(
                title="Commute add",
                informal_statement="For every m and n : Nat: m + n = n + m.",
                definitions=["Nat"],
                lemmas=[],
                propositions=[],
                dependencies=[],
                notes=[],
            )
        )

        self.assertEqual(payload["assumptions"], ["m : Nat", "n : Nat"])
        self.assertEqual(payload["conclusion"], "m + n = n + m")

    def test_legacy_theorem_spec_payload_accepts_comma_separated_binders(self) -> None:
        payload = _legacy_theorem_spec_payload(
            TheoremExtraction(
                title="Commute add",
                informal_statement="For every natural numbers m, n, m + n = n + m.",
                definitions=["Nat"],
                lemmas=[],
                propositions=[],
                dependencies=[],
                notes=[],
            )
        )

        self.assertEqual(payload["assumptions"], ["m : Nat", "n : Nat"])
        self.assertEqual(payload["conclusion"], "m + n = n + m")

    def test_legacy_theorem_spec_payload_accepts_comma_separated_typed_binders(self) -> None:
        payload = _legacy_theorem_spec_payload(
            TheoremExtraction(
                title="Commute add",
                informal_statement="For every natural numbers m, n : Nat, m + n = n + m.",
                definitions=["Nat"],
                lemmas=[],
                propositions=[],
                dependencies=[],
                notes=[],
            )
        )

        self.assertEqual(payload["assumptions"], ["m : Nat", "n : Nat"])
        self.assertEqual(payload["conclusion"], "m + n = n + m")

    def test_resume_override_persists_new_command_in_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "persist-command"
            (run_root / "01_enrichment").mkdir(parents=True)
            (run_root / "00_input").mkdir(parents=True)
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "persist-command",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "subprocess:old",
                        "agent_config": {
                            "backend": "command",
                            "command": ["python3", "old.py"],
                            "codex_model": None,
                        },
                        "template_dir": str(repo_root / "lean_workspace_template"),
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_enrichment_approval",
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "00_input" / "source.txt").write_text("source\n", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text("source\n", encoding="utf-8")
            (run_root / "01_enrichment" / "checkpoint.md").write_text("# checkpoint\n", encoding="utf-8")
            (run_root / "01_enrichment" / "review.md").write_text(
                "# review\n\ndecision: approve\n\nNotes:\n\n",
                encoding="utf-8",
            )
            (run_root / "01_enrichment" / "extraction.json").write_text(
                json.dumps(
                    {
                        "title": "Zero add",
                        "informal_statement": "For every natural number n, 0 + n = n.",
                        "definitions": ["Nat"],
                        "lemmas": ["Nat.zero_add"],
                        "propositions": [],
                        "dependencies": ["Nat.zero_add"],
                        "notes": [],
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "01_enrichment" / "enrichment_report.json").write_text(
                json.dumps(
                    {
                        "self_contained": True,
                        "satisfied_prerequisites": ["Nat.zero_add exists."],
                        "missing_prerequisites": [],
                        "required_plan_additions": [],
                        "recommended_scope": "Keep the theorem over Nat.",
                        "difficulty_assessment": "easy",
                        "open_questions": [],
                        "next_steps": ["Approve the merged plan."],
                        "human_handoff": "Everything needed is already present.",
                    }
                ),
                encoding="utf-8",
            )

            manifest = _load_manifest(repo_root, "persist-command")
            args = Namespace(agent_command="python3 new.py")
            agent_config = _resume_agent_config(manifest, args, repo_root)
            workflow = FormalizationWorkflow(
                repo_root=repo_root,
                agent=build_agent(agent_config, repo_root),
                agent_config=agent_config,
                lean_runner=LeanRunner(template_dir=Path(manifest.template_dir), lake_path=None),
            )

            with self.assertRaises(Exception):
                workflow.resume("persist-command")

            persisted = json.loads((run_root / "manifest.json").read_text(encoding="utf-8"))["agent_config"]
            self.assertEqual(persisted["command"], ["python3", "new.py"])

    def test_prove_validation_happens_before_template_resolution(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            target_dir = repo_root / "lean_workspace_template"
            target_dir.mkdir(parents=True)
            (target_dir / "stale.txt").write_text("stale", encoding="utf-8")

            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "lean_formalization_engine.cli",
                    "--repo-root",
                    str(repo_root),
                    "prove",
                    "missing.md",
                    "--run-id",
                    "existing-run",
                    "--agent-backend",
                    "demo",
                ],
                cwd=project_root,
                env={**os.environ, "PYTHONPATH": "src"},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertTrue((target_dir / "stale.txt").exists())
            self.assertFalse((target_dir / "FormalizationEngineWorkspace" / "Basic.lean").exists())

    def test_prove_does_not_require_template_before_first_checkpoint(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            source_path = project_root / "examples" / "inputs" / "zero_add.md"

            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "lean_formalization_engine.cli",
                    "--repo-root",
                    str(repo_root),
                    "--lake-path",
                    "/definitely/missing/lake",
                    "prove",
                    str(source_path),
                    "--run-id",
                    "deferred-template",
                    "--agent-backend",
                    "demo",
                ],
                cwd=project_root,
                env={**os.environ, "PYTHONPATH": "src"},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("awaiting_enrichment_approval", result.stdout)
            self.assertTrue((repo_root / "artifacts" / "runs" / "deferred-template" / "01_enrichment" / "review.md").exists())

    def test_prove_bootstraps_nonexistent_repo_root(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "new-root"
            source_path = project_root / "examples" / "inputs" / "zero_add.md"

            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "lean_formalization_engine.cli",
                    "--repo-root",
                    str(repo_root),
                    "--lake-path",
                    "/definitely/missing/lake",
                    "prove",
                    str(source_path),
                    "--run-id",
                    "fresh-root",
                    "--agent-backend",
                    "demo",
                ],
                cwd=project_root,
                env={**os.environ, "PYTHONPATH": "src"},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("awaiting_enrichment_approval", result.stdout)
            self.assertTrue((repo_root / "artifacts" / "runs" / "fresh-root" / "01_enrichment" / "review.md").exists())

    def test_prove_reports_missing_lake_as_proof_blocked(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            source_path = project_root / "examples" / "inputs" / "zero_add.md"

            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "lean_formalization_engine.cli",
                    "--repo-root",
                    str(repo_root),
                    "--lake-path",
                    "/definitely/missing/lake",
                    "prove",
                    str(source_path),
                    "--run-id",
                    "missing-lake",
                    "--agent-backend",
                    "demo",
                    "--auto-approve",
                ],
                cwd=project_root,
                env={**os.environ, "PYTHONPATH": "src"},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("proof_blocked", result.stdout)

    def test_prove_rejects_existing_ineligible_template_cleanly(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            target_dir = repo_root / "lean_workspace_template"
            (target_dir / "FormalizationEngineWorkspace").mkdir(parents=True)
            (target_dir / "lakefile.toml").write_text(
                'name = "Scratch"\n[[require]]\nname = "mathlib"\n',
                encoding="utf-8",
            )
            (target_dir / "local.txt").write_text("keep", encoding="utf-8")
            source_path = project_root / "examples" / "inputs" / "zero_add.md"

            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "lean_formalization_engine.cli",
                    "--repo-root",
                    str(repo_root),
                    "prove",
                    str(source_path),
                    "--run-id",
                    "bad-template",
                    "--agent-backend",
                    "demo",
                    "--auto-approve",
                ],
                cwd=project_root,
                env={**os.environ, "PYTHONPATH": "src"},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not an eligible Terry template", result.stderr)
            self.assertTrue((target_dir / "local.txt").exists())

    def test_resume_does_not_require_template_while_checkpoint_is_still_pending(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "awaiting-enrichment"
            (run_root / "01_enrichment").mkdir(parents=True)
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "awaiting-enrichment",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "demo_zero_add_agent",
                        "agent_config": {"backend": "demo", "command": None, "codex_model": None},
                        "template_dir": str(repo_root / "missing-template"),
                        "lake_path": "/definitely/missing/lake",
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_enrichment_approval",
                    }
                ),
                encoding="utf-8",
            )
            (run_root / "01_enrichment" / "checkpoint.md").write_text("# checkpoint\n", encoding="utf-8")
            (run_root / "01_enrichment" / "review.md").write_text(
                "# review\n\ndecision: pending\n\nNotes:\n\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [
                    "python3",
                    "-m",
                    "lean_formalization_engine.cli",
                    "--repo-root",
                    str(repo_root),
                    "resume",
                    "awaiting-enrichment",
                ],
                cwd=project_root,
                env={**os.environ, "PYTHONPATH": "src"},
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("awaiting_enrichment_approval", result.stdout)

    def test_load_manifest_falls_back_for_legacy_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir)
            run_root = repo_root / "artifacts" / "runs" / "legacy"
            run_root.mkdir(parents=True)
            project_root = Path(__file__).resolve().parents[1]
            child_template = repo_root / "child" / "lean_workspace_template"
            shutil.copytree(project_root / "lean_workspace_template", child_template)
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
            self.assertEqual(manifest.template_dir, str(child_template.resolve()))
