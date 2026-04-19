from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lean_formalization_engine.template_manager import (
    _extract_mathlib_rev,
    _replace_mathlib_rev,
)


class TestTemplateManagerVersionPins(unittest.TestCase):
    def test_extract_mathlib_rev_returns_revision_for_mathlib_block(self):
        lakefile_text = """name = "workspace"
[[require]]
name = "mathlib"
scope = "leanprover-community"
rev = "abc123"
"""

        self.assertEqual(_extract_mathlib_rev(lakefile_text), "abc123")

    def test_extract_mathlib_rev_returns_none_when_mathlib_missing(self):
        lakefile_text = """name = "workspace"
[[require]]
name = "other"
rev = "zzz"
"""

        self.assertIsNone(_extract_mathlib_rev(lakefile_text))

    def test_replace_mathlib_rev_preserves_neighboring_require_blocks(self):
        lakefile_text = """name = "workspace"
[[require]]
name = "mathlib"
scope = "leanprover-community"
rev = "abc123"
[[require]]
name = "std"
scope = "leanprover"
rev = "keep-me"
"""

        updated = _replace_mathlib_rev(lakefile_text, "newrev")

        self.assertIn('rev = "newrev"\n[[require]]', updated)
        self.assertEqual(_extract_mathlib_rev(updated), "newrev")
        self.assertIn('name = "std"', updated)
        self.assertIn('rev = "keep-me"', updated)


if __name__ == "__main__":
    unittest.main()
