from __future__ import annotations

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lean_formalization_engine.prompt_loader import (
    load_prompt_template,
    render_bullet_list,
    render_prompt_template,
)

_ALL_TEMPLATES = [
    "codex_common.md",
    "codex_enrichment.md",
    "codex_plan.md",
    "codex_proof.md",
    "codex_review.md",
    "demo_enrichment.md",
    "demo_plan.md",
    "demo_proof.md",
    "demo_review.md",
]


class TestLoadPromptTemplate(unittest.TestCase):
    def test_all_known_templates_exist_and_are_non_empty(self):
        for name in _ALL_TEMPLATES:
            with self.subTest(name=name):
                content = load_prompt_template(name)
                self.assertIsInstance(content, str)
                self.assertGreater(len(content.strip()), 0)

    def test_missing_template_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            load_prompt_template("does_not_exist.md")
        self.assertIn("does_not_exist.md", str(ctx.exception))

    def test_returns_string(self):
        content = load_prompt_template("demo_enrichment.md")
        self.assertIsInstance(content, str)


class TestRenderBulletList(unittest.TestCase):
    def test_empty_iterable_returns_none_bullet(self):
        self.assertEqual(render_bullet_list([]), "- none")

    def test_single_item(self):
        self.assertEqual(render_bullet_list(["foo"]), "- foo")

    def test_multiple_items_joined_with_newlines(self):
        result = render_bullet_list(["a", "b", "c"])
        self.assertEqual(result, "- a\n- b\n- c")

    def test_items_prefixed_with_dash(self):
        result = render_bullet_list(["hello"])
        self.assertTrue(result.startswith("- "))

    def test_generator_input(self):
        result = render_bullet_list(x for x in ["x", "y"])
        self.assertEqual(result, "- x\n- y")

    def test_items_with_spaces(self):
        result = render_bullet_list(["hello world", "foo bar"])
        self.assertIn("- hello world", result)
        self.assertIn("- foo bar", result)


class TestRenderPromptTemplate(unittest.TestCase):
    def test_substitutes_kwargs(self):
        # demo_enrichment.md has {theorem_name} and {output_dir} placeholders
        result = render_prompt_template(
            "demo_enrichment.md",
            theorem_name="zero_add",
            output_dir="/tmp/out",
        )
        self.assertIn("zero_add", result)
        self.assertIn("/tmp/out", result)

    def test_missing_key_raises_key_error(self):
        with self.assertRaises(KeyError):
            # Provide none of the required kwargs
            render_prompt_template("demo_enrichment.md")

    def test_missing_template_raises_file_not_found(self):
        with self.assertRaises(FileNotFoundError):
            render_prompt_template("nonexistent.md", key="value")


if __name__ == "__main__":
    unittest.main()
