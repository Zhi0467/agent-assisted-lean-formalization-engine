from __future__ import annotations

import re
import sys
import unittest
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lean_formalization_engine.models import (
    AgentConfig,
    AgentTurn,
    BackendStage,
    CompileAttempt,
    ReviewDecision,
    RunManifest,
    RunStage,
    SourceKind,
    SourceRef,
    StageRequest,
    to_jsonable,
    utc_now,
)

_ISO8601_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class TestUtcNow(unittest.TestCase):
    def test_format_matches_iso8601_utc(self):
        ts = utc_now()
        self.assertRegex(ts, _ISO8601_UTC)

    def test_ends_with_z(self):
        self.assertTrue(utc_now().endswith("Z"))

    def test_two_calls_are_ordered(self):
        t1 = utc_now()
        t2 = utc_now()
        self.assertLessEqual(t1, t2)


class TestToJsonable(unittest.TestCase):
    def test_none_passthrough(self):
        self.assertIsNone(to_jsonable(None))

    def test_int_passthrough(self):
        self.assertEqual(to_jsonable(42), 42)

    def test_string_passthrough(self):
        self.assertEqual(to_jsonable("hello"), "hello")

    def test_bool_passthrough(self):
        self.assertIs(to_jsonable(True), True)

    def test_path_becomes_string(self):
        result = to_jsonable(Path("/tmp/foo"))
        self.assertIsInstance(result, str)
        self.assertEqual(result, "/tmp/foo")

    def test_enum_becomes_value(self):
        self.assertEqual(to_jsonable(SourceKind.MARKDOWN), "markdown")
        self.assertEqual(to_jsonable(RunStage.CREATED), "created")
        self.assertEqual(to_jsonable(BackendStage.ENRICHMENT), "enrichment")

    def test_list_is_mapped(self):
        result = to_jsonable([SourceKind.PDF, Path("/x")])
        self.assertEqual(result, ["pdf", "/x"])

    def test_dict_keys_become_strings(self):
        result = to_jsonable({1: "a", "b": 2})
        self.assertIn("1", result)
        self.assertIn("b", result)

    def test_dict_values_are_recursed(self):
        result = to_jsonable({"k": SourceKind.LATEX})
        self.assertEqual(result["k"], "latex")

    def test_nested_list_in_dict(self):
        result = to_jsonable({"items": [SourceKind.TEXT, None]})
        self.assertEqual(result["items"], ["text", None])

    def test_dataclass_is_serialized(self):
        ref = SourceRef(path="foo.md", kind=SourceKind.MARKDOWN)
        result = to_jsonable(ref)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["path"], "foo.md")
        self.assertEqual(result["kind"], "markdown")

    def test_nested_dataclass(self):
        config = AgentConfig(backend="codex")
        result = to_jsonable(config)
        self.assertEqual(result["backend"], "codex")
        self.assertIsNone(result["command"])

    def test_custom_enum_value(self):
        class Color(Enum):
            RED = "red"

        self.assertEqual(to_jsonable(Color.RED), "red")

    def test_empty_list(self):
        self.assertEqual(to_jsonable([]), [])

    def test_empty_dict(self):
        self.assertEqual(to_jsonable({}), {})


class TestEnums(unittest.TestCase):
    def test_source_kind_values(self):
        self.assertEqual(SourceKind.MARKDOWN.value, "markdown")
        self.assertEqual(SourceKind.LATEX.value, "latex")
        self.assertEqual(SourceKind.PDF.value, "pdf")
        self.assertEqual(SourceKind.TEXT.value, "text")

    def test_backend_stage_values(self):
        self.assertEqual(BackendStage.ENRICHMENT.value, "enrichment")
        self.assertEqual(BackendStage.PLAN.value, "plan")
        self.assertEqual(BackendStage.PROOF.value, "proof")
        self.assertEqual(BackendStage.REVIEW.value, "review")

    def test_run_stage_completed(self):
        self.assertEqual(RunStage.COMPLETED.value, "completed")

    def test_run_stage_legacy_aliases_exist(self):
        # Verify legacy values are accessible (not removed accidentally)
        self.assertIsNotNone(RunStage.LEGACY_AWAITING_ENRICHMENT_REVIEW)
        self.assertIsNotNone(RunStage.LEGACY_AWAITING_SPEC_REVIEW)
        self.assertIsNotNone(RunStage.LEGACY_AWAITING_PLAN_REVIEW)


if __name__ == "__main__":
    unittest.main()
