from __future__ import annotations

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
        if lake_path is None:
            return CompileAttempt(
                attempt=attempt,
                command=["lake", "build", "FormalizationEngineWorkspace"],
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
        stdout = f"$ {' '.join(build_command)}\n{build_result.stdout}"
        stderr = f"$ {' '.join(build_command)}\n{build_result.stderr}"

        self._cleanup_workspace(workspace)
        return CompileAttempt(
            attempt=attempt,
            command=[" ".join(build_command)],
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
        workspace = store.path("workspace")
        if workspace.exists():
            shutil.rmtree(workspace)
        shutil.copytree(self.template_dir, workspace)
        return workspace

    def _cleanup_workspace(self, workspace: Path) -> None:
        shutil.rmtree(workspace / ".lake", ignore_errors=True)
        shutil.rmtree(workspace / "build", ignore_errors=True)

    def _resolve_lake(self) -> str | None:
        if self.lake_path:
            return self.lake_path

        candidate = shutil.which("lake")
        if candidate:
            return candidate

        elan_candidate = Path.home() / ".elan" / "bin" / "lake"
        if elan_candidate.exists():
            return str(elan_candidate)
        return None


def _extract_diagnostics(stderr: str) -> list[str]:
    return [line.strip() for line in stderr.splitlines() if line.strip()][-10:]
