from __future__ import annotations

import io
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import pandas as pd
from pypdf import PdfReader

from app_core.models import FileParseResult


SUPPORTED_EXTENSIONS = {".txt", ".md", ".csv", ".xlsx", ".xml", ".pdf"}


def estimate_tokens(text: str, chars_per_token: float) -> int:
    if not text:
        return 0
    return math.ceil(len(text) / max(chars_per_token, 0.1))


def truncate_by_tokens(text: str, token_limit: int, chars_per_token: float) -> str:
    if token_limit <= 0 or not text:
        return ""
    max_chars = max(1, math.floor(token_limit * chars_per_token))
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 19].rstrip() + "\n...[truncated]..."


def discover_supported_files(folder_path: str) -> list[Path]:
    root = Path(folder_path)
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder_path}")

    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS]
    return sorted(files)


def parse_files_from_folder(folder_path: str, chars_per_token: float) -> list[FileParseResult]:
    root = Path(folder_path)
    results: list[FileParseResult] = []
    for file_path in discover_supported_files(folder_path):
        relative_path = file_path.relative_to(root).as_posix()
        results.append(parse_file_from_path(file_path, relative_path, chars_per_token))
    return results


def parse_attachment(filename: str, content: bytes, chars_per_token: float) -> FileParseResult:
    path = Path(filename)
    suffix = path.suffix.lower()
    relative_path = filename
    size_bytes = len(content)

    try:
        if suffix in {".txt", ".md"}:
            text = content.decode("utf-8", errors="replace")
            structure, evidence, metadata = _parse_text_like(text)
        elif suffix == ".csv":
            structure, evidence, metadata = _parse_csv(io.BytesIO(content))
        elif suffix == ".xlsx":
            structure, evidence, metadata = _parse_xlsx(io.BytesIO(content))
        elif suffix == ".xml":
            text = content.decode("utf-8", errors="replace")
            structure, evidence, metadata = _parse_xml(text)
        elif suffix == ".pdf":
            structure, evidence, metadata = _parse_pdf(io.BytesIO(content))
        else:
            raise ValueError(f"Unsupported attachment type: {suffix}")
        parse_status = "ok"
        warnings: list[str] = []
    except Exception as exc:
        structure = "Parsing failed."
        evidence = ""
        metadata = {}
        parse_status = "fail"
        warnings = [str(exc)]

    return _build_result(
        relative_path=relative_path,
        file_type=suffix.lstrip("."),
        size_bytes=size_bytes,
        parse_status=parse_status,
        structure=structure,
        evidence=evidence,
        metadata=metadata,
        warnings=warnings,
        chars_per_token=chars_per_token,
    )


def parse_file_from_path(file_path: Path, relative_path: str, chars_per_token: float) -> FileParseResult:
    suffix = file_path.suffix.lower()
    size_bytes = file_path.stat().st_size

    try:
        if suffix in {".txt", ".md"}:
            text = file_path.read_text(encoding="utf-8", errors="replace")
            structure, evidence, metadata = _parse_text_like(text)
        elif suffix == ".csv":
            structure, evidence, metadata = _parse_csv(file_path)
        elif suffix == ".xlsx":
            structure, evidence, metadata = _parse_xlsx(file_path)
        elif suffix == ".xml":
            text = file_path.read_text(encoding="utf-8", errors="replace")
            structure, evidence, metadata = _parse_xml(text)
        elif suffix == ".pdf":
            structure, evidence, metadata = _parse_pdf(file_path)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")
        parse_status = "ok"
        warnings: list[str] = []
    except Exception as exc:
        structure = "Parsing failed."
        evidence = ""
        metadata = {}
        parse_status = "fail"
        warnings = [str(exc)]

    return _build_result(
        relative_path=relative_path,
        file_type=suffix.lstrip("."),
        size_bytes=size_bytes,
        parse_status=parse_status,
        structure=structure,
        evidence=evidence,
        metadata=metadata,
        warnings=warnings,
        chars_per_token=chars_per_token,
    )


