from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from .models import to_jsonable, utc_now

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

_PERSISTED_LOG_SKIP_EVENTS: frozenset[str] = frozenset({"backend_process_heartbeat"})


def validate_run_id(run_id: str) -> str:
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError(
            "Run IDs must be a single safe path segment containing only letters, "
            "numbers, dots, underscores, or hyphens."
        )
    return run_id


class RunStore:
    def __init__(
        self,
        artifacts_root: Path,
        run_id: str,
        event_sink: Callable[[dict[str, Any]], None] | None = None,
    ):
        self.artifacts_root = artifacts_root
        self.run_id = validate_run_id(run_id)
        self.run_root = artifacts_root / "runs" / self.run_id
        self.event_sink = event_sink

    def ensure(self) -> None:
        self.run_root.mkdir(parents=True, exist_ok=True)

    def ensure_new(self) -> None:
        if self.run_root.exists():
            raise FileExistsError(
                f"Run ID `{self.run_id}` already exists under artifacts/runs."
            )
        self.run_root.mkdir(parents=True, exist_ok=False)

    def path(self, relative_path: str) -> Path:
        return self.run_root / relative_path

    def write_text(self, relative_path: str, content: str) -> Path:
        destination = self.path(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")
        return destination

    def read_text(self, relative_path: str) -> str:
        return self.path(relative_path).read_text(encoding="utf-8")

    def write_json(self, relative_path: str, payload: Any) -> Path:
        destination = self.path(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(to_jsonable(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination

    def read_json(self, relative_path: str) -> Any:
        return json.loads(self.read_text(relative_path))

    def exists(self, relative_path: str) -> bool:
        return self.path(relative_path).exists()

    def append_log(
        self,
        event_type: str,
        summary: str,
        *,
        stage: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "timestamp": utc_now(),
            "event_type": event_type,
            "summary": summary,
            "stage": stage,
            "details": to_jsonable(details or {}),
        }
        if event_type not in _PERSISTED_LOG_SKIP_EVENTS:
            log_path = self.path("logs/workflow.jsonl")
            log_path.parent.mkdir(parents=True, exist_ok=True)
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")

            timeline_path = self.path("logs/timeline.md")
            timeline_path.parent.mkdir(parents=True, exist_ok=True)
            stage_suffix = f" [{stage}]" if stage else ""
            with timeline_path.open("a", encoding="utf-8") as handle:
                detail_suffix = _timeline_detail_suffix(payload["details"])
                handle.write(
                    f"- {payload['timestamp']} | `{event_type}`{stage_suffix} | {summary}{detail_suffix}\n"
                )
        if self.event_sink is not None:
            self.event_sink(payload)


def _timeline_detail_suffix(details: dict[str, Any]) -> str:
    if not details:
        return ""
    rendered_items = []
    for key, value in sorted(details.items()):
        rendered_items.append(f"{key}={json.dumps(value, sort_keys=True)}")
    return " | " + ", ".join(rendered_items)
