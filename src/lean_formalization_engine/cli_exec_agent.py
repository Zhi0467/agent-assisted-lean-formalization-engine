from __future__ import annotations

import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from .backend_runtime import ProgressCallback, run_subprocess_with_heartbeat
from .models import AgentTurn, StageRequest, to_jsonable
from .prompt_loader import load_prompt_template, render_bullet_list, render_prompt_template

SUPPORTED_CLI_BACKENDS: frozenset[str] = frozenset({"codex", "claude"})

_DEFAULT_EXECUTABLES: dict[str, str] = {
    "codex": "codex",
    "claude": "claude",
}


class CliExecFormalizationAgent:
    """Drive a Terry stage via an external coding CLI (Codex or Claude)."""

    def __init__(
        self,
        repo_root: Path,
        backend: str = "codex",
        model: str | None = None,
        executable: str | None = None,
        heartbeat_interval_seconds: float = 10.0,
    ):
        if backend not in SUPPORTED_CLI_BACKENDS:
            raise ValueError(
                f"Unsupported CLI backend `{backend}`. "
                f"Expected one of: {sorted(SUPPORTED_CLI_BACKENDS)}."
            )
        self.backend = backend
        self.repo_root = repo_root
        self.model = model
        self.executable = executable or _DEFAULT_EXECUTABLES[backend]
        self.heartbeat_interval_seconds = heartbeat_interval_seconds
        self.name = f"{backend}:{model or 'default'}"

    def run_stage(
        self,
        request: StageRequest,
        progress_callback: ProgressCallback | None = None,
    ) -> AgentTurn:
        prompt = self._build_prompt(request)
        with tempfile.TemporaryDirectory(prefix=f"terry_{self.backend}_stage_") as temp_dir:
            # Keep the coding CLI outside the project tree so Terry workers do not
            # inherit the repo's AGENTS.md or other repo-root instruction files.
            sandbox_root = Path(temp_dir)
            sandbox_request = self._prepare_sandbox_request(sandbox_root, request)
            command = self._build_command(sandbox_root)
            subprocess_cwd = self._subprocess_cwd(sandbox_root)

            try:
                if progress_callback is not None:
                    progress_callback(
                        "backend_process_started",
                        f"Starting {self._display_name()} for `{request.stage.value}`.",
                        {"command": command, "sandbox_root": str(sandbox_root)},
                    )
                execution = run_subprocess_with_heartbeat(
                    command,
                    cwd=subprocess_cwd,
                    input_text=prompt,
                    heartbeat_interval_seconds=self.heartbeat_interval_seconds,
                    progress_callback=progress_callback,
                )
            except FileNotFoundError as exc:
                raise RuntimeError(
                    f"The `{self.executable}` CLI is not available. "
                    f"Install it before running the {self.backend} backend."
                ) from exc

            response = execution.result
            if progress_callback is not None:
                progress_callback(
                    "backend_process_completed",
                    f"{self._display_name()} finished for `{request.stage.value}`.",
                    {
                        "command": command,
                        "elapsed_seconds": execution.elapsed_seconds,
                        "returncode": response.returncode,
                    },
                )
            if response.returncode != 0:
                stderr = response.stderr.strip()
                stdout = response.stdout.strip()
                details = "\n".join(part for part in [stderr, stdout] if part)
                raise RuntimeError(
                    f"{self._display_name()} failed during `{request.stage.value}`."
                    + (f"\n{details}" if details else "")
                )

            self._copy_output_dir_back(sandbox_request)

        raw_response = response.stdout.strip()
        if not raw_response:
            raw_response = response.stderr.strip()
        if not raw_response:
            raw_response = f"{self._display_name()} completed `{request.stage.value}` without a text summary."

        return AgentTurn(
            request_payload=to_jsonable(request),
            prompt=prompt,
            raw_response=raw_response,
        )

    def _build_command(self, sandbox_root: Path) -> list[str]:
        if self.backend == "codex":
            command = [
                self.executable,
                "exec",
                "--ephemeral",
                "--skip-git-repo-check",
                "--dangerously-bypass-approvals-and-sandbox",
                "-C",
                str(sandbox_root),
            ]
            if self.model:
                command.extend(["-m", self.model])
            return command
        if self.backend == "claude":
            command = [
                self.executable,
                "-p",
                "--dangerously-skip-permissions",
            ]
            if self.model:
                command.extend(["--model", self.model])
            return command
        raise ValueError(f"Unsupported CLI backend `{self.backend}`.")

    def _subprocess_cwd(self, sandbox_root: Path) -> Path | None:
        # Codex takes the sandbox root via `-C`; Claude inherits cwd instead.
        if self.backend == "claude":
            return sandbox_root
        return None

    def _display_name(self) -> str:
        return {"codex": "Codex CLI", "claude": "Claude CLI"}.get(
            self.backend, f"{self.backend} CLI"
        )

    def _build_prompt(self, request: StageRequest) -> str:
        stage_inputs = render_bullet_list(f"{name}: {path}" for name, path in sorted(request.input_paths.items()))
        required_outputs = render_bullet_list(f"{request.output_dir}/{path}" for path in request.required_outputs)
        stage_instructions = load_prompt_template(f"stage_{request.stage.value}.md").strip()

        return render_prompt_template(
            "stage_common.md",
            stage=request.stage.value,
            run_dir=request.run_dir,
            output_dir=request.output_dir,
            stage_inputs=stage_inputs,
            required_outputs=required_outputs,
            stale_outputs_section=(
                "\nStale prior outputs from the superseded iteration "
                "(treat them as stale context only; overwrite them if needed):\n"
                + render_bullet_list(request.stale_output_paths)
                + "\n"
                if request.stale_output_paths
                else ""
            ),
            stage_instructions=stage_instructions,
            reviewer_notes_section=(
                f"\nReviewer notes path: {request.review_notes_path}"
                if request.review_notes_path
                else ""
            ),
            latest_compile_section=(
                f"\nLatest compile result path: {request.latest_compile_result_path}"
                if request.latest_compile_result_path
                else ""
            ),
            previous_attempt_section=(
                f"\nPrevious attempt directory: {request.previous_attempt_dir}"
                if request.previous_attempt_dir
                else ""
            ),
            attempt_section=(
                f"\nAttempt: {request.attempt}/{request.max_attempts}"
                if request.attempt is not None and request.max_attempts is not None
                else ""
            ),
        )

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
            raise FileNotFoundError(
                f"Missing Terry stage input `{relative_path}` for the {self.backend} backend."
            )
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


# Backwards-compatible alias so existing imports `from ... import CodexCliFormalizationAgent`
# continue to function. New code should import `CliExecFormalizationAgent` directly.
CodexCliFormalizationAgent = CliExecFormalizationAgent
