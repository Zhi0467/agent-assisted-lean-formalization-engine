from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .models import CompileAttempt, LeanDraft
from .storage import RunStore


class LeanRunner:
    def __init__(self, template_dir: Path, lake_path: str | None = None):
        self.template_dir = template_dir
        self.lake_path = lake_path

    def compile_draft(self, store: RunStore, draft: LeanDraft, attempt: int) -> CompileAttempt:
        workspace = self._prepare_workspace(store)
        generated_path = workspace / "FormalizationEngineWorkspace" / "Generated.lean"
        generated_path.write_text(draft.content, encoding="utf-8")

        lake_path = self._resolve_lake()
        display_command = [
            self._display_lake(),
            "build",
            "FormalizationEngineWorkspace",
        ]
        if lake_path is None:
            return CompileAttempt(
                attempt=attempt,
                command=[" ".join(display_command)],
                stdout="",
                stderr="Lean toolchain is not available on PATH and ~/.elan/bin/lake was not found.",
                returncode=127,
                diagnostics=["Missing `lake` executable."],
                fast_check_passed=False,
                build_passed=False,
                contains_sorry="sorry" in draft.content,
                missing_toolchain=True,
                quality_gate_passed=False,
                passed=False,
                status="toolchain_missing",
            )

        build_command = [lake_path, "build", "FormalizationEngineWorkspace"]
        build_result = subprocess.run(
            build_command,
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )

        contains_sorry = "sorry" in draft.content
        fast_check_passed = build_result.returncode == 0
        build_passed = build_result.returncode == 0
        quality_gate_passed = not contains_sorry
        passed = fast_check_passed and build_passed and quality_gate_passed
        display_command_text = " ".join(display_command)
        stdout = (
            f"$ {display_command_text}\n"
            f"{self._sanitize_output(build_result.stdout, store, workspace, lake_path)}"
        )
        stderr = (
            f"$ {display_command_text}\n"
            f"{self._sanitize_output(build_result.stderr, store, workspace, lake_path)}"
        )

        self._cleanup_workspace(workspace)
        return CompileAttempt(
            attempt=attempt,
            command=[display_command_text],
            stdout=stdout,
            stderr=stderr,
            returncode=0 if passed else build_result.returncode,
            diagnostics=_extract_diagnostics(stderr),
            fast_check_passed=fast_check_passed,
            build_passed=build_passed,
            contains_sorry=contains_sorry,
            missing_toolchain=False,
            quality_gate_passed=quality_gate_passed,
            passed=passed,
            status="passed" if passed else "compile_failed",
        )

    def _prepare_workspace(self, store: RunStore) -> Path:
        workspace = store.path("03_proof/workspace")
        if workspace.exists():
            shutil.rmtree(workspace)
        shutil.copytree(
            self.template_dir,
            workspace,
            ignore=shutil.ignore_patterns(".git", ".lake", "build", "lake-manifest.json"),
        )
        return workspace

    def _cleanup_workspace(self, workspace: Path) -> None:
        shutil.rmtree(workspace / ".lake", ignore_errors=True)
        shutil.rmtree(workspace / "build", ignore_errors=True)
        (workspace / "lake-manifest.json").unlink(missing_ok=True)

    def _resolve_lake(self) -> str | None:
        if self.lake_path:
            configured = shutil.which(self.lake_path)
            if configured:
                return configured

            configured_path = Path(self.lake_path).expanduser()
            if configured_path.exists() and os.access(configured_path, os.X_OK):
                return str(configured_path)
            return None

        candidate = shutil.which("lake")
        if candidate:
            return candidate

        elan_candidate = Path.home() / ".elan" / "bin" / "lake"
        if elan_candidate.exists():
            return str(elan_candidate)
        return None

    def _display_lake(self) -> str:
        if self.lake_path:
            configured = Path(self.lake_path).expanduser()
            if configured.is_absolute() or "/" in self.lake_path:
                return configured.name
            return self.lake_path
        return "lake"

    def _sanitize_output(
        self,
        content: str,
        store: RunStore,
        workspace: Path,
        lake_path: str,
    ) -> str:
        run_root_display = f"artifacts/runs/{store.run_id}"
        sanitized = content.replace(str(workspace), f"{run_root_display}/03_proof/workspace")
        sanitized = sanitized.replace(str(store.run_root), run_root_display)
        sanitized = sanitized.replace(lake_path, self._display_lake())
        sanitized = sanitized.replace(str(Path.home()), "~")
        return sanitized


def _extract_diagnostics(stderr: str) -> list[str]:
    return [line.strip() for line in stderr.splitlines() if line.strip()][-10:]