def _build_result(
    *,
    relative_path: str,
    file_type: str,
    size_bytes: int,
    parse_status: str,
    structure: str,
    evidence: str,
    metadata: dict,
    warnings: list[str],
    chars_per_token: float,
) -> FileParseResult:
    return FileParseResult(
        relative_path=relative_path,
        file_type=file_type,
        size_bytes=size_bytes,
        parse_status=parse_status,
        structure_text=structure.strip(),
        evidence_text=evidence.strip(),
        metadata=metadata,
        warnings=warnings,
        tokens_structure_full_est=estimate_tokens(structure, chars_per_token),
        tokens_evidence_full_est=estimate_tokens(evidence, chars_per_token),
        tokens_total_full_est=estimate_tokens(f"{structure}\n{evidence}", chars_per_token),
    )


def _parse_text_like(text: str) -> tuple[str, str, dict]:
    lines = text.splitlines()
    headings = [line.strip() for line in lines if line.strip().startswith(("#", "##", "###"))]
    structure_lines = [
        f"lines: {len(lines)}",
        f"headings_count: {len(headings)}",
    ]
    if headings:
        structure_lines.append("headings:")
        structure_lines.extend(f"- {heading}" for heading in headings[:20])
    else:
        structure_lines.append("headings: none")

    evidence = text.strip()
    metadata = {"line_count": len(lines), "headings": headings[:20]}
    return "\n".join(structure_lines), evidence, metadata


def _parse_csv(source: str | Path | io.BytesIO) -> tuple[str, str, dict]:
    df = pd.read_csv(source)
    return _dataframe_to_structure_and_evidence({"sheet1": df})


def _parse_xlsx(source: str | Path | io.BytesIO) -> tuple[str, str, dict]:
    sheets = pd.read_excel(source, sheet_name=None)
    return _dataframe_to_structure_and_evidence(sheets)


def _dataframe_to_structure_and_evidence(sheets: dict[str, pd.DataFrame]) -> tuple[str, str, dict]:
    structure_parts: list[str] = [f"sheets_count: {len(sheets)}"]
    evidence_parts: list[str] = []
    metadata: dict[str, dict] = {}

    for sheet_name, df in sheets.items():
        metadata[sheet_name] = {
            "rows": int(df.shape[0]),
            "columns": int(df.shape[1]),
            "column_names": [str(col) for col in df.columns.tolist()],
        }
        structure_parts.extend(
            [
                f"sheet: {sheet_name}",
                f"- shape: {df.shape[0]} rows x {df.shape[1]} columns",
                f"- columns: {', '.join(map(str, df.columns.tolist())) or '(none)'}",
                f"- dtypes: {', '.join(f'{col}={dtype}' for col, dtype in df.dtypes.astype(str).items())}",
                f"- empty_cells_est: {int(df.isna().sum().sum())}",
            ]
        )
        sample = df.head(5).fillna("").astype(str)
        evidence_parts.append(f"sheet: {sheet_name}\n{sample.to_csv(index=False).strip()}")

    return "\n".join(structure_parts), "\n\n".join(evidence_parts), metadata


def _parse_xml(text: str) -> tuple[str, str, dict]:
    root = ET.fromstring(text)
    tags: dict[str, int] = {}
    evidence_lines: list[str] = []
    for elem in root.iter():
        tags[elem.tag] = tags.get(elem.tag, 0) + 1
        snippet = (elem.text or "").strip()
        if snippet:
            attrs = " ".join(f'{k}="{v}"' for k, v in elem.attrib.items())
            prefix = f"<{elem.tag}{(' ' + attrs) if attrs else ''}>"
            evidence_lines.append(f"{prefix} {snippet}")

    common_tags = sorted(tags.items(), key=lambda item: (-item[1], item[0]))[:15]
    structure_lines = [
        f"root: {root.tag}",
        "common_tags:",
        *[f"- {tag}: {count}" for tag, count in common_tags],
    ]
    metadata = {"root": root.tag, "common_tags": common_tags}
    return "\n".join(structure_lines), "\n".join(evidence_lines[:50]), metadata


def _parse_pdf(source: str | Path | io.BytesIO) -> tuple[str, str, dict]:
    reader = PdfReader(source)
    pages = []
    for idx, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").strip()
        pages.append({"page": idx, "text": text})

    structure_lines = [
        f"pages: {len(pages)}",
        f"pages_with_text: {sum(1 for page in pages if page['text'])}",
    ]
    evidence_lines = [
        f"PDF_TEXT p.{page['page']}:\n{page['text'] or '(no text extracted)'}"
        for page in pages
    ]
    metadata = {"page_count": len(pages), "included_pages": [page["page"] for page in pages]}
    return "\n".join(structure_lines), "\n\n".join(evidence_lines), metadata
