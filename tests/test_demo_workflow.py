from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

import lean_formalization_engine.lean_runner as lean_runner_module
from lean_formalization_engine.demo_agent import DemoFormalizationAgent
from lean_formalization_engine.lean_runner import LeanRunner
from lean_formalization_engine.models import (
    AgentConfig,
    AgentTurn,
    BackendStage,
    CompileAttempt,
    RunManifest,
    RunStage,
    SourceKind,
    SourceRef,
    StageRequest,
)
from lean_formalization_engine.storage import RunStore
from lean_formalization_engine.subprocess_agent import SubprocessFormalizationAgent
from lean_formalization_engine.workflow import FormalizationWorkflow


class ContentCheckingLeanRunner:
    def __init__(self) -> None:
        self.attempts: list[int] = []
        self.template_dir = Path("/tmp/unused-template")
        self.lake_path: str | None = None

    def compile_candidate(self, store: RunStore, candidate_relative_path: str, attempt: int) -> CompileAttempt:
        self.attempts.append(attempt)
        content = store.read_text(candidate_relative_path)
        contains_sorry = "sorry" in content
        passed = not contains_sorry
        return CompileAttempt(
            attempt=attempt,
            command=["lake build FormalizationEngineWorkspace"],
            stdout="" if contains_sorry else "ok",
            stderr="found sorry" if contains_sorry else "",
            returncode=1 if contains_sorry else 0,
            diagnostics=["found sorry"] if contains_sorry else [],
            fast_check_passed=passed,
            build_passed=passed,
            contains_sorry=contains_sorry,
            missing_toolchain=False,
            quality_gate_passed=not contains_sorry,
            passed=passed,
            status="compile_failed" if contains_sorry else "passed",
        )


class RecordingRepairAgent:
    name = "recording_repair_agent"

    def __init__(self) -> None:
        self.requests: list[StageRequest] = []

    def run_stage(self, request: StageRequest) -> AgentTurn:
        self.requests.append(request)
        output_dir = Path(request.repo_root) / request.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        if request.stage == BackendStage.ENRICHMENT:
            content = "# Enrichment Handoff\n\nSelf-contained over Nat.\n"
            (output_dir / "handoff.md").write_text(content, encoding="utf-8")
        elif request.stage == BackendStage.PLAN:
            content = "\n".join(
                [
                    "# Plan Handoff",
                    "",
                    "Proposed theorem name: `recorded_zero_add`",
                    "Target statement: `theorem recorded_zero_add (n : Nat) : 0 + n = n`",
                    "Proof route: use `Nat.zero_add`.",
                    "",
                ]
            )
            (output_dir / "handoff.md").write_text(content, encoding="utf-8")
        elif request.stage == BackendStage.PROOF:
            proof_retry = request.review_notes_path is not None and request.review_notes_path.endswith(
                "03_proof/review.md"
            )
            if not proof_retry:
                content = "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem recorded_zero_add (n : Nat) : 0 + n = n := by",
                        "  sorry",
                        "",
                    ]
                )
            else:
                content = "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem recorded_zero_add (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                )
            (output_dir / "candidate.lean").write_text(content, encoding="utf-8")
        else:
            raise ValueError(f"Unsupported stage {request.stage.value}")

        return AgentTurn(
            request_payload={"stage": request.stage.value},
            prompt=f"{request.stage.value} prompt",
            raw_response=f"{request.stage.value} response",
        )


