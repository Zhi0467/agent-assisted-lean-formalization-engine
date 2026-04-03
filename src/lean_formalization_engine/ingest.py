from __future__ import annotations

from pathlib import Path

from .models import IngestedSource, SourceRef


def ingest_source(source: SourceRef) -> IngestedSource:
    path = Path(source.path)
    raw_text = _read_source_text(path, source.kind.value)
    normalized_text = _normalize_text(raw_text)
    provenance = {
        "path": str(path),
        "kind": source.kind.value,
        "bytes": path.stat().st_size,
    }
    return IngestedSource(
        raw_text=raw_text,
        normalized_text=normalized_text,
        provenance=provenance,
    )


def _read_source_text(path: Path, kind: str) -> str:
    if kind in {"markdown", "latex"}:
        return path.read_text(encoding="utf-8")
    if kind == "pdf":
        try:
            import fitz  # type: ignore

            doc = fitz.open(path)
            return "\n".join(page.get_text() for page in doc)
        except ImportError:
            try:
                from pypdf import PdfReader  # type: ignore

                reader = PdfReader(str(path))
                return "\n".join(page.extract_text() or "" for page in reader.pages)
            except ImportError as exc:
                raise RuntimeError(
                    "PDF ingestion requires PyMuPDF or pypdf. Install the `pdf` extra."
                ) from exc
    raise ValueError(f"Unsupported source kind: {kind}")


def _normalize_text(raw_text: str) -> str:
    lines = [line.rstrip() for line in raw_text.splitlines()]
    collapsed = []
    previous_blank = False
    for line in lines:
        is_blank = not line.strip()
        if is_blank and previous_blank:
            continue
        collapsed.append(line)
        previous_blank = is_blank
    return "\n".join(collapsed).strip() + "\n"
