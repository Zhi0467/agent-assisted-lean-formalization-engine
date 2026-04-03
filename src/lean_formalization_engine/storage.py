from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import to_jsonable, utc_now


class RunStore:
    def __init__(self, artifacts_root: Path, run_id: str):
        self.artifacts_root = artifacts_root
        self.run_id = run_id
        self.run_root = artifacts_root / "runs" / run_id

    def ensure(self) -> None:
        self.run_root.mkdir(parents=True, exist_ok=True)

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