class AlwaysSorryAgent:
    name = "always_sorry_agent"

    def run_stage(self, request: StageRequest) -> AgentTurn:
        output_dir = Path(request.repo_root) / request.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        if request.stage == BackendStage.ENRICHMENT:
            (output_dir / "handoff.md").write_text("# Enrichment Handoff\n\nStill scoped over Nat.\n", encoding="utf-8")
        elif request.stage == BackendStage.PLAN:
            (output_dir / "handoff.md").write_text(
                "\n".join(
                    [
                        "# Plan Handoff",
                        "",
                        "Target statement: `theorem stuck_zero_add (n : Nat) : 0 + n = n`",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        elif request.stage == BackendStage.PROOF:
            (output_dir / "candidate.lean").write_text(
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem stuck_zero_add (n : Nat) : 0 + n = n := by",
                        "  sorry",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
        else:
            raise ValueError(f"Unsupported stage {request.stage.value}")

        return AgentTurn(
            request_payload={"stage": request.stage.value},
            prompt=f"{request.stage.value} prompt",
            raw_response=f"{request.stage.value} response",
        )


class BrokenAgent:
    name = "broken_agent"

    def run_stage(self, request: StageRequest) -> AgentTurn:
        return AgentTurn(request_payload={"stage": request.stage.value}, prompt="broken", raw_response="broken")


class DemoWorkflowTest(unittest.TestCase):
    def _write_review(self, run_root: Path, stage_dir: str, decision: str, notes: str) -> None:
        (run_root / stage_dir / "review.md").write_text(
            "\n".join(
                [
                    f"# {stage_dir}",
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

    def _write_fake_lake(self, directory: Path, *, name: str = "lake", version: str = "fake-lake") -> Path:
        fake_lake = directory / name
        workspace_template = (
            Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
        )
        fake_lake.write_text(
            "\n".join(
                [
                    "#!/usr/bin/env python3",
                    "import pathlib",
                    "import re",
                    "import shutil",
                    "import sys",
                    "",
                    f"WORKSPACE_TEMPLATE = pathlib.Path({str(workspace_template)!r})",
                    f"VERSION = {version!r}",
                    "",
                    "def required_packages(cwd: pathlib.Path) -> list[str]:",
                    "    toml_path = cwd / 'lakefile.toml'",
                    "    if toml_path.exists():",
                    "        names = []",
                    "        in_require = False",
                    "        for line in toml_path.read_text(encoding='utf-8').splitlines():",
                    "            stripped = line.strip()",
                    "            if stripped.startswith('[['):",
                    "                in_require = stripped.startswith('[[require]]')",
                    "                continue",
                    "            if not in_require:",
                    "                continue",
                    "            match = re.match(r'^name\\s*=\\s*[\"\\']([^\"\\']+)[\"\\']', stripped)",
                    "            if match:",
                    "                names.append(match.group(1))",
                    "        return names",
                    "    lean_path = cwd / 'lakefile.lean'",
                    "    if lean_path.exists():",
                    "        names = []",
                    "        for line in lean_path.read_text(encoding='utf-8').splitlines():",
                    "            match = re.match(r'^\\\\s*require\\\\s+([A-Za-z_][A-Za-z0-9_\\']*)\\\\b', line)",
                    "            if match:",
                    "                names.append(match.group(1))",
                    "        return names",
                    "    return []",
                    "",
                    "def main() -> int:",
                    "    args = sys.argv[1:]",
                    "    if args[:1] == ['--version']:",
                    "        print(VERSION)",
                        "        return 0",
                    "    if args[:1] == ['update']:",
                    "        manifest = pathlib.Path.cwd() / 'lake-manifest.json'",
                    "        manifest.write_text('{\"version\": 7, \"packagesDir\": \".lake/packages\"}', encoding='utf-8')",
                    "        for name in required_packages(pathlib.Path.cwd()):",
                    "            package_dir = pathlib.Path.cwd() / '.lake' / 'packages' / name",
                    "            package_dir.mkdir(parents=True, exist_ok=True)",
                    "            (package_dir / 'Pkg.lean').write_text('-- pkg\\n', encoding='utf-8')",
                    "            (package_dir / 'lakefile.toml').write_text(f'name = \"{name}\"\\n', encoding='utf-8')",
                    "        return 0",
                    "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                    "        manifest = pathlib.Path.cwd() / 'lake-manifest.json'",
                    "        packages = pathlib.Path.cwd() / '.lake' / 'packages'",
                    "        if not manifest.exists() and not packages.exists():",
                    "            print('missing manifest; use `lake update` to generate one', file=sys.stderr)",
                    "            return 1",
                    "        generated = pathlib.Path.cwd() / 'FormalizationEngineWorkspace' / 'Generated.lean'",
                    "        content = generated.read_text(encoding='utf-8')",
                    "        if 'sorry' in content:",
                    "            print(f'{generated}: found sorry', file=sys.stderr)",
                    "            return 1",
                    "        return 0",
                    "    if args[:3] == ['new', 'lean_workspace_template', 'math']:",
                    "        target = pathlib.Path.cwd() / 'lean_workspace_template'",
                    "        if target.exists():",
                    "            shutil.rmtree(target)",
                    "        shutil.copytree(WORKSPACE_TEMPLATE, target)",
                    "        return 0",
                    "    print(f'unexpected args: {args}', file=sys.stderr)",
                    "    return 1",
                    "",
                    "if __name__ == '__main__':",
                    "    raise SystemExit(main())",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        fake_lake.chmod(0o755)
        return fake_lake

    def _write_named_fake_lake(self, directory: Path, name: str) -> Path:
        return self._write_fake_lake(directory, name=name, version=name)

    def test_demo_workflow_completes_without_old_payload_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.prove(source_path=source_path, run_id="demo-test", auto_approve=True)

            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(manifest.final_output_path, "04_final/final.lean")
            run_root = temp_root / "artifacts" / "runs" / "demo-test"
            self.assertTrue((run_root / "01_enrichment" / "handoff.md").exists())
            self.assertTrue((run_root / "02_plan" / "handoff.md").exists())
            self.assertFalse((run_root / "01_enrichment" / "enrichment_report.json").exists())
            self.assertFalse((run_root / "02_plan" / "formalization_plan.json").exists())

    def test_manual_review_path_uses_review_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, n + 0 = n.\n", encoding="utf-8")

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.prove(source_path=source_path, run_id="manual-demo", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            run_root = temp_root / "artifacts" / "runs" / "manual-demo"
            self.assertTrue((run_root / "01_enrichment" / "checkpoint.md").exists())
            self.assertTrue((run_root / "01_enrichment" / "review.md").exists())

            self._write_review(
                run_root,
                "01_enrichment",
                "approve",
                "The theorem is ready for planning.",
            )
            manifest = workflow.resume("manual-demo", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)

            self._write_review(
                run_root,
                "02_plan",
                "approve",
                "The theorem statement and proof route are correct.",
            )
            manifest = workflow.resume("manual-demo", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_APPROVAL)

            self._write_review(
                run_root,
                "04_final",
                "approve",
                "The compiling Lean file is acceptable.",
            )
            manifest = workflow.resume("manual-demo", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)

    def test_resume_rejects_backend_switch_for_paused_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.prove(source_path=source_path, run_id="stable-backend", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            provider_script = Path(__file__).resolve().parents[1] / "examples" / "providers" / "scripted_repair_provider.py"
            command = [sys.executable, str(provider_script)]
            wrong_backend_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=SubprocessFormalizationAgent(command),
                agent_config=AgentConfig(backend="command", command=command),
                lean_runner=ContentCheckingLeanRunner(),
            )

            with self.assertRaisesRegex(ValueError, "keep the backend recorded in the manifest"):
                wrong_backend_workflow.resume("stable-backend", auto_approve=False)

            manifest = workflow.status("stable-backend")
            self.assertEqual(manifest.agent_config.backend, "demo")

    def test_resume_keeps_packaged_template_after_missing_lake_stall(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()

            blocked_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(temp_root / "lean_workspace_template", lake_path="missing-lake"),
            )
            manifest = blocked_workflow.prove(source_path=source_path, run_id="stall-demo", auto_approve=True)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(Path(manifest.template_dir), packaged_template)

            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            fake_lake = self._write_fake_lake(temp_root)

            resumed_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=LeanRunner(
                    Path(manifest.template_dir),
                    repo_root=temp_root,
                    lake_path=str(fake_lake),
                ),
            )
            manifest = resumed_workflow.resume("stall-demo", auto_approve=True)
            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(Path(manifest.template_dir), packaged_template)

    def test_lean_runner_reuses_shared_workspace_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            first_store = RunStore(temp_root / "artifacts", "cache-a")
            first_store.ensure_new()
            first_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem cached_zero_add_a (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            first_result = runner.compile_candidate(first_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(first_result.passed)
            self.assertEqual(
                first_result.command,
                ["lake update", "lake build FormalizationEngineWorkspace"],
            )

            shared_workspace = temp_root / ".terry" / "lean_workspace"
            sentinel = shared_workspace / ".lake" / "packages" / "mathlib" / "sentinel.txt"
            sentinel.parent.mkdir(parents=True, exist_ok=True)
            sentinel.write_text("warm", encoding="utf-8")

            second_store = RunStore(temp_root / "artifacts", "cache-b")
            second_store.ensure_new()
            second_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem cached_zero_add_b (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            second_result = runner.compile_candidate(second_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(second_result.passed)
            self.assertEqual(second_result.command, ["lake build FormalizationEngineWorkspace"])
            self.assertTrue(sentinel.exists())

    def test_lean_runner_sanitizes_generated_path_to_attempt_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "path-sanitize")
            store.ensure_new()
            candidate_relative_path = "03_proof/attempts/attempt_0001/candidate.lean"
            store.write_text(
                candidate_relative_path,
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem path_sanitize (n : Nat) : 0 + n = n := by",
                        "  sorry",
                        "",
                    ]
                ),
            )

            result = runner.compile_candidate(store, candidate_relative_path, 1)
            self.assertFalse(result.passed)
            self.assertIn(
                "artifacts/runs/path-sanitize/03_proof/attempts/attempt_0001/candidate.lean: found sorry",
                result.stderr,
            )
            self.assertNotIn(".terry/lean_workspace/FormalizationEngineWorkspace/Generated.lean", result.stderr)

    def test_lean_runner_rebuilds_shared_workspace_when_template_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            first_store = RunStore(temp_root / "artifacts", "refresh-a")
            first_store.ensure_new()
            first_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem refresh_zero_add_a (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            first_result = runner.compile_candidate(first_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(first_result.passed)

            shared_workspace = temp_root / ".terry" / "lean_workspace"
            stale_marker = shared_workspace / "stale.txt"
            stale_marker.write_text("remove me", encoding="utf-8")
            template_basic = temp_root / "lean_workspace_template" / "FormalizationEngineWorkspace" / "Basic.lean"
            template_basic.write_text(
                template_basic.read_text(encoding="utf-8") + "\n-- changed template\n",
                encoding="utf-8",
            )

            second_store = RunStore(temp_root / "artifacts", "refresh-b")
            second_store.ensure_new()
            second_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem refresh_zero_add_b (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            second_result = runner.compile_candidate(second_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(second_result.passed)
            self.assertEqual(
                second_result.command,
                ["lake update", "lake build FormalizationEngineWorkspace"],
            )
            self.assertFalse(stale_marker.exists())
            self.assertIn(
                "-- changed template",
                (shared_workspace / "FormalizationEngineWorkspace" / "Basic.lean").read_text(encoding="utf-8"),
            )
            self.assertEqual(
                (shared_workspace / "lake-manifest.json").read_text(encoding="utf-8"),
                '{"version": 7, "packagesDir": ".lake/packages"}',
            )

    def test_lean_runner_rebuilds_shared_workspace_when_vendored_lake_contents_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            vendored_file = temp_root / "lean_workspace_template" / ".lake" / "packages" / "mathlib" / "Marker.lean"
            vendored_file.parent.mkdir(parents=True, exist_ok=True)
            vendored_file.write_text("first", encoding="utf-8")
            (vendored_file.parent / "lakefile.toml").write_text(
                "\n".join(
                    [
                        "name = \"mathlib\"",
                        "version = \"0.1.0\"",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            first_store = RunStore(temp_root / "artifacts", "vendored-a")
            first_store.ensure_new()
            first_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem vendored_zero_add_a (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            first_result = runner.compile_candidate(first_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(first_result.passed)
            self.assertEqual(
                first_result.command,
                ["lake update", "lake build FormalizationEngineWorkspace"],
            )

            shared_workspace = temp_root / ".terry" / "lean_workspace"
            stale_marker = shared_workspace / "stale-vendored.txt"
            stale_marker.write_text("remove me", encoding="utf-8")
            vendored_file.write_text("second", encoding="utf-8")

            second_store = RunStore(temp_root / "artifacts", "vendored-b")
            second_store.ensure_new()
            second_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem vendored_zero_add_b (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            second_result = runner.compile_candidate(second_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(second_result.passed)
            self.assertEqual(
                second_result.command,
                ["lake update", "lake build FormalizationEngineWorkspace"],
            )
            self.assertFalse(stale_marker.exists())
            self.assertEqual(
                (shared_workspace / ".lake" / "packages" / "mathlib" / "Marker.lean").read_text(encoding="utf-8"),
                "second",
            )

    def test_lean_runner_rebuilds_when_non_git_vendored_content_changes_without_stat_change(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            vendored_file = temp_root / "lean_workspace_template" / ".lake" / "packages" / "mathlib" / "Marker.lean"
            vendored_file.parent.mkdir(parents=True, exist_ok=True)
            vendored_file.write_text("alpha\n", encoding="utf-8")
            original_mtime_ns = vendored_file.stat().st_mtime_ns
            (vendored_file.parent / "lakefile.toml").write_text(
                "\n".join(
                    [
                        "name = \"mathlib\"",
                        "version = \"0.1.0\"",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            first_store = RunStore(temp_root / "artifacts", "vendored-stat-a")
            first_store.ensure_new()
            first_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem vendored_stat_a (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            first_result = runner.compile_candidate(first_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(first_result.passed)

            shared_workspace = temp_root / ".terry" / "lean_workspace"
            stale_marker = shared_workspace / "stale-vendored-stat.txt"
            stale_marker.write_text("remove me", encoding="utf-8")
            vendored_file.write_text("omega\n", encoding="utf-8")
            os.utime(vendored_file, ns=(original_mtime_ns, original_mtime_ns))

            second_store = RunStore(temp_root / "artifacts", "vendored-stat-b")
            second_store.ensure_new()
            second_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem vendored_stat_b (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            second_result = runner.compile_candidate(second_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(second_result.passed)
            self.assertEqual(
                second_result.command,
                ["lake update", "lake build FormalizationEngineWorkspace"],
            )
            self.assertFalse(stale_marker.exists())
            self.assertEqual(
                (shared_workspace / ".lake" / "packages" / "mathlib" / "Marker.lean").read_text(encoding="utf-8"),
                "omega\n",
            )

    def test_lean_runner_does_not_copy_template_build_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            fake_lake = self._write_fake_lake(temp_root)
            top_level_build = temp_root / "lean_workspace_template" / "build" / "stale.txt"
            top_level_build.parent.mkdir(parents=True, exist_ok=True)
            top_level_build.write_text("stale", encoding="utf-8")
            lake_build = (
                temp_root
                / "lean_workspace_template"
                / ".lake"
                / "build"
                / "lib"
                / "FormalizationEngineWorkspace"
                / "Basic.olean"
            )
            lake_build.parent.mkdir(parents=True, exist_ok=True)
            lake_build.write_text("stale", encoding="utf-8")
            vendored_lake_build = (
                temp_root
                / "lean_workspace_template"
                / ".lake"
                / "packages"
                / "mathlib"
                / ".lake"
                / "build"
                / "lib"
                / "Mathlib"
                / "Vendored.olean"
            )
            vendored_lake_build.parent.mkdir(parents=True, exist_ok=True)
            vendored_lake_build.write_text("stale", encoding="utf-8")
            vendored_build = (
                temp_root
                / "lean_workspace_template"
                / ".lake"
                / "packages"
                / "mathlib"
                / "build"
                / "Vendored.olean"
            )
            vendored_build.parent.mkdir(parents=True, exist_ok=True)
            vendored_build.write_text("stale", encoding="utf-8")
            nested_vendored_build = (
                temp_root
                / "lean_workspace_template"
                / ".lake"
                / "packages"
                / "mathlib"
                / ".lake"
                / "packages"
                / "aux"
                / "build"
                / "Nested.olean"
            )
            nested_vendored_build.parent.mkdir(parents=True, exist_ok=True)
            nested_vendored_build.write_text("stale", encoding="utf-8")
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "no-build-copy")
            store.ensure_new()
            store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem no_build_copy (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )

            result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(result.passed)
            shared_workspace = temp_root / ".terry" / "lean_workspace"
            self.assertFalse((shared_workspace / "build" / "stale.txt").exists())
            self.assertFalse(
                (
                    shared_workspace
                    / ".lake"
                    / "build"
                    / "lib"
                    / "FormalizationEngineWorkspace"
                    / "Basic.olean"
                ).exists()
            )
            self.assertFalse(
                (
                    shared_workspace
                    / ".lake"
                    / "packages"
                    / "mathlib"
                    / ".lake"
                    / "build"
                    / "lib"
                    / "Mathlib"
                    / "Vendored.olean"
                ).exists()
            )
            self.assertFalse(
                (
                    shared_workspace
                    / ".lake"
                    / "packages"
                    / "mathlib"
                    / "build"
                    / "Vendored.olean"
                ).exists()
            )
            self.assertFalse(
                (
                    shared_workspace
                    / ".lake"
                    / "packages"
                    / "mathlib"
                    / ".lake"
                    / "packages"
                    / "aux"
                    / "build"
                    / "Nested.olean"
                ).exists()
            )

    def test_lean_runner_updates_when_vendored_packages_are_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            vendored_file = temp_root / "lean_workspace_template" / ".lake" / "packages" / "aux" / "marker.txt"
            vendored_file.parent.mkdir(parents=True, exist_ok=True)
            vendored_file.write_text("aux", encoding="utf-8")
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "partial-vendored")
            store.ensure_new()
            store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem partial_vendored (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )

            result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(result.passed)
            self.assertEqual(
                result.command,
                ["lake update", "lake build FormalizationEngineWorkspace"],
            )

    def test_lean_runner_retries_lake_update_after_failed_manifest_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            state_file = temp_root / "lake-update-state.txt"
            state_file.write_text("fail", encoding="utf-8")
            fake_lake = temp_root / "lake-retry"
            fake_lake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import pathlib",
                        "import sys",
                        "",
                        f"STATE_FILE = pathlib.Path({str(state_file)!r})",
                        "",
                        "def main() -> int:",
                        "    args = sys.argv[1:]",
                        "    cwd = pathlib.Path.cwd()",
                        "    if args[:1] == ['--version']:",
                        "        print('lake-retry')",
                        "        return 0",
                        "    if args[:1] == ['update']:",
                        "        manifest = cwd / 'lake-manifest.json'",
                        "        manifest.write_text('{\"version\": 7, \"packagesDir\": \".lake/packages\"}', encoding='utf-8')",
                        "        if STATE_FILE.read_text(encoding='utf-8').strip() == 'fail':",
                        "            STATE_FILE.write_text('ok', encoding='utf-8')",
                        "            print('network down', file=sys.stderr)",
                        "            return 1",
                        "        package_dir = cwd / '.lake' / 'packages' / 'mathlib'",
                        "        package_dir.mkdir(parents=True, exist_ok=True)",
                        "        (package_dir / 'Pkg.lean').write_text('-- pkg\\n', encoding='utf-8')",
                        "        (package_dir / 'lakefile.toml').write_text('name = \"mathlib\"\\n', encoding='utf-8')",
                        "        return 0",
                        "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                        "        if not (cwd / '.lake' / 'packages' / 'mathlib' / 'Pkg.lean').exists():",
                        "            print('missing packages: mathlib', file=sys.stderr)",
                        "            return 1",
                        "        return 0",
                        "    return 1",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake.chmod(0o755)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            first_store = RunStore(temp_root / "artifacts", "failed-update-a")
            first_store.ensure_new()
            first_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem failed_update_a (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            first_result = runner.compile_candidate(first_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertFalse(first_result.passed)
            self.assertEqual(first_result.command, ["lake-retry update"])

            shared_workspace = temp_root / ".terry" / "lean_workspace"
            self.assertFalse((shared_workspace / "lake-manifest.json").exists())

            second_store = RunStore(temp_root / "artifacts", "failed-update-b")
            second_store.ensure_new()
            second_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem failed_update_b (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            second_result = runner.compile_candidate(second_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(second_result.passed)
            self.assertEqual(
                second_result.command,
                ["lake-retry update", "lake-retry build FormalizationEngineWorkspace"],
            )

    def test_lean_runner_repairs_manifest_backed_incomplete_vendored_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            (temp_root / "lean_workspace_template" / "lake-manifest.json").write_text("{}", encoding="utf-8")
            vendored = temp_root / "lean_workspace_template" / ".lake" / "packages" / "mathlib"
            vendored.mkdir(parents=True, exist_ok=True)
            (vendored / "README.md").write_text("incomplete\n", encoding="utf-8")
            fake_lake = temp_root / "lake-manifest-repair"
            fake_lake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import pathlib",
                        "import sys",
                        "",
                        "def main() -> int:",
                        "    args = sys.argv[1:]",
                        "    cwd = pathlib.Path.cwd()",
                        "    if args[:1] == ['--version']:",
                        "        print('lake-manifest-repair')",
                        "        return 0",
                        "    if args[:1] == ['update']:",
                        "        pkg = cwd / '.lake' / 'packages' / 'mathlib'",
                        "        pkg.mkdir(parents=True, exist_ok=True)",
                        "        (pkg / 'Pkg.lean').write_text('-- repaired\\n', encoding='utf-8')",
                        "        (pkg / 'lakefile.toml').write_text('name = \"mathlib\"\\n', encoding='utf-8')",
                        "        (cwd / 'lake-manifest.json').write_text('{}', encoding='utf-8')",
                        "        return 0",
                        "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                        "        if not (cwd / '.lake' / 'packages' / 'mathlib' / 'Pkg.lean').exists():",
                        "            print('mathlib incomplete', file=sys.stderr)",
                        "            return 1",
                        "        return 0",
                        "    return 1",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake.chmod(0o755)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "manifest-backed-vendored")
            store.ensure_new()
            store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem manifest_backed_vendored (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )

            result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(result.passed)
            self.assertEqual(
                result.command,
                ["lake-manifest-repair update", "lake-manifest-repair build FormalizationEngineWorkspace"],
            )

    def test_lean_runner_rebuilds_when_git_backed_vendored_package_is_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            mathlib_dir = temp_root / "lean_workspace_template" / ".lake" / "packages" / "mathlib"
            mathlib_dir.mkdir(parents=True, exist_ok=True)
            tracked_file = mathlib_dir / "Marker.lean"
            tracked_file.write_text("first\n", encoding="utf-8")
            (mathlib_dir / "lakefile.toml").write_text(
                "\n".join(
                    [
                        "name = \"mathlib\"",
                        "version = \"0.1.0\"",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init"], cwd=mathlib_dir, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=mathlib_dir, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=mathlib_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(["git", "add", "Marker.lean"], cwd=mathlib_dir, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=mathlib_dir, check=True, capture_output=True, text=True)
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            first_store = RunStore(temp_root / "artifacts", "git-vendored-a")
            first_store.ensure_new()
            first_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem git_vendored_a (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            first_result = runner.compile_candidate(first_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(first_result.passed)
            self.assertEqual(
                first_result.command,
                ["lake update", "lake build FormalizationEngineWorkspace"],
            )

            shared_workspace = temp_root / ".terry" / "lean_workspace"
            stale_marker = shared_workspace / "stale-git-vendored.txt"
            stale_marker.write_text("remove me", encoding="utf-8")
            tracked_file.write_text("second\n", encoding="utf-8")

            second_store = RunStore(temp_root / "artifacts", "git-vendored-b")
            second_store.ensure_new()
            second_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem git_vendored_b (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            second_result = runner.compile_candidate(second_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(second_result.passed)
            self.assertEqual(
                second_result.command,
                ["lake update", "lake build FormalizationEngineWorkspace"],
            )
            self.assertFalse(stale_marker.exists())

    def test_lean_runner_rebuilds_when_git_backed_vendored_ignore_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            mathlib_dir = temp_root / "lean_workspace_template" / ".lake" / "packages" / "mathlib"
            mathlib_dir.mkdir(parents=True, exist_ok=True)
            tracked_file = mathlib_dir / "Marker.lean"
            tracked_file.write_text("tracked\n", encoding="utf-8")
            ignored_file = mathlib_dir / "Generated.lean"
            ignored_file.write_text("first\n", encoding="utf-8")
            (mathlib_dir / ".gitignore").write_text("Generated.lean\n", encoding="utf-8")
            (mathlib_dir / "lakefile.toml").write_text(
                "\n".join(
                    [
                        "name = \"mathlib\"",
                        "version = \"0.1.0\"",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init"], cwd=mathlib_dir, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=mathlib_dir, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=mathlib_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(
                ["git", "add", "Marker.lean", ".gitignore", "lakefile.toml"],
                cwd=mathlib_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(["git", "commit", "-m", "init"], cwd=mathlib_dir, check=True, capture_output=True, text=True)
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            first_store = RunStore(temp_root / "artifacts", "git-vendored-ignore-a")
            first_store.ensure_new()
            first_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem git_vendored_ignore_a (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            first_result = runner.compile_candidate(first_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(first_result.passed)

            shared_workspace = temp_root / ".terry" / "lean_workspace"
            stale_marker = shared_workspace / "stale-git-vendored-ignore.txt"
            stale_marker.write_text("remove me", encoding="utf-8")
            ignored_file.write_text("second\n", encoding="utf-8")

            second_store = RunStore(temp_root / "artifacts", "git-vendored-ignore-b")
            second_store.ensure_new()
            second_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem git_vendored_ignore_b (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            second_result = runner.compile_candidate(second_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(second_result.passed)
            self.assertEqual(
                second_result.command,
                ["lake update", "lake build FormalizationEngineWorkspace"],
            )
            self.assertFalse(stale_marker.exists())
            self.assertEqual(
                (shared_workspace / ".lake" / "packages" / "mathlib" / "Generated.lean").read_text(encoding="utf-8"),
                "second\n",
            )

    def test_lean_runner_falls_back_when_git_is_unavailable_for_vendored_signature(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            mathlib_dir = temp_root / "lean_workspace_template" / ".lake" / "packages" / "mathlib"
            mathlib_dir.mkdir(parents=True, exist_ok=True)
            (mathlib_dir / ".git").write_text("gitdir: nowhere\n", encoding="utf-8")
            (mathlib_dir / "Marker.lean").write_text("-- vendored\n", encoding="utf-8")
            (mathlib_dir / "lakefile.toml").write_text("name = \"mathlib\"\n", encoding="utf-8")
            fake_lake = temp_root / "lake-no-git"
            fake_lake.write_text(
                "\n".join(
                    [
                        f"#!{sys.executable}",
                        "import sys",
                        "",
                        "def main() -> int:",
                        "    args = sys.argv[1:]",
                        "    if args[:1] == ['--version']:",
                        "        print('lake-no-git')",
                        "        return 0",
                        "    if args[:1] == ['update']:",
                        "        return 0",
                        "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                        "        return 0",
                        "    return 1",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake.chmod(0o755)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "git-missing")
            store.ensure_new()
            store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem git_missing (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )

            original_path = os.environ.get("PATH", "")
            os.environ["PATH"] = ""
            try:
                result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            finally:
                os.environ["PATH"] = original_path

            self.assertTrue(result.passed)
            self.assertEqual(
                result.command,
                ["lake-no-git update", "lake-no-git build FormalizationEngineWorkspace"],
            )

    def test_lean_runner_rebuilds_when_dirty_git_vendored_file_changes_again(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            mathlib_dir = temp_root / "lean_workspace_template" / ".lake" / "packages" / "mathlib"
            mathlib_dir.mkdir(parents=True, exist_ok=True)
            tracked_file = mathlib_dir / "Marker.lean"
            tracked_file.write_text("first\n", encoding="utf-8")
            (mathlib_dir / "lakefile.toml").write_text(
                "\n".join(
                    [
                        "name = \"mathlib\"",
                        "version = \"0.1.0\"",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            subprocess.run(["git", "init"], cwd=mathlib_dir, check=True, capture_output=True, text=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=mathlib_dir, check=True, capture_output=True, text=True)
            subprocess.run(
                ["git", "config", "user.email", "test@example.com"],
                cwd=mathlib_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run(["git", "add", "Marker.lean"], cwd=mathlib_dir, check=True, capture_output=True, text=True)
            subprocess.run(["git", "commit", "-m", "init"], cwd=mathlib_dir, check=True, capture_output=True, text=True)
            tracked_file.write_text("dirty first\n", encoding="utf-8")
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            first_store = RunStore(temp_root / "artifacts", "git-vendored-dirty-a")
            first_store.ensure_new()
            first_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem git_vendored_dirty_a (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            first_result = runner.compile_candidate(first_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(first_result.passed)

            shared_workspace = temp_root / ".terry" / "lean_workspace"
            stale_marker = shared_workspace / "stale-git-vendored-dirty.txt"
            stale_marker.write_text("remove me", encoding="utf-8")
            tracked_file.write_text("dirty second\n", encoding="utf-8")

            second_store = RunStore(temp_root / "artifacts", "git-vendored-dirty-b")
            second_store.ensure_new()
            second_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem git_vendored_dirty_b (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            second_result = runner.compile_candidate(second_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(second_result.passed)
            self.assertEqual(
                second_result.command,
                ["lake update", "lake build FormalizationEngineWorkspace"],
            )
            self.assertFalse(stale_marker.exists())
            self.assertEqual(
                (shared_workspace / ".lake" / "packages" / "mathlib" / "Marker.lean").read_text(encoding="utf-8"),
                "dirty second\n",
            )

    def test_lean_runner_respects_vendored_packages_for_lakefile_lean_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            (temp_root / "lean_workspace_template" / "lakefile.toml").unlink()
            (temp_root / "lean_workspace_template" / "lakefile.lean").write_text(
                "\n".join(
                    [
                        "import Lake",
                        "open Lake DSL",
                        "",
                        "package FormalizationEngineWorkspace",
                        "",
                        "require mathlib from git",
                        "  \"https://github.com/leanprover-community/mathlib4.git\" @ \"v4.29.0\"",
                        "",
                        "@[default_target]",
                        "lean_lib FormalizationEngineWorkspace",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            mathlib_dir = temp_root / "lean_workspace_template" / ".lake" / "packages" / "mathlib"
            mathlib_dir.mkdir(parents=True, exist_ok=True)
            (mathlib_dir / "Marker.lean").write_text("vendored\n", encoding="utf-8")
            (mathlib_dir / "lakefile.toml").write_text(
                "\n".join(
                    [
                        "name = \"mathlib\"",
                        "version = \"0.1.0\"",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "lakefile-lean-vendored")
            store.ensure_new()
            store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem lakefile_lean_vendored (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )

            result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(result.passed)
            self.assertEqual(
                result.command,
                ["lake update", "lake build FormalizationEngineWorkspace"],
            )

    def test_lean_runner_updates_when_vendored_package_has_only_metadata_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            mathlib_dir = temp_root / "lean_workspace_template" / ".lake" / "packages" / "mathlib"
            mathlib_dir.mkdir(parents=True, exist_ok=True)
            (mathlib_dir / "README.md").write_text("# metadata only\n", encoding="utf-8")
            (mathlib_dir / "lean-toolchain").write_text("leanprover/lean4:v4.29.0\n", encoding="utf-8")
            (mathlib_dir / "lakefile.toml").write_text(
                "\n".join(
                    [
                        "name = \"mathlib\"",
                        "version = \"0.1.0\"",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "metadata-only-vendored")
            store.ensure_new()
            store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem metadata_only_vendored (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )

            result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(result.passed)
            self.assertEqual(
                result.command,
                ["lake update", "lake build FormalizationEngineWorkspace"],
            )

    def test_lean_runner_updates_when_toml_require_uses_comment_or_single_quotes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            (temp_root / "lean_workspace_template" / "lakefile.toml").write_text(
                "\n".join(
                    [
                        "name = \"FormalizationEngineWorkspace\"",
                        "version = \"0.1.0\"",
                        "defaultTargets = [\"FormalizationEngineWorkspace\"]",
                        "",
                        "[[require]] # pinned",
                        "name = 'mathlib' # pinned",
                        "",
                        "[[lean_lib]]",
                        "name = \"FormalizationEngineWorkspace\"",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (temp_root / "lean_workspace_template" / ".lake" / "packages").mkdir(parents=True, exist_ok=True)
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "quoted-toml-vendored")
            store.ensure_new()
            store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem quoted_toml_vendored (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )

            result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(result.passed)
            self.assertEqual(
                result.command,
                ["lake update", "lake build FormalizationEngineWorkspace"],
            )

    def test_lean_runner_reuses_checked_in_manifest_without_vendored_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            (temp_root / "lean_workspace_template" / "lake-manifest.json").write_text("{}", encoding="utf-8")
            fake_lake = temp_root / "lake-manifest-only"
            fake_lake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import sys",
                        "",
                        "def main() -> int:",
                        "    args = sys.argv[1:]",
                        "    if args[:1] == ['--version']:",
                        "        print('lake-manifest-only')",
                        "        return 0",
                        "    if args[:1] == ['update']:",
                        "        print('update should not run', file=sys.stderr)",
                        "        return 1",
                        "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                        "        return 0",
                        "    return 1",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake.chmod(0o755)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "manifest-only")
            store.ensure_new()
            store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem manifest_only (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )

            result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(result.passed)
            self.assertEqual(result.command, ["lake-manifest-only build FormalizationEngineWorkspace"])

    def test_lean_runner_reuses_checked_in_manifest_with_complete_vendored_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            (temp_root / "lean_workspace_template" / "lake-manifest.json").write_text("{}", encoding="utf-8")
            mathlib_dir = temp_root / "lean_workspace_template" / ".lake" / "packages" / "mathlib"
            mathlib_dir.mkdir(parents=True, exist_ok=True)
            (mathlib_dir / "Mathlib.lean").write_text("-- vendored mathlib\n", encoding="utf-8")
            (mathlib_dir / "lakefile.toml").write_text("name = \"mathlib\"\n", encoding="utf-8")
            fake_lake = temp_root / "lake-vendored-manifest"
            fake_lake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import sys",
                        "",
                        "def main() -> int:",
                        "    args = sys.argv[1:]",
                        "    if args[:1] == ['--version']:",
                        "        print('lake-vendored-manifest')",
                        "        return 0",
                        "    if args[:1] == ['update']:",
                        "        print('update should not run', file=sys.stderr)",
                        "        return 1",
                        "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                        "        return 0",
                        "    return 1",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake.chmod(0o755)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "manifest-vendored")
            store.ensure_new()
            store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem manifest_vendored (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )

            result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(result.passed)
            self.assertEqual(result.command, ["lake-vendored-manifest build FormalizationEngineWorkspace"])

    def test_lean_runner_preserves_copied_manifest_when_update_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            manifest_text = "{\"version\": 7}\n"
            (temp_root / "lean_workspace_template" / "lake-manifest.json").write_text(manifest_text, encoding="utf-8")
            mathlib_dir = temp_root / "lean_workspace_template" / ".lake" / "packages" / "mathlib"
            mathlib_dir.mkdir(parents=True, exist_ok=True)
            (mathlib_dir / "README.md").write_text("# incomplete vendored tree\n", encoding="utf-8")
            fake_lake = temp_root / "lake-preserve-manifest"
            fake_lake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import sys",
                        "",
                        "def main() -> int:",
                        "    args = sys.argv[1:]",
                        "    if args[:1] == ['--version']:",
                        "        print('lake-preserve-manifest')",
                        "        return 0",
                        "    if args[:1] == ['update']:",
                        "        print('update failed', file=sys.stderr)",
                        "        return 1",
                        "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                        "        return 0",
                        "    return 1",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake.chmod(0o755)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "preserve-manifest")
            store.ensure_new()
            store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem preserve_manifest (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )

            result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertFalse(result.passed)
            shared_manifest = temp_root / ".terry" / "lean_workspace" / "lake-manifest.json"
            self.assertEqual(shared_manifest.read_text(encoding="utf-8"), manifest_text)

    def test_lean_runner_skips_lake_update_for_local_path_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            (temp_root / "lean_workspace_template" / "lakefile.toml").write_text(
                "\n".join(
                    [
                        "name = \"FormalizationEngineWorkspace\"",
                        "version = \"0.1.0\"",
                        "defaultTargets = [\"FormalizationEngineWorkspace\"]",
                        "",
                        "[[require]]",
                        "name = \"aux\"",
                        "path = \"Packages/aux\"",
                        "",
                        "[[lean_lib]]",
                        "name = \"FormalizationEngineWorkspace\"",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            aux_dir = temp_root / "lean_workspace_template" / "Packages" / "aux"
            aux_dir.mkdir(parents=True, exist_ok=True)
            (aux_dir / "Aux.lean").write_text("-- local path dependency\n", encoding="utf-8")
            (aux_dir / "lakefile.toml").write_text("name = \"aux\"\n", encoding="utf-8")
            fake_lake = temp_root / "lake-path-only"
            fake_lake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import pathlib",
                        "import sys",
                        "",
                        "def main() -> int:",
                        "    args = sys.argv[1:]",
                        "    if args[:1] == ['--version']:",
                        "        print('lake-path-only')",
                        "        return 0",
                        "    if args[:1] == ['update']:",
                        "        print('update should not run', file=sys.stderr)",
                        "        return 1",
                        "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                        "        return 0",
                        "    return 1",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake.chmod(0o755)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "path-dependency")
            store.ensure_new()
            store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem path_dependency (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )

            result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(result.passed)
            self.assertEqual(result.command, ["lake-path-only build FormalizationEngineWorkspace"])

    def test_lean_runner_skips_lake_update_for_multiline_lakefile_lean_path_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            (temp_root / "lean_workspace_template" / "lakefile.toml").unlink()
            (temp_root / "lean_workspace_template" / "lakefile.lean").write_text(
                "\n".join(
                    [
                        "import Lake",
                        "open Lake DSL",
                        "",
                        "package FormalizationEngineWorkspace",
                        "",
                        "require aux from",
                        "  \"./Packages/aux\"",
                        "",
                        "@[default_target]",
                        "lean_lib FormalizationEngineWorkspace",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            aux_dir = temp_root / "lean_workspace_template" / "Packages" / "aux"
            aux_dir.mkdir(parents=True, exist_ok=True)
            (aux_dir / "Aux.lean").write_text("-- local path dependency\n", encoding="utf-8")
            (aux_dir / "lakefile.toml").write_text("name = \"aux\"\n", encoding="utf-8")
            fake_lake = temp_root / "lake-multiline-path-only"
            fake_lake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import sys",
                        "",
                        "def main() -> int:",
                        "    args = sys.argv[1:]",
                        "    if args[:1] == ['--version']:",
                        "        print('lake-multiline-path-only')",
                        "        return 0",
                        "    if args[:1] == ['update']:",
                        "        print('update should not run', file=sys.stderr)",
                        "        return 1",
                        "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                        "        return 0",
                        "    return 1",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake.chmod(0o755)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "multiline-path-dependency")
            store.ensure_new()
            store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem multiline_path_dependency (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )

            result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(result.passed)
            self.assertEqual(
                result.command,
                ["lake-multiline-path-only build FormalizationEngineWorkspace"],
            )

    def test_lean_runner_updates_for_transitive_external_dependencies_of_local_path_packages(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            (temp_root / "lean_workspace_template" / "lakefile.toml").write_text(
                "\n".join(
                    [
                        "name = \"FormalizationEngineWorkspace\"",
                        "version = \"0.1.0\"",
                        "defaultTargets = [\"FormalizationEngineWorkspace\"]",
                        "",
                        "[[require]]",
                        "name = \"aux\"",
                        "path = \"Packages/aux\"",
                        "",
                        "[[lean_lib]]",
                        "name = \"FormalizationEngineWorkspace\"",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            aux_dir = temp_root / "lean_workspace_template" / "Packages" / "aux"
            aux_dir.mkdir(parents=True, exist_ok=True)
            (aux_dir / "Aux.lean").write_text("-- local path dependency\n", encoding="utf-8")
            (aux_dir / "lakefile.toml").write_text(
                "\n".join(
                    [
                        "name = \"aux\"",
                        "",
                        "[[require]]",
                        "name = \"mathlib\"",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake = temp_root / "lake-transitive"
            fake_lake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import pathlib",
                        "import sys",
                        "",
                        "def main() -> int:",
                        "    args = sys.argv[1:]",
                        "    if args[:1] == ['--version']:",
                        "        print('lake-transitive')",
                        "        return 0",
                        "    if args[:1] == ['update']:",
                        "        cwd = pathlib.Path.cwd()",
                        "        (cwd / 'lake-manifest.json').write_text('{}', encoding='utf-8')",
                        "        pkg = cwd / '.lake' / 'packages' / 'mathlib'",
                        "        pkg.mkdir(parents=True, exist_ok=True)",
                        "        (pkg / 'Pkg.lean').write_text('-- dep\\n', encoding='utf-8')",
                        "        return 0",
                        "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                        "        cwd = pathlib.Path.cwd()",
                        "        if not (cwd / '.lake' / 'packages' / 'mathlib').exists():",
                        "            print('missing transitive dep', file=sys.stderr)",
                        "            return 1",
                        "        return 0",
                        "    return 1",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake.chmod(0o755)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "transitive-path-dependency")
            store.ensure_new()
            store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem transitive_path_dependency (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )

            result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(result.passed)
            self.assertEqual(
                result.command,
                ["lake-transitive update", "lake-transitive build FormalizationEngineWorkspace"],
            )

    def test_lean_runner_adds_shared_cache_to_local_git_exclude(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            subprocess.run(["git", "init"], cwd=temp_root, check=True, capture_output=True, text=True)
            (temp_root / ".gitignore").write_text(
                "\n".join(
                    [
                        "artifacts/",
                        "lean_workspace_template/",
                        "lake*",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            subprocess.run(["git", "add", ".gitignore"], cwd=temp_root, check=True, capture_output=True, text=True)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            store = RunStore(temp_root / "artifacts", "git-exclude")
            store.ensure_new()
            store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem git_exclude (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )

            result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(result.passed)
            exclude_text = (temp_root / ".git" / "info" / "exclude").read_text(encoding="utf-8")
            self.assertIn(".terry/", exclude_text)
            status = subprocess.run(
                ["git", "status", "--short"],
                cwd=temp_root,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertNotIn(".terry/", status.stdout)

    def test_lean_runner_rebuilds_shared_workspace_when_lake_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            first_lake = self._write_named_fake_lake(temp_root, "lake-first")
            second_lake = self._write_named_fake_lake(temp_root, "lake-second")
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(first_lake),
            )

            first_store = RunStore(temp_root / "artifacts", "lake-a")
            first_store.ensure_new()
            first_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem lake_zero_add_a (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            first_result = runner.compile_candidate(first_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(first_result.passed)

            shared_workspace = temp_root / ".terry" / "lean_workspace"
            stale_marker = shared_workspace / "stale-toolchain.txt"
            stale_marker.write_text("remove me", encoding="utf-8")
            runner.lake_path = str(second_lake)

            second_store = RunStore(temp_root / "artifacts", "lake-b")
            second_store.ensure_new()
            second_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem lake_zero_add_b (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            second_result = runner.compile_candidate(second_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(second_result.passed)
            self.assertEqual(
                second_result.command,
                ["lake-second update", "lake-second build FormalizationEngineWorkspace"],
            )
            self.assertFalse(stale_marker.exists())

    def test_lean_runner_rebuilds_shared_workspace_when_lake_changes_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            fake_lake = self._write_fake_lake(temp_root, version="lake-v1")
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            first_store = RunStore(temp_root / "artifacts", "lake-same-path-a")
            first_store.ensure_new()
            first_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem lake_same_path_a (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            first_result = runner.compile_candidate(first_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(first_result.passed)

            shared_workspace = temp_root / ".terry" / "lean_workspace"
            stale_marker = shared_workspace / "stale-same-path.txt"
            stale_marker.write_text("remove me", encoding="utf-8")
            self._write_fake_lake(temp_root, version="lake-v2")

            second_store = RunStore(temp_root / "artifacts", "lake-same-path-b")
            second_store.ensure_new()
            second_store.write_text(
                "03_proof/attempts/attempt_0001/candidate.lean",
                "\n".join(
                    [
                        "import FormalizationEngineWorkspace.Basic",
                        "",
                        "theorem lake_same_path_b (n : Nat) : 0 + n = n := by",
                        "  simpa using Nat.zero_add n",
                        "",
                    ]
                ),
            )
            second_result = runner.compile_candidate(second_store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            self.assertTrue(second_result.passed)
            self.assertEqual(
                second_result.command,
                ["lake update", "lake build FormalizationEngineWorkspace"],
            )
            self.assertFalse(stale_marker.exists())

    def test_lean_runner_serializes_shared_workspace_without_platform_file_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            fake_lake = temp_root / "race-lake"
            fake_lake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import pathlib",
                        "import sys",
                        "import time",
                        "",
                        "def main() -> int:",
                        "    args = sys.argv[1:]",
                        "    if args[:1] == ['update']:",
                        "        manifest = pathlib.Path.cwd() / 'lake-manifest.json'",
                        "        manifest.write_text('{\"version\": 7}', encoding='utf-8')",
                        "        return 0",
                        "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                        "        generated = pathlib.Path.cwd() / 'FormalizationEngineWorkspace' / 'Generated.lean'",
                        "        text = generated.read_text(encoding='utf-8')",
                        "        time.sleep(0.2)",
                        "        if 'theorem A' in text:",
                        "            print('saw A', file=sys.stderr)",
                        "        elif 'theorem B' in text:",
                        "            print('saw B', file=sys.stderr)",
                        "        else:",
                        "            print('saw ?', file=sys.stderr)",
                        "        return 0",
                        "    print(f'unexpected args: {args}', file=sys.stderr)",
                        "    return 1",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake.chmod(0o755)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            original_fcntl = lean_runner_module.fcntl
            original_msvcrt = lean_runner_module.msvcrt
            lean_runner_module.fcntl = None
            lean_runner_module.msvcrt = None
            try:
                results: dict[str, str] = {}
                failures: list[BaseException] = []

                def run(run_id: str, theorem_name: str) -> None:
                    try:
                        store = RunStore(temp_root / "artifacts", run_id)
                        store.ensure_new()
                        candidate_relative_path = "03_proof/attempts/attempt_0001/candidate.lean"
                        store.write_text(
                            candidate_relative_path,
                            "\n".join(
                                [
                                    "import FormalizationEngineWorkspace.Basic",
                                    "",
                                    f"theorem {theorem_name} : True := by",
                                    "  trivial",
                                    "",
                                ]
                            ),
                        )
                        results[run_id] = runner.compile_candidate(store, candidate_relative_path, 1).stderr
                    except BaseException as exc:  # pragma: no cover - thread failure forwarding
                        failures.append(exc)

                first_thread = threading.Thread(target=run, args=("race-a", "A"))
                second_thread = threading.Thread(target=run, args=("race-b", "B"))
                first_thread.start()
                second_thread.start()
                first_thread.join()
                second_thread.join()
            finally:
                lean_runner_module.fcntl = original_fcntl
                lean_runner_module.msvcrt = original_msvcrt

            self.assertFalse(failures)
            self.assertIn("saw A", results["race-a"])
            self.assertIn("saw B", results["race-b"])

    def test_lean_runner_falls_back_when_flock_is_unsupported(self) -> None:
        class UnsupportedFcntl:
            LOCK_EX = 1
            LOCK_UN = 2

            @staticmethod
            def flock(_fd: int, operation: int) -> None:
                if operation == UnsupportedFcntl.LOCK_EX:
                    raise OSError("operation not supported")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            original_fcntl = lean_runner_module.fcntl
            original_msvcrt = lean_runner_module.msvcrt
            lean_runner_module.fcntl = UnsupportedFcntl()
            lean_runner_module.msvcrt = None
            try:
                store = RunStore(temp_root / "artifacts", "unsupported-flock")
                store.ensure_new()
                candidate_relative_path = "03_proof/attempts/attempt_0001/candidate.lean"
                store.write_text(
                    candidate_relative_path,
                    "\n".join(
                        [
                            "import FormalizationEngineWorkspace.Basic",
                            "",
                            "theorem unsupported_flock (n : Nat) : 0 + n = n := by",
                            "  simpa using Nat.zero_add n",
                            "",
                        ]
                    ),
                )
                result = runner.compile_candidate(store, candidate_relative_path, 1)
            finally:
                lean_runner_module.fcntl = original_fcntl
                lean_runner_module.msvcrt = original_msvcrt

            self.assertTrue(result.passed)

    def test_lean_runner_uses_cross_process_fallback_lock_when_flock_is_unsupported(self) -> None:
        try:
            ctx = multiprocessing.get_context("fork")
        except ValueError:
            self.skipTest("fork multiprocessing is unavailable on this platform")

        class UnsupportedFcntl:
            LOCK_EX = 1
            LOCK_UN = 2

            @staticmethod
            def flock(_fd: int, operation: int) -> None:
                if operation == UnsupportedFcntl.LOCK_EX:
                    raise OSError("operation not supported")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            fake_lake = temp_root / "race-lake"
            fake_lake.write_text(
                "\n".join(
                    [
                        "#!/usr/bin/env python3",
                        "import pathlib",
                        "import sys",
                        "import time",
                        "",
                        "def main() -> int:",
                        "    args = sys.argv[1:]",
                        "    cwd = pathlib.Path.cwd()",
                        "    if args[:1] == ['--version']:",
                        "        print('race-lake')",
                        "        return 0",
                        "    if args[:1] == ['update']:",
                        "        (cwd / 'lake-manifest.json').write_text('{}', encoding='utf-8')",
                        "        return 0",
                        "    if args[:2] == ['build', 'FormalizationEngineWorkspace']:",
                        "        time.sleep(0.3)",
                        "        text = (cwd / 'FormalizationEngineWorkspace' / 'Generated.lean').read_text(encoding='utf-8')",
                        "        if 'theorem A' in text:",
                        "            print('saw A', file=sys.stderr)",
                        "        elif 'theorem B' in text:",
                        "            print('saw B', file=sys.stderr)",
                        "        else:",
                        "            print(text, file=sys.stderr)",
                        "        return 0",
                        "    return 1",
                        "",
                        "if __name__ == '__main__':",
                        "    raise SystemExit(main())",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            fake_lake.chmod(0o755)

            def run(theorem_name: str, queue: multiprocessing.queues.Queue) -> None:
                import lean_formalization_engine.lean_runner as lean_runner_process_module

                lean_runner_process_module.fcntl = UnsupportedFcntl()
                lean_runner_process_module.msvcrt = None
                runner = LeanRunner(
                    temp_root / "lean_workspace_template",
                    repo_root=temp_root,
                    lake_path=str(fake_lake),
                )
                store = RunStore(temp_root / "artifacts", f"race-{theorem_name.lower()}")
                store.ensure_new()
                candidate_relative_path = "03_proof/attempts/attempt_0001/candidate.lean"
                store.write_text(
                    candidate_relative_path,
                    "\n".join(
                        [
                            "import FormalizationEngineWorkspace.Basic",
                            "",
                            f"theorem {theorem_name} : True := by",
                            "  trivial",
                            "",
                        ]
                    ),
                )
                try:
                    result = runner.compile_candidate(store, candidate_relative_path, 1)
                    queue.put((theorem_name, result.stderr, None))
                except BaseException as exc:  # pragma: no cover - process failure forwarding
                    queue.put((theorem_name, "", repr(exc)))

            queue = ctx.Queue()
            first_process = ctx.Process(target=run, args=("A", queue))
            second_process = ctx.Process(target=run, args=("B", queue))
            first_process.start()
            second_process.start()
            first_process.join()
            second_process.join()

            outputs: dict[str, str] = {}
            failures: list[str] = []
            for _ in range(2):
                theorem_name, stderr, failure = queue.get(timeout=1)
                if failure is not None:
                    failures.append(failure)
                else:
                    outputs[theorem_name] = stderr

            self.assertFalse(failures)
            self.assertIn("saw A", outputs["A"])
            self.assertIn("saw B", outputs["B"])

    def test_lean_runner_breaks_stale_fallback_lock(self) -> None:
        class UnsupportedFcntl:
            LOCK_EX = 1
            LOCK_UN = 2

            @staticmethod
            def flock(_fd: int, operation: int) -> None:
                if operation == UnsupportedFcntl.LOCK_EX:
                    raise OSError("operation not supported")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            packaged_template = (
                Path(__file__).resolve().parents[1] / "src" / "lean_formalization_engine" / "workspace_template"
            ).resolve()
            shutil.copytree(packaged_template, temp_root / "lean_workspace_template")
            stale_lock_dir = temp_root / ".terry" / "lean_workspace.lockdir"
            stale_lock_dir.mkdir(parents=True, exist_ok=True)
            (stale_lock_dir / "owner").write_text("999999\n0\n", encoding="utf-8")
            fake_lake = self._write_fake_lake(temp_root)
            runner = LeanRunner(
                temp_root / "lean_workspace_template",
                repo_root=temp_root,
                lake_path=str(fake_lake),
            )

            original_fcntl = lean_runner_module.fcntl
            original_msvcrt = lean_runner_module.msvcrt
            lean_runner_module.fcntl = UnsupportedFcntl()
            lean_runner_module.msvcrt = None
            try:
                store = RunStore(temp_root / "artifacts", "stale-fallback-lock")
                store.ensure_new()
                candidate_relative_path = "03_proof/attempts/attempt_0001/candidate.lean"
                store.write_text(
                    candidate_relative_path,
                    "\n".join(
                        [
                            "import FormalizationEngineWorkspace.Basic",
                            "",
                            "theorem stale_fallback_lock (n : Nat) : 0 + n = n := by",
                            "  simpa using Nat.zero_add n",
                            "",
                        ]
                    ),
                )
                result = runner.compile_candidate(store, candidate_relative_path, 1)
            finally:
                lean_runner_module.fcntl = original_fcntl
                lean_runner_module.msvcrt = original_msvcrt

            self.assertTrue(result.passed)
            self.assertFalse(stale_lock_dir.exists())

    def test_resume_reuses_existing_plan_handoff_after_enrichment_approval(self) -> None:
        class PlanCountingAgent:
            name = "plan_counting_agent"

            def __init__(self) -> None:
                self.plan_calls = 0

            def run_stage(self, request: StageRequest) -> AgentTurn:
                if request.stage == BackendStage.PLAN:
                    self.plan_calls += 1
                raise AssertionError("Resume should reuse the existing plan handoff instead of rerunning the backend.")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "reused-plan"
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "01_enrichment").mkdir(parents=True, exist_ok=True)
            (run_root / "02_plan").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text(
                "For every natural number n, 0 + n = n.\n",
                encoding="utf-8",
            )
            (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")
            (run_root / "01_enrichment" / "review.md").write_text(
                "# Enrichment Review\n\ndecision: approve\n\nNotes:\n\n",
                encoding="utf-8",
            )
            (run_root / "02_plan" / "handoff.md").write_text("# Existing Plan Handoff\n", encoding="utf-8")
            (run_root / "02_plan" / "request.json").write_text('{"stage": "plan"}', encoding="utf-8")
            (run_root / "02_plan" / "prompt.md").write_text("plan prompt", encoding="utf-8")
            (run_root / "02_plan" / "response.txt").write_text("plan response", encoding="utf-8")
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "reused-plan",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "plan_counting_agent",
                        "agent_config": {"backend": "demo"},
                        "template_dir": str((temp_root / "lean_workspace_template").resolve()),
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_enrichment_approval",
                        "attempt_count": 0,
                    }
                ),
                encoding="utf-8",
            )

            agent = PlanCountingAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.resume("reused-plan", auto_approve=False)

            self.assertEqual(agent.plan_calls, 0)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)
            self.assertEqual((run_root / "02_plan" / "handoff.md").read_text(encoding="utf-8"), "# Existing Plan Handoff\n")
            self.assertTrue((run_root / "02_plan" / "checkpoint.md").exists())
            self.assertTrue((run_root / "02_plan" / "review.md").exists())

    def test_resume_reruns_orphaned_plan_turn(self) -> None:
        class FailingPlanAgent:
            name = "failing_plan_agent"

            def __init__(self) -> None:
                self.plan_calls = 0

            def run_stage(self, request: StageRequest) -> AgentTurn:
                output_dir = Path(request.repo_root) / request.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                if request.stage == BackendStage.ENRICHMENT:
                    (output_dir / "handoff.md").write_text("# Enrichment Handoff\n", encoding="utf-8")
                    return AgentTurn({"stage": "enrichment"}, "enrichment prompt", "enrichment response")
                if request.stage == BackendStage.PLAN:
                    self.plan_calls += 1
                    (output_dir / "handoff.md").write_text("# Plan Handoff\n", encoding="utf-8")
                    raise ValueError("plan serialization failed")
                raise AssertionError("Proof should not run while the plan turn is still failing.")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            agent = FailingPlanAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )

            with self.assertRaisesRegex(ValueError, "plan serialization failed"):
                workflow.prove(source_path=source_path, run_id="plan-failure", auto_approve=True)
            self.assertEqual(agent.plan_calls, 1)

            with self.assertRaisesRegex(ValueError, "plan serialization failed"):
                workflow.resume("plan-failure", auto_approve=False)
            self.assertEqual(agent.plan_calls, 2)
            self.assertFalse(
                (temp_root / "artifacts" / "runs" / "plan-failure" / "03_proof" / "attempts" / "attempt_0001").exists()
            )

    def test_resume_reruns_orphaned_proof_turn(self) -> None:
        class FailingProofAgent:
            name = "failing_proof_agent"

            def __init__(self) -> None:
                self.proof_calls = 0

            def run_stage(self, request: StageRequest) -> AgentTurn:
                output_dir = Path(request.repo_root) / request.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                if request.stage == BackendStage.ENRICHMENT:
                    (output_dir / "handoff.md").write_text("# Enrichment Handoff\n", encoding="utf-8")
                    return AgentTurn({"stage": "enrichment"}, "enrichment prompt", "enrichment response")
                if request.stage == BackendStage.PLAN:
                    (output_dir / "handoff.md").write_text("# Plan Handoff\n", encoding="utf-8")
                    return AgentTurn({"stage": "plan"}, "plan prompt", "plan response")
                self.proof_calls += 1
                (output_dir / "candidate.lean").write_text(
                    "\n".join(
                        [
                            "import FormalizationEngineWorkspace.Basic",
                            "",
                            "theorem failed_proof (n : Nat) : 0 + n = n := by",
                            "  sorry",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                raise ValueError("proof serialization failed")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            agent = FailingProofAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )

            with self.assertRaisesRegex(ValueError, "proof serialization failed"):
                workflow.prove(source_path=source_path, run_id="proof-failure", auto_approve=True)
            self.assertEqual(agent.proof_calls, 1)
            run_root = temp_root / "artifacts" / "runs" / "proof-failure"
            self.assertFalse((run_root / "03_proof" / "attempts" / "attempt_0001" / "request.json").exists())

            with self.assertRaisesRegex(ValueError, "proof serialization failed"):
                workflow.resume("proof-failure", auto_approve=False)
            self.assertEqual(agent.proof_calls, 2)
            self.assertFalse((run_root / "03_proof" / "attempts" / "attempt_0001" / "compile_result.json").exists())

    def test_resume_clears_stale_candidate_before_rerunning_proof_turn(self) -> None:
        class CrashingProofAgent:
            name = "crashing_proof_agent"

            def run_stage(self, request: StageRequest) -> AgentTurn:
                output_dir = Path(request.repo_root) / request.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                if request.stage == BackendStage.ENRICHMENT:
                    (output_dir / "handoff.md").write_text("# Enrichment Handoff\n", encoding="utf-8")
                    return AgentTurn({"stage": "enrichment"}, "enrichment prompt", "enrichment response")
                if request.stage == BackendStage.PLAN:
                    (output_dir / "handoff.md").write_text("# Plan Handoff\n", encoding="utf-8")
                    return AgentTurn({"stage": "plan"}, "plan prompt", "plan response")
                (output_dir / "candidate.lean").write_text(
                    "\n".join(
                        [
                            "import FormalizationEngineWorkspace.Basic",
                            "",
                            "theorem failed_proof (n : Nat) : 0 + n = n := by",
                            "  sorry",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                raise ValueError("proof serialization failed")

        class MissingCandidateAgent:
            name = "missing_candidate_agent"

            def run_stage(self, request: StageRequest) -> AgentTurn:
                output_dir = Path(request.repo_root) / request.output_dir
                output_dir.mkdir(parents=True, exist_ok=True)
                if request.stage == BackendStage.ENRICHMENT:
                    (output_dir / "handoff.md").write_text("# Enrichment Handoff\n", encoding="utf-8")
                elif request.stage == BackendStage.PLAN:
                    (output_dir / "handoff.md").write_text("# Plan Handoff\n", encoding="utf-8")
                return AgentTurn({"stage": request.stage.value}, f"{request.stage.value} prompt", f"{request.stage.value} response")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            crashing_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=CrashingProofAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )

            with self.assertRaisesRegex(ValueError, "proof serialization failed"):
                crashing_workflow.prove(source_path=source_path, run_id="proof-stale", auto_approve=True)

            recovery_workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=MissingCandidateAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            with self.assertRaisesRegex(RuntimeError, "attempt_0001/candidate.lean"):
                recovery_workflow.resume("proof-stale", auto_approve=False)

            run_root = temp_root / "artifacts" / "runs" / "proof-stale"
            manifest = recovery_workflow.status("proof-stale")
            self.assertEqual(manifest.attempt_count, 0)
            self.assertFalse((run_root / "03_proof" / "attempts" / "attempt_0001" / "candidate.lean").exists())
            self.assertFalse((run_root / "03_proof" / "attempts" / "attempt_0001" / "compile_result.json").exists())
            self.assertFalse((run_root / "03_proof" / "attempts" / "attempt_0002").exists())

    def test_command_backend_repairs_after_sorry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            provider_script = Path(__file__).resolve().parents[1] / "examples" / "providers" / "scripted_repair_provider.py"
            command = [sys.executable, str(provider_script)]

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=SubprocessFormalizationAgent(command),
                agent_config=AgentConfig(backend="command", command=command),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.prove(source_path=source_path, run_id="command-demo", auto_approve=True)
            run_root = temp_root / "artifacts" / "runs" / "command-demo"

            self.assertEqual(manifest.current_stage, RunStage.COMPLETED)
            self.assertEqual(manifest.attempt_count, 2)
            first_attempt = json.loads(
                (run_root / "03_proof" / "attempts" / "attempt_0001" / "compile_result.json").read_text(
                    encoding="utf-8"
                )
            )
            second_attempt = json.loads(
                (run_root / "03_proof" / "attempts" / "attempt_0002" / "compile_result.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertTrue(first_attempt["contains_sorry"])
            self.assertEqual(first_attempt["status"], "compile_failed")
            self.assertTrue(second_attempt["passed"])

    def test_stage_requests_use_file_paths_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            agent = RecordingRepairAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.prove(source_path=source_path, run_id="recording", auto_approve=False)
            run_root = temp_root / "artifacts" / "runs" / "recording"
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            self._write_review(run_root, "01_enrichment", "approve", "Scope looks right.")
            manifest = workflow.resume("recording", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)

            self._write_review(run_root, "02_plan", "approve", "Start proving.")
            manifest = workflow.resume("recording", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)

            self._write_review(run_root, "03_proof", "retry", "One more attempt.")
            manifest = workflow.resume("recording", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_APPROVAL)

            self.assertEqual(agent.requests[0].stage, BackendStage.ENRICHMENT)
            self.assertEqual(
                set(agent.requests[0].input_paths),
                {"normalized_source", "provenance", "source"},
            )
            self.assertIsNone(agent.requests[0].review_notes_path)

            self.assertEqual(agent.requests[1].stage, BackendStage.PLAN)
            self.assertIn("enrichment_handoff", agent.requests[1].input_paths)
            self.assertIn("enrichment_review", agent.requests[1].input_paths)
            self.assertTrue(agent.requests[1].review_notes_path.endswith("01_enrichment/review.md"))
            self.assertNotIn("extraction", agent.requests[1].input_paths)
            self.assertNotIn("theorem_spec", agent.requests[1].input_paths)

            first_proof = agent.requests[2]
            self.assertEqual(first_proof.stage, BackendStage.PROOF)
            self.assertIn("plan_handoff", first_proof.input_paths)
            self.assertIn("plan_review", first_proof.input_paths)
            self.assertTrue(first_proof.review_notes_path.endswith("02_plan/review.md"))
            self.assertNotIn("plan", first_proof.input_paths)

            retry_proof = agent.requests[-1]
            self.assertEqual(retry_proof.stage, BackendStage.PROOF)
            self.assertIn("previous_compile_result", retry_proof.input_paths)
            self.assertIn("previous_candidate", retry_proof.input_paths)
            self.assertTrue(retry_proof.review_notes_path.endswith("03_proof/review.md"))

    def test_retry_review_file_resets_after_consumption(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=AlwaysSorryAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
                max_attempts=1,
            )
            manifest = workflow.prove(source_path=source_path, run_id="stale-retry", auto_approve=False)
            run_root = temp_root / "artifacts" / "runs" / "stale-retry"
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            self._write_review(run_root, "01_enrichment", "approve", "Scope is fixed.")
            manifest = workflow.resume("stale-retry", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)

            self._write_review(run_root, "02_plan", "approve", "Try once.")
            manifest = workflow.resume("stale-retry", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 1)

            self._write_review(run_root, "03_proof", "retry", "Try one more attempt.")
            manifest = workflow.resume("stale-retry", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 2)

            review_text = (run_root / "03_proof" / "review.md").read_text(encoding="utf-8")
            self.assertIn("decision: pending", review_text)
            self.assertNotIn("decision: retry", review_text)

            manifest = workflow.resume("stale-retry", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)
            self.assertEqual(manifest.attempt_count, 2)

    def test_stage_requests_fall_back_to_legacy_normalized_input(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=RecordingRepairAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            store = RunStore(temp_root / "artifacts", "legacy-normalized")
            store.ensure_new()
            store.write_text("00_input/source.txt", "For every natural number n, 0 + n = n.\n")
            store.write_json("00_input/provenance.json", {})
            store.write_text("01_normalized/normalized.md", "For every natural number n, 0 + n = n.\n")

            manifest = RunManifest(
                run_id="legacy-normalized",
                source=SourceRef(path="input.md", kind=SourceKind.MARKDOWN),
                agent_name="recording_repair_agent",
                agent_config=AgentConfig(backend="demo"),
                template_dir=str((temp_root / "lean_workspace_template").resolve()),
                created_at="2026-04-16T00:00:00Z",
                updated_at="2026-04-16T00:00:00Z",
                current_stage=RunStage.CREATED,
            )

            request = workflow._build_stage_request(
                store,
                manifest,
                stage=BackendStage.ENRICHMENT,
                output_dir="01_enrichment",
                required_outputs=["handoff.md"],
            )

            self.assertTrue(request.input_paths["normalized_source"].endswith("01_normalized/normalized.md"))

    def test_auto_approve_does_not_advertise_missing_review_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            agent = RecordingRepairAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            workflow.prove(source_path=source_path, run_id="auto-approve", auto_approve=True)

            plan_request = agent.requests[1]
            first_proof_request = agent.requests[2]
            self.assertNotIn("enrichment_review", plan_request.input_paths)
            self.assertIsNone(plan_request.review_notes_path)
            self.assertNotIn("plan_review", first_proof_request.input_paths)
            self.assertIsNone(first_proof_request.review_notes_path)

    def test_auto_approve_resume_does_not_pass_pending_review_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            agent = RecordingRepairAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
                max_attempts=1,
            )

            manifest = workflow.prove(source_path=source_path, run_id="auto-approve-resume", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_ENRICHMENT_APPROVAL)

            manifest = workflow.resume("auto-approve-resume", auto_approve=True)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)

            plan_request = agent.requests[1]
            proof_request = agent.requests[2]
            self.assertNotIn("enrichment_review", plan_request.input_paths)
            self.assertIsNone(plan_request.review_notes_path)
            self.assertNotIn("plan_review", proof_request.input_paths)
            self.assertIsNone(proof_request.review_notes_path)

    def test_legacy_auto_approve_does_not_pass_pending_enrichment_review_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-enrichment-auto"
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "03_enrichment").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")
            (run_root / "03_enrichment" / "enrichment_report.approved.json").write_text("{}", encoding="utf-8")
            (run_root / "03_enrichment" / "review.md").write_text(
                "# Legacy Enrichment Review\n\ndecision: pending\n\nNotes:\n\n",
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-enrichment-auto",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "recording_repair_agent",
                        "agent_config": {"backend": "demo"},
                        "template_dir": str((temp_root / "lean_workspace_template").resolve()),
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_enrichment_review",
                        "attempt_count": 0,
                    }
                ),
                encoding="utf-8",
            )

            agent = RecordingRepairAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
                max_attempts=0,
            )
            manifest = workflow.resume("legacy-enrichment-auto", auto_approve=True)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)

            plan_request = agent.requests[0]
            self.assertNotIn("legacy_enrichment_review", plan_request.input_paths)
            self.assertIsNone(plan_request.review_notes_path)

    def test_legacy_auto_approve_does_not_pass_pending_plan_review_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-plan-auto"
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "06_plan").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")
            (run_root / "06_plan" / "formalization_plan.approved.json").write_text("{}", encoding="utf-8")
            (run_root / "06_plan" / "review.md").write_text(
                "# Legacy Plan Review\n\ndecision: pending\n\nNotes:\n\n",
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-plan-auto",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "recording_repair_agent",
                        "agent_config": {"backend": "demo"},
                        "template_dir": str((temp_root / "lean_workspace_template").resolve()),
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_plan_review",
                        "attempt_count": 0,
                    }
                ),
                encoding="utf-8",
            )

            agent = RecordingRepairAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
                max_attempts=1,
            )
            manifest = workflow.resume("legacy-plan-auto", auto_approve=True)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)

            proof_request = agent.requests[0]
            self.assertNotIn("legacy_plan_review", proof_request.input_paths)
            self.assertIsNone(proof_request.review_notes_path)

    def test_legacy_spec_review_stays_legacy_until_plan_is_migrated(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-spec"
            (run_root / "04_spec").mkdir(parents=True, exist_ok=True)
            (run_root / "03_enrichment").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")
            (run_root / "03_enrichment" / "enrichment_report.approved.json").write_text("{}", encoding="utf-8")
            (run_root / "04_spec" / "theorem_spec.approved.json").write_text(
                json.dumps({"title": "Legacy spec", "conclusion": "0 + n = n"}),
                encoding="utf-8",
            )
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-spec",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "recording_repair_agent",
                        "agent_config": {"backend": "demo"},
                        "template_dir": str((temp_root / "lean_workspace_template").resolve()),
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_spec_review",
                        "attempt_count": 0,
                    }
                ),
                encoding="utf-8",
            )

            agent = RecordingRepairAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )

            manifest = workflow.status("legacy-spec")
            self.assertEqual(manifest.current_stage, RunStage.LEGACY_AWAITING_SPEC_REVIEW)

            manifest = workflow.resume("legacy-spec", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.LEGACY_AWAITING_SPEC_REVIEW)
            self.assertTrue((run_root / "04_spec" / "checkpoint.md").exists())
            self.assertTrue((run_root / "04_spec" / "review.md").exists())

            self._write_review(run_root, "04_spec", "approve", "Use the approved legacy spec.")
            manifest = workflow.resume("legacy-spec", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_PLAN_APPROVAL)
            self.assertTrue((run_root / "02_plan" / "handoff.md").exists())
            self.assertIn("legacy_spec", agent.requests[0].input_paths)
            self.assertTrue(agent.requests[0].review_notes_path.endswith("04_spec/review.md"))

    def test_legacy_reject_review_is_not_overwritten_on_pause(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-reject"
            (run_root / "04_spec").mkdir(parents=True, exist_ok=True)
            (run_root / "04_spec" / "theorem_spec.json").write_text("{}", encoding="utf-8")
            original_review = "\n".join(
                [
                    "# Legacy Spec Review",
                    "",
                    "decision: reject",
                    "",
                    "Notes:",
                    "keep these notes",
                    "",
                ]
            )
            (run_root / "04_spec" / "review.md").write_text(original_review, encoding="utf-8")
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-reject",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "demo_zero_add_agent",
                        "agent_config": {"backend": "demo"},
                        "template_dir": str((temp_root / "lean_workspace_template").resolve()),
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_spec_review",
                        "attempt_count": 0,
                    }
                ),
                encoding="utf-8",
            )

            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.resume("legacy-reject", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.LEGACY_AWAITING_SPEC_REVIEW)
            self.assertEqual((run_root / "04_spec" / "review.md").read_text(encoding="utf-8"), original_review)

    def test_legacy_stall_retry_carries_forward_previous_compile_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            run_root = temp_root / "artifacts" / "runs" / "legacy-stall"
            (run_root / "00_input").mkdir(parents=True, exist_ok=True)
            (run_root / "06_plan").mkdir(parents=True, exist_ok=True)
            (run_root / "09_review").mkdir(parents=True, exist_ok=True)
            (run_root / "07_draft" / "attempt_0001").mkdir(parents=True, exist_ok=True)
            (run_root / "08_compile" / "attempt_0001").mkdir(parents=True, exist_ok=True)
            (run_root / "00_input" / "source.txt").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "normalized.md").write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            (run_root / "00_input" / "provenance.json").write_text("{}", encoding="utf-8")
            (run_root / "06_plan" / "formalization_plan.approved.json").write_text("{}", encoding="utf-8")
            (run_root / "09_review" / "review.md").write_text(
                "# Legacy Proof Stall Review\n\ndecision: retry\n\nNotes:\ntry again\n",
                encoding="utf-8",
            )
            (run_root / "07_draft" / "attempt_0001" / "draft.lean").write_text("theorem x : True := by\n  sorry\n", encoding="utf-8")
            (run_root / "08_compile" / "attempt_0001" / "result.json").write_text('{"status":"compile_failed"}', encoding="utf-8")
            (run_root / "manifest.json").write_text(
                json.dumps(
                    {
                        "run_id": "legacy-stall",
                        "source": {"path": "input.md", "kind": "markdown"},
                        "agent_name": "recording_repair_agent",
                        "agent_config": {"backend": "demo"},
                        "template_dir": str((temp_root / "lean_workspace_template").resolve()),
                        "created_at": "2026-04-16T00:00:00Z",
                        "updated_at": "2026-04-16T00:00:00Z",
                        "current_stage": "awaiting_stall_review",
                        "attempt_count": 1,
                    }
                ),
                encoding="utf-8",
            )

            agent = RecordingRepairAgent()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=agent,
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            manifest = workflow.resume("legacy-stall", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.PROOF_BLOCKED)

            proof_request = agent.requests[0]
            self.assertEqual(proof_request.stage, BackendStage.PROOF)
            self.assertIn("legacy_previous_compile_result", proof_request.input_paths)
            self.assertIn("legacy_previous_candidate", proof_request.input_paths)
            self.assertTrue(proof_request.latest_compile_result_path.endswith("08_compile/attempt_0001/result.json"))

    def test_resume_queues_final_review_after_successful_compile_crash(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            runner = ContentCheckingLeanRunner()
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=DemoFormalizationAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=runner,
            )
            workflow.prove(source_path=source_path, run_id="proof-crash", auto_approve=False)
            run_root = temp_root / "artifacts" / "runs" / "proof-crash"
            self._write_review(run_root, "01_enrichment", "approve", "")
            workflow.resume("proof-crash", auto_approve=False)
            self._write_review(run_root, "02_plan", "approve", "")

            store = RunStore(temp_root / "artifacts", "proof-crash")
            manifest = workflow.status("proof-crash")
            request = workflow._build_stage_request(
                store,
                manifest,
                stage=BackendStage.PROOF,
                output_dir="03_proof/attempts/attempt_0001",
                required_outputs=["candidate.lean"],
                review_notes_relative_path="02_plan/review.md",
                attempt=1,
                max_attempts=3,
            )
            workflow._run_backend_stage(store, request, "03_proof/attempts/attempt_0001")
            compile_result = runner.compile_candidate(store, "03_proof/attempts/attempt_0001/candidate.lean", 1)
            workflow._write_compile_result(store, 1, compile_result)
            manifest.current_stage = RunStage.PROVING
            manifest.attempt_count = 1
            manifest.latest_error = None
            workflow._save_manifest(store, manifest)

            manifest = workflow.resume("proof-crash", auto_approve=False)
            self.assertEqual(manifest.current_stage, RunStage.AWAITING_FINAL_APPROVAL)
            self.assertEqual(manifest.attempt_count, 1)
            self.assertTrue((run_root / "04_final" / "final_candidate.lean").exists())

    def test_missing_required_output_raises(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            workflow = FormalizationWorkflow(
                repo_root=temp_root,
                agent=BrokenAgent(),
                agent_config=AgentConfig(backend="demo"),
                lean_runner=ContentCheckingLeanRunner(),
            )
            with self.assertRaisesRegex(RuntimeError, "required Terry output"):
                workflow.prove(source_path=source_path, run_id="broken", auto_approve=False)

    def test_cli_demo_backend_e2e(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            fake_lake = self._write_fake_lake(temp_root)

            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            command = [
                sys.executable,
                "-m",
                "lean_formalization_engine",
                "--repo-root",
                str(temp_root),
                "--lake-path",
                str(fake_lake),
                "prove",
                str(source_path),
                "--run-id",
                "cli-demo",
                "--agent-backend",
                "demo",
                "--auto-approve",
            ]
            result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Stage: completed", result.stdout)
            self.assertTrue((temp_root / "artifacts" / "runs" / "cli-demo" / "04_final" / "final.lean").exists())

    def test_cli_command_backend_e2e(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            source_path = temp_root / "input.md"
            source_path.write_text("For every natural number n, 0 + n = n.\n", encoding="utf-8")
            fake_lake = self._write_fake_lake(temp_root)
            provider_script = Path(__file__).resolve().parents[1] / "examples" / "providers" / "scripted_repair_provider.py"

            env = os.environ.copy()
            env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            command = [
                sys.executable,
                "-m",
                "lean_formalization_engine",
                "--repo-root",
                str(temp_root),
                "--lake-path",
                str(fake_lake),
                "prove",
                str(source_path),
                "--run-id",
                "cli-command",
                "--agent-backend",
                "command",
                "--agent-command",
                f"{sys.executable} {provider_script}",
                "--auto-approve",
            ]
            result = subprocess.run(command, capture_output=True, text=True, env=env, check=False)
            self.assertEqual(result.returncode, 0, msg=result.stderr)
            self.assertIn("Attempts: 2", result.stdout)
            self.assertTrue((temp_root / "artifacts" / "runs" / "cli-command" / "04_final" / "final.lean").exists())
