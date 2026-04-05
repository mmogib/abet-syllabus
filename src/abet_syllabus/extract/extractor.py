"""Main extraction entry point — dispatches to format-specific extractors."""

from __future__ import annotations

import sys
from pathlib import Path

from abet_syllabus.extract.detector import detect_format, is_supported
from abet_syllabus.extract.docx_extractor import extract_docx
from abet_syllabus.extract.models import ExtractionResult
from abet_syllabus.extract.pdf_extractor import extract_pdf

# Map format type strings to extractor functions
_EXTRACTORS = {
    "format_a_pdf": extract_pdf,
    "format_b_crf2": extract_docx,
}


def extract_file(file_path: str | Path) -> ExtractionResult:
    """Extract text and tables from a single course specification file.

    Detects the format based on file extension and delegates to the
    appropriate extractor.

    Args:
        file_path: Path to a PDF or DOCX file.

    Returns:
        ExtractionResult with raw text, tables, and metadata.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file type is unsupported or the file is corrupt.
    """
    path = Path(file_path).resolve()
    fmt = detect_format(path)
    extractor = _EXTRACTORS[fmt]
    return extractor(path)


def extract_folder(
    folder_path: str | Path,
    *,
    recursive: bool = False,
) -> list[ExtractionResult]:
    """Extract text and tables from all supported files in a folder.

    Args:
        folder_path: Path to a directory containing PDF/DOCX files.
        recursive: If True, search subdirectories as well.

    Returns:
        List of ExtractionResult objects, one per successfully processed file.
        Files that fail extraction are skipped with a warning printed to stderr.

    Raises:
        FileNotFoundError: If the folder does not exist.
        ValueError: If the path is not a directory.
    """
    folder = Path(folder_path).resolve()
    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder}")
    if not folder.is_dir():
        raise ValueError(f"Not a directory: {folder}")

    # Collect all supported files
    pattern = "**/*" if recursive else "*"
    files = sorted(
        p for p in folder.glob(pattern)
        if p.is_file() and is_supported(p)
    )

    results: list[ExtractionResult] = []
    for file_path in files:
        try:
            result = extract_file(file_path)
            results.append(result)
        except Exception as exc:
            print(f"Warning: skipping '{file_path.name}': {exc}", file=sys.stderr)

    return results
