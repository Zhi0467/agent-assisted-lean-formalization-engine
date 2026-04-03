from __future__ import annotations

from pathlib import Path

from .models import IngestedSource, SourceKind, SourceRef


def detect_source_kind(source_path: Path) -> SourceKind:
    suffix = source_path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return SourceKind.MARKDOWN
    if suffix in {".tex", ".latex"}:
        return SourceKind.LATEX
    if suffix == ".pdf":
        return SourceKind.PDF
    return SourceKind.TEXT


def ingest_source(source_path: Path) -> tuple[SourceRef, IngestedSource]:
    kind = detect_source_kind(source_path)
    source_ref = SourceRef(path=str(source_path), kind=kind)

    if kind == SourceKind.PDF:
        raw_text, extraction_method = _extract_pdf_text(source_path)
    else:
        raw_text = source_path.read_text(encoding="utf-8")
        extraction_method = "plain_text"

    normalized = _normalize_text(raw_text)
    return source_ref, IngestedSource(
        raw_text=raw_text,
        normalized_text=normalized,
        extraction_method=extraction_method,
    )


def _extract_pdf_text(source_path: Path) -> tuple[str, str]:
    try:
        import fitz  # type: ignore

        document = fitz.open(source_path)
        return "\n".join(page.get_text() for page in document), "pymupdf"
    except ImportError:
        pass

    try:
        from pypdf import PdfReader  # type: ignore

        reader = PdfReader(str(source_path))
        return "\n".join(page.extract_text() or "" for page in reader.pages), "pypdf"
    except ImportError as exc:
        raise RuntimeError(
            "PDF ingestion requires either PyMuPDF or pypdf. "
            "Install with `python3 -m pip install -e '.[pdf]'`."
        ) from exc


def _normalize_text(raw_text: str) -> str:
    lines = [line.rstrip() for line in raw_text.splitlines()]
    compact_lines: list[str] = []
    blank_streak = 0
    for line in lines:
        if line:
            blank_streak = 0
            compact_lines.append(line)
            continue
        blank_streak += 1
        if blank_streak <= 1:
            compact_lines.append("")
    return "\n".join(compact_lines).strip() + "\n"
