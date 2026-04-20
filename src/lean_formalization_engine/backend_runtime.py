from __future__ import annotations

import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

ProgressCallback = Callable[[str, str, Optional[dict[str, Any]]], None]

_TRANSIENT_BACKEND_ERROR_FRAGMENTS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "connection aborted",
    "connection closed",
    "connection refused",
    "connection reset",
    "dns",
    "econnaborted",
    "econnrefused",
    "econnreset",
    "host unreachable",
    "internal server error",
    "name or service not known",
    "network",
    "rate limit",
    "server busy",
    "temporary failure in name resolution",
    "temporarily unavailable",
    "timed out",
    "timeout",
    "tlsv1 alert internal error",
    "transport error",
    "try again",
)


@dataclass(frozen=True)
class SubprocessExecution:
    result: subprocess.CompletedProcess[str]
    elapsed_seconds: float


def is_transient_backend_failure(message: str) -> bool:
    lowered = message.lower()
    return any(fragment in lowered for fragment in _TRANSIENT_BACKEND_ERROR_FRAGMENTS)


def run_subprocess_with_heartbeat(
    command: list[str],
    *,
    input_text: str | None = None,
    cwd: Path | None = None,
    heartbeat_interval_seconds: float = 10.0,
    progress_callback: ProgressCallback | None = None,
) -> SubprocessExecution:
    start_time = time.monotonic()
    state: dict[str, object] = {}

    def _target() -> None:
        try:
            state["result"] = subprocess.run(
                command,
                cwd=cwd,
                input=input_text,
                capture_output=True,
                text=True,
                check=False,
            )
        except BaseException as exc:  # pragma: no cover - exercised through callers
            state["error"] = exc

    worker = threading.Thread(target=_target, daemon=True)
    worker.start()
    heartbeat_count = 0

    while worker.is_alive():
        worker.join(timeout=max(heartbeat_interval_seconds, 0.01))
        if worker.is_alive() and progress_callback is not None:
            heartbeat_count += 1
            elapsed_seconds = round(time.monotonic() - start_time, 1)
            progress_callback(
                "backend_process_heartbeat",
                f"Backend subprocess is still running after {elapsed_seconds:.1f}s.",
                {
                    "command": command,
                    "elapsed_seconds": elapsed_seconds,
                    "heartbeat_count": heartbeat_count,
                },
            )

    elapsed_seconds = round(time.monotonic() - start_time, 3)
    error = state.get("error")
    if error is not None:
        raise error  # type: ignore[misc]

    result = state.get("result")
    if not isinstance(result, subprocess.CompletedProcess):  # pragma: no cover - defensive
        raise RuntimeError("Backend subprocess did not return a result.")
    return SubprocessExecution(result=result, elapsed_seconds=elapsed_seconds)
