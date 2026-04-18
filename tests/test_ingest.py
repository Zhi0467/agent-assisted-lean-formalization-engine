from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from lean_formalization_engine.ingest import (
    _display_path,
    _normalize_text,
    detect_source_kind,
    ingest_source,
)
from lean_formalization_engine.models import SourceKind


class TestDetectSourceKind(unittest.TestCase):
    def test_md_extension(self):
        self.assertEqual(detect_source_kind(Path("theorem.md")), SourceKind.MARKDOWN)

    def test_markdown_extension(self):
        self.assertEqual(detect_source_kind(Path("theorem.markdown")), SourceKind.MARKDOWN)

    def test_tex_extension(self):
        self.assertEqual(detect_source_kind(Path("paper.tex")), SourceKind.LATEX)

    def test_latex_extension(self):
        self.assertEqual(detect_source_kind(Path("paper.latex")), SourceKind.LATEX)

    def test_pdf_extension(self):
        self.assertEqual(detect_source_kind(Path("paper.pdf")), SourceKind.PDF)

    def test_lean_extension_returns_text(self):
        self.assertEqual(detect_source_kind(Path("proof.lean")), SourceKind.TEXT)

    def test_txt_extension_returns_text(self):
        self.assertEqual(detect_source_kind(Path("notes.txt")), SourceKind.TEXT)

    def test_no_extension_returns_text(self):
        self.assertEqual(detect_source_kind(Path("README")), SourceKind.TEXT)

    def test_uppercase_md_extension(self):
        self.assertEqual(detect_source_kind(Path("doc.MD")), SourceKind.MARKDOWN)

    def test_uppercase_pdf_extension(self):
        self.assertEqual(detect_source_kind(Path("doc.PDF")), SourceKind.PDF)

    def test_uppercase_tex_extension(self):
        self.assertEqual(detect_source_kind(Path("doc.TEX")), SourceKind.LATEX)


class TestNormalizeText(unittest.TestCase):
    def test_strips_trailing_whitespace_per_line(self):
        result = _normalize_text("hello   \nworld  \n")
        self.assertEqual(result.splitlines()[0], "hello")
        self.assertEqual(result.splitlines()[1], "world")

    def test_collapses_multiple_blank_lines_to_one(self):
        result = _normalize_text("a\n\n\n\nb\n")
        self.assertNotIn("\n\n\n", result)
        self.assertIn("\n\n", result)
        self.assertIn("a", result)
        self.assertIn("b", result)

    def test_always_ends_with_newline(self):
        self.assertTrue(_normalize_text("hello").endswith("\n"))
        self.assertTrue(_normalize_text("hello\nworld").endswith("\n"))

    def test_strips_leading_blank_lines(self):
        result = _normalize_text("\n\nhello\n")
        self.assertFalse(result.startswith("\n"))
        self.assertTrue(result.startswith("hello"))

    def test_empty_string_returns_newline(self):
        self.assertEqual(_normalize_text(""), "\n")

    def test_only_blank_lines_returns_newline(self):
        self.assertEqual(_normalize_text("\n\n\n"), "\n")

    def test_single_line_no_trailing_whitespace(self):
        result = _normalize_text("hello")
        self.assertEqual(result, "hello\n")

    def test_preserves_single_blank_line_between_paragraphs(self):
        result = _normalize_text("para1\n\npara2\n")
        self.assertIn("para1\n\npara2", result)


class TestDisplayPath(unittest.TestCase):
    def test_path_inside_repo_root_returns_relative(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            file = root / "subdir" / "file.md"
            result = _display_path(file, root)
            self.assertEqual(result, str(Path("subdir") / "file.md"))

    def test_path_outside_repo_root_returns_absolute(self):
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            root = Path(tmp1)
            file = Path(tmp2) / "file.md"
            result = _display_path(file, root)
            self.assertIn(tmp2, result)
            self.assertTrue(Path(result).is_absolute())

    def test_none_repo_root_returns_absolute(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "file.md"
            result = _display_path(file, None)
            self.assertTrue(Path(result).is_absolute())


class TestIngestSource(unittest.TestCase):
    def _write_temp(self, suffix: str, content: str) -> Path:
        f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False, encoding="utf-8")
        f.write(content)
        f.close()
        return Path(f.name)

    def test_ingest_plain_text_file(self):
        path = self._write_temp(".lean", "theorem foo : True := trivial\n")
        try:
            source_ref, ingested = ingest_source(path)
            self.assertEqual(source_ref.kind, SourceKind.TEXT)
            self.assertIn("theorem foo", ingested.raw_text)
            self.assertEqual(ingested.extraction_method, "plain_text")
            self.assertTrue(ingested.normalized_text.endswith("\n"))
        finally:
            path.unlink()

    def test_ingest_markdown_file(self):
        path = self._write_temp(".md", "# Theorem\nFor all n, n + 0 = n.\n")
        try:
            source_ref, ingested = ingest_source(path)
            self.assertEqual(source_ref.kind, SourceKind.MARKDOWN)
            self.assertEqual(ingested.extraction_method, "plain_text")
        finally:
            path.unlink()

    def test_ingest_latex_file(self):
        path = self._write_temp(".tex", r"\begin{theorem}n+0=n\end{theorem}" + "\n")
        try:
            source_ref, ingested = ingest_source(path)
            self.assertEqual(source_ref.kind, SourceKind.LATEX)
        finally:
            path.unlink()

    def test_display_path_relative_to_repo_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "sub" / "input.md"
            path.parent.mkdir(parents=True)
            path.write_text("hello\n", encoding="utf-8")
            source_ref, _ = ingest_source(path, repo_root=root)
            self.assertEqual(source_ref.path, str(Path("sub") / "input.md"))

    def test_raw_text_preserved_verbatim(self):
        content = "line one   \n\n\nline two\n"
        path = self._write_temp(".txt", content)
        try:
            _, ingested = ingest_source(path)
            self.assertEqual(ingested.raw_text, content)
        finally:
            path.unlink()


class TestExtractPdfTextFallback(unittest.TestCase):
    def test_raises_runtime_error_when_no_pdf_library_available(self):
        from lean_formalization_engine.ingest import _extract_pdf_text

        with patch.dict(sys.modules, {"fitz": None, "pypdf": None}):
            with self.assertRaises(RuntimeError) as ctx:
                _extract_pdf_text(Path("dummy.pdf"))

        msg = str(ctx.exception)
        self.assertIn("PyMuPDF", msg)
        self.assertIn("pypdf", msg)


if __name__ == "__main__":
    unittest.main()
