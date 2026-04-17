from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from .models import AgentTurn, StageRequest, to_jsonable


class CodexCliFormalizationAgent:
    """Use `codex exec` as a live Terry backend."""

    def __init__(
        self,
        repo_root: Path,
        model: str | None = None,
        executable: str = "codex",
    ):
        self.repo_root = repo_root
        self.model = model
        self.executable = executable
        self.name = f"codex_cli:{model or 'default'}"

    def run_stage(self, request: StageRequest) -> AgentTurn:
        prompt = self._build_prompt(request)
        with tempfile.TemporaryDirectory(prefix="terry_codex_stage_") as temp_dir:
            sandbox_root = Path(temp_dir)
            sandbox_request = self._prepare_sandbox_request(sandbox_root, request)
            command = [
                self.executable,
                "exec",
                "--ephemeral",
                "--skip-git-repo-check",
                "-C",
                str(sandbox_root),
                "-s",
                "workspace-write",
            ]
            if self.model:
                command.extend(["-m", self.model])

            try:
                response = subprocess.run(
                    command,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    check=False,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    "The `codex` CLI is not available. Install it before running the Codex backend."
                ) from exc

            if response.returncode != 0:
                stderr = response.stderr.strip()
                stdout = response.stdout.strip()
                details = "\n".join(part for part in [stderr, stdout] if part)
                raise RuntimeError(
                    f"Codex exec failed during `{request.stage.value}`."
                    + (f"\n{details}" if details else "")
                )

            self._copy_output_dir_back(sandbox_request)

        raw_response = response.stdout.strip()
        if not raw_response:
            raw_response = response.stderr.strip()
        if not raw_response:
            raw_response = f"Codex completed `{request.stage.value}` without a text summary."

        return AgentTurn(
            request_payload=to_jsonable(request),
            prompt=prompt,
            raw_response=raw_response,
        )

    def _build_prompt(self, request: StageRequest) -> str:
        lines = [
            "You are the backend for Terry, a Lean 4 formalization workflow.",
            "Terry is only the orchestrator. Do the theorem work through files.",
            "",
            f"Stage: {request.stage.value}",
            "Repo root: current working directory",
            f"Run directory: {request.run_dir}",
            f"Output directory: {request.output_dir}",
            "",
            "Read the listed input files from disk and write the required output files into the output directory.",
            "Do not edit files outside the output directory.",
            "",
            "Stage inputs:",
        ]
        for name, path in sorted(request.input_paths.items()):
            lines.append(f"- {name}: {path}")

        lines.extend(
            [
                "",
                "Required outputs:",
            ]
        )
        for path in request.required_outputs:
            lines.append(f"- {request.output_dir}/{path}")

        if request.review_notes_path:
            lines.extend(
                [
                    "",
                    f"Reviewer notes path: {request.review_notes_path}",
                ]
            )

        if request.latest_compile_result_path:
            lines.extend(
                [
                    f"Latest compile result path: {request.latest_compile_result_path}",
                ]
            )

        if request.previous_attempt_dir:
            lines.extend(
                [
                    f"Previous attempt directory: {request.previous_attempt_dir}",
                ]
            )

        if request.attempt is not None and request.max_attempts is not None:
            lines.extend(
                [
                    f"Attempt: {request.attempt}/{request.max_attempts}",
                ]
            )

        lines.extend(
            [
                "",
                "When you are done, reply with a brief plain-text note describing what you wrote.",
            ]
        )
        return "\n".join(lines)

    def _prepare_sandbox_request(self, sandbox_root: Path, request: StageRequest) -> StageRequest:
        sandbox_root.mkdir(parents=True, exist_ok=True)
        relative_inputs = set(request.input_paths.values())
        if request.review_notes_path:
            relative_inputs.add(request.review_notes_path)
        if request.latest_compile_result_path:
            relative_inputs.add(request.latest_compile_result_path)
        if request.previous_attempt_dir:
            relative_inputs.add(request.previous_attempt_dir)

        for relative_path in sorted(relative_inputs):
            self._copy_relative_path_into_sandbox(sandbox_root, relative_path)

        (sandbox_root / request.output_dir).mkdir(parents=True, exist_ok=True)
        return replace(request, repo_root=str(sandbox_root.resolve()))

    def _copy_relative_path_into_sandbox(self, sandbox_root: Path, relative_path: str) -> None:
        source = self.repo_root / relative_path
        destination = sandbox_root / relative_path
        if not source.exists():
            raise FileNotFoundError(f"Missing Terry stage input `{relative_path}` for Codex.")
        if source.is_dir():
            shutil.copytree(source, destination, dirs_exist_ok=True)
            return
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    def _copy_output_dir_back(self, request: StageRequest) -> None:
        sandbox_output_dir = Path(request.repo_root) / request.output_dir
        real_output_dir = self.repo_root / request.output_dir
        if not sandbox_output_dir.exists():
            return
        shutil.copytree(sandbox_output_dir, real_output_dir, dirs_exist_ok=True)
