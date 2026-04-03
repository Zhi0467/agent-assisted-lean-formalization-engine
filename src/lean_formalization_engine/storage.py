from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from .models import RunManifest, to_jsonable


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class ArtifactStore:
    root: Path

    def initialize_run(self, run_id: str) -> Path:
        run_dir = self.root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        for dirname in [
            "00_input",
            "01_normalized",
            "02_spec",
            "03_plan",
            "04_draft",
            "05_compile",
            "06_final",
        ]:
            (run_dir / dirname).mkdir(exist_ok=True)
        return run_dir

    def write_text(self, run_dir: Path, relative_path: str, content: str) -> Path:
        path = run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def write_json(self, run_dir: Path, relative_path: str, content: Any) -> Path:
        path = run_dir / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(to_jsonable(content), indent=2) + "\n", encoding="utf-8")
        return path

    def write_manifest(self, run_dir: Path, manifest: RunManifest) -> None:
        self.write_json(run_dir, "manifest.json", manifest)

    def append_event(self, run_dir: Path, event_type: str, payload: Dict[str, Any]) -> None:
        path = run_dir / "events.jsonl"
        record = {
            "timestamp": utc_timestamp(),
            "event_type": event_type,
            "payload": to_jsonable(payload),
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
