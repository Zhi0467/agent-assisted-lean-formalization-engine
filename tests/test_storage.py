from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lean_formalization_engine.storage import RunStore, validate_run_id


class TestValidateRunId(unittest.TestCase):
    def test_valid_alphanumeric(self):
        self.assertEqual(validate_run_id("abc123"), "abc123")

    def test_valid_with_hyphens_dots_underscores(self):
        self.assertEqual(validate_run_id("run-2026.04_18"), "run-2026.04_18")

    def test_single_character(self):
        self.assertEqual(validate_run_id("x"), "x")

    def test_empty_string_raises(self):
        with self.assertRaises(ValueError):
            validate_run_id("")

    def test_leading_hyphen_raises(self):
        with self.assertRaises(ValueError):
            validate_run_id("-bad")

    def test_leading_dot_raises(self):
        with self.assertRaises(ValueError):
            validate_run_id(".bad")

    def test_space_raises(self):
        with self.assertRaises(ValueError):
            validate_run_id("bad id")

    def test_slash_raises(self):
        with self.assertRaises(ValueError):
            validate_run_id("bad/id")

    def test_newline_raises(self):
        with self.assertRaises(ValueError):
            validate_run_id("bad\nid")

    def test_returns_same_string(self):
        run_id = "my-run_001"
        self.assertIs(validate_run_id(run_id), run_id)


class TestRunStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.artifacts_root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _store(self, run_id: str = "test-run-001") -> RunStore:
        return RunStore(self.artifacts_root, run_id)

    def test_ensure_creates_run_root(self):
        store = self._store()
        store.ensure()
        self.assertTrue(store.run_root.is_dir())

    def test_ensure_new_creates_run_root(self):
        store = self._store()
        store.ensure_new()
        self.assertTrue(store.run_root.is_dir())

    def test_ensure_new_raises_if_already_exists(self):
        store = self._store()
        store.ensure_new()
        with self.assertRaises(FileExistsError) as ctx:
            store.ensure_new()
        self.assertIn("test-run-001", str(ctx.exception))

    def test_ensure_is_idempotent(self):
        store = self._store()
        store.ensure()
        store.ensure()  # should not raise

    def test_write_and_read_text(self):
        store = self._store()
        store.ensure()
        store.write_text("sub/file.txt", "hello world\n")
        self.assertEqual(store.read_text("sub/file.txt"), "hello world\n")

    def test_write_text_creates_parent_dirs(self):
        store = self._store()
        store.ensure()
        store.write_text("deep/nested/file.txt", "content")
        self.assertTrue(store.path("deep/nested/file.txt").exists())

    def test_write_and_read_json_roundtrip(self):
        store = self._store()
        store.ensure()
        payload = {"key": "value", "num": 42, "nested": {"a": [1, 2]}}
        store.write_json("data.json", payload)
        result = store.read_json("data.json")
        self.assertEqual(result["key"], "value")
        self.assertEqual(result["num"], 42)
        self.assertEqual(result["nested"]["a"], [1, 2])

    def test_write_json_is_valid_json_on_disk(self):
        store = self._store()
        store.ensure()
        store.write_json("out.json", {"x": 1})
        raw = store.path("out.json").read_text(encoding="utf-8")
        parsed = json.loads(raw)
        self.assertEqual(parsed["x"], 1)

    def test_exists_returns_false_for_missing_file(self):
        store = self._store()
        store.ensure()
        self.assertFalse(store.exists("nonexistent.txt"))

    def test_exists_returns_true_after_write(self):
        store = self._store()
        store.ensure()
        store.write_text("present.txt", "hi")
        self.assertTrue(store.exists("present.txt"))

    def test_path_resolves_under_run_root(self):
        store = self._store()
        store.ensure()
        p = store.path("foo/bar.txt")
        self.assertEqual(p, store.run_root / "foo" / "bar.txt")

    def test_invalid_run_id_rejected_at_construction(self):
        with self.assertRaises(ValueError):
            RunStore(self.artifacts_root, "bad id!")


class TestAppendLog(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = RunStore(Path(self._tmp.name), "log-test-run")
        self.store.ensure()

    def tearDown(self):
        self._tmp.cleanup()

    def test_append_log_creates_jsonl(self):
        self.store.append_log("test_event", "something happened")
        log_path = self.store.path("logs/workflow.jsonl")
        self.assertTrue(log_path.exists())

    def test_append_log_jsonl_entry_is_valid_json(self):
        self.store.append_log("test_event", "hello")
        lines = self.store.path("logs/workflow.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["event_type"], "test_event")
        self.assertEqual(entry["summary"], "hello")

    def test_append_log_creates_timeline_md(self):
        self.store.append_log("test_event", "something happened")
        timeline = self.store.path("logs/timeline.md")
        self.assertTrue(timeline.exists())
        content = timeline.read_text(encoding="utf-8")
        self.assertIn("test_event", content)
        self.assertIn("something happened", content)

    def test_append_log_stage_suffix_in_timeline(self):
        self.store.append_log("transition", "moved to proving", stage="proving")
        content = self.store.path("logs/timeline.md").read_text(encoding="utf-8")
        self.assertIn("[proving]", content)

    def test_append_log_no_stage_omits_suffix(self):
        self.store.append_log("start", "run started")
        content = self.store.path("logs/timeline.md").read_text(encoding="utf-8")
        self.assertNotIn("[None]", content)

    def test_append_log_multiple_entries_accumulate(self):
        self.store.append_log("ev1", "first")
        self.store.append_log("ev2", "second")
        lines = self.store.path("logs/workflow.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["event_type"], "ev1")
        self.assertEqual(json.loads(lines[1])["event_type"], "ev2")

    def test_append_log_details_serialized(self):
        self.store.append_log("ev", "detail test", details={"count": 3})
        entry = json.loads(
            self.store.path("logs/workflow.jsonl").read_text(encoding="utf-8").splitlines()[0]
        )
        self.assertEqual(entry["details"]["count"], 3)


if __name__ == "__main__":
    unittest.main()
