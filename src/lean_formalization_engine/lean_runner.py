from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List

from .models import CompileAttempt, LeanDraft


class LeanRunner:
    def __init__(self, template_root: Path) -> None:
        self.template_root = template_root

    def compile_draft(self, run_dir: Path, draft: LeanDraft, attempt: int) -> CompileAttempt:
        compile_dir = run_dir / "05_compile" / f"attempt_{attempt:04d}"
        workspace_dir = compile_dir / "workspace"
        if workspace_dir.exists():
            shutil.rmtree(workspace_dir)
        shutil.copytree(self.template_root, workspace_dir)
        draft_path = workspace_dir / "FormalizationEngineWorkspace" / "Draft.lean"
        draft_path.write_text(draft.code, encoding="utf-8")

        if shutil.which("lake") is None:
            return CompileAttempt(
                attempt=attempt,
                command=[],
                returncode=127,
                passed=False,
                stdout="",
                stderr="Lean toolchain is not available on PATH.",
                diagnostics=["Missing `lake` executable."],
                missing_toolchain=True,
                quality_gate_passed=False,
            )

        command = [
            "zsh",
            "-lc",
            'source "$HOME/.elan/env" && lake build FormalizationEngineWorkspace',
        ]
        completed = subprocess.run(command, cwd=workspace_dir, capture_output=True, text=True)
        diagnostics = _extract_diagnostics(completed.stderr)
        quality_gate_passed = "sorry" not in draft.code
        return CompileAttempt(
            attempt=attempt,
            command=command,
            returncode=completed.returncode,
            passed=completed.returncode == 0,
            stdout=completed.stdout,
            stderr=completed.stderr,
            diagnostics=diagnostics,
            missing_toolchain=False,
            quality_gate_passed=quality_gate_passed,
        )


def _extract_diagnostics(stderr: str) -> List[str]:
    lines = [line.strip() for line in stderr.splitlines() if line.strip()]
    return lines[-10:]
