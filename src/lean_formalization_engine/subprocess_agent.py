from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .backend_runtime import ProgressCallback, run_subprocess_with_heartbeat
from .models import AgentTurn, StageRequest, to_jsonable


class ProviderResponseError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        response_text: str = "",
        provider_payload: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.response_text = response_text
        self.provider_payload = provider_payload


class SubprocessFormalizationAgent:
    """Delegate Terry stages to an external command over stdin/stdout."""

    def __init__(
        self,
        command: list[str],
        name: str | None = None,
        working_directory: Path | None = None,
        heartbeat_interval_seconds: float = 10.0,
    ):
        if not command:
            raise ValueError("SubprocessFormalizationAgent requires a non-empty command.")
        self.command = command
        self.name = name or _default_agent_name(command)
        self.working_directory = working_directory
        self.heartbeat_interval_seconds = heartbeat_interval_seconds

    def run_stage(
        self,
        request: StageRequest,
        progress_callback: ProgressCallback | None = None,
    ) -> AgentTurn:
        request_payload = to_jsonable(request)
        provider_payload = self._invoke_provider(
            request_payload,
            stage_label=request.stage.value,
            progress_callback=progress_callback,
        )
        if not isinstance(provider_payload, dict):
            raise ProviderResponseError(
                f"Provider returned a non-object response during `{request.stage.value}`.",
                response_text=json.dumps(provider_payload),
            )

        prompt = provider_payload.get("prompt")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ProviderResponseError(
                f"Provider omitted `prompt` during `{request.stage.value}`.",
                provider_payload=provider_payload,
            )

        raw_response = provider_payload.get("raw_response")
        if not isinstance(raw_response, str):
            raw_response = json.dumps(provider_payload, indent=2, sort_keys=True)

        return AgentTurn(
            request_payload=request_payload,
            prompt=prompt,
            raw_response=raw_response,
        )

    def _invoke_provider(
        self,
        payload: dict[str, Any],
        *,
        stage_label: str,
        progress_callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        try:
            if progress_callback is not None:
                progress_callback(
                    "backend_process_started",
                    f"Starting provider command for `{stage_label}`.",
                    {"command": self.command},
                )
            execution = run_subprocess_with_heartbeat(
                self.command,
                cwd=self.working_directory,
                input_text=json.dumps(payload),
                heartbeat_interval_seconds=self.heartbeat_interval_seconds,
                progress_callback=progress_callback,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                f"Provider command `{self.command[0]}` is not available for `{stage_label}`."
            ) from exc

        response = execution.result
        if progress_callback is not None:
            progress_callback(
                "backend_process_completed",
                f"Provider command finished for `{stage_label}`.",
                {
                    "command": self.command,
                    "elapsed_seconds": execution.elapsed_seconds,
                    "returncode": response.returncode,
                },
            )
        if response.returncode != 0:
            stderr = response.stderr.strip()
            stdout = response.stdout.strip()
            details = "\n".join(part for part in [stderr, stdout] if part)
            raise RuntimeError(
                f"Provider command exited with code {response.returncode} during `{stage_label}`."
                + (f"\n{details}" if details else "")
            )

        try:
            provider_payload = json.loads(response.stdout)
        except json.JSONDecodeError as exc:
            raise ProviderResponseError(
                f"Provider returned invalid JSON during `{stage_label}`.",
                response_text=response.stdout.strip(),
            ) from exc

        return provider_payload


def _default_agent_name(command: list[str]) -> str:
    executable_name = Path(command[0]).name
    if executable_name.startswith("python") and len(command) > 1:
        if command[1] == "-m" and len(command) > 2:
            return f"subprocess:{command[2]}"
        if command[1] == "-c":
            return "subprocess:python-inline"
        return f"subprocess:{Path(command[1]).name}"
    return f"subprocess:{executable_name}"
