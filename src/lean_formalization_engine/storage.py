from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import to_jsonable, utc_now

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def validate_run_id(run_id: str) -> str:
    if not _SAFE_RUN_ID.fullmatch(run_id):
        raise ValueError(
            "Run IDs must be a single safe path segment containing only letters, "
            "numbers, dots, underscores, or hyphens."
        )
    return run_id


class RunStore:
    def __init__(self, artifacts_root: Path, run_id: str):
        self.artifacts_root = artifacts_root
        self.run_id = validate_run_id(run_id)
        self.run_root = artifacts_root / "runs" / self.run_id

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

    def write_json(self, relative_path: str, payload: Any) -> Path:
        destination = self.path(relative_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(to_jsonable(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return destination

    def read_json(self, relative_path: str) -> Any:
        return json.loads(self.path(relative_path).read_text(encoding="utf-8"))

    def exists(self, relative_path: str) -> bool:
        return self.path(relative_path).exists()

    def append_event(self, event_type: str, payload: dict[str, Any]) -> None:
        events_path = self.path("events.jsonl")
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(
                    {
                        "event_type": event_type,
                        "timestamp": utc_now(),
                        "payload": to_jsonable(payload),
                    },
                    sort_keys=True,
                )
                + "\n"
            )
