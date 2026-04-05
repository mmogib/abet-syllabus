"""PDF text and table extraction using pdfplumber."""

from __future__ import annotations

from pathlib import Path

import pdfplumber

from abet_syllabus.extract.models import ExtractedTable, ExtractionResult


def extract_pdf(file_path: str | Path) -> ExtractionResult:
    """Extract text and tables from a PDF file.

    Uses pdfplumber to read each page, preserving layout for text
    and extracting structured table data.

    Args:
        file_path: Path to the PDF file.

    Returns:
        ExtractionResult with raw_text, tables, and metadata.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file cannot be read as a PDF.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    page_texts: list[str] = []
    tables: list[ExtractedTable] = []
    table_index = 0

    try:
        with pdfplumber.open(str(path)) as pdf:
            page_count = len(pdf.pages)

            for page in pdf.pages:
                # Extract text preserving layout
                text = page.extract_text() or ""
                page_texts.append(text)

                # Extract tables from this page
                page_tables = page.extract_tables() or []
                for raw_table in page_tables:
                    if not raw_table:
                        continue

                    # Normalize cells: replace None with empty string
                    rows = [
                        [cell if cell is not None else "" for cell in row]
                        for row in raw_table
                        if row is not None
                    ]

                    if not rows:
                        continue

                    header = rows[0] if rows else None
                    tables.append(ExtractedTable(
                        rows=rows,
                        header=header,
                        table_index=table_index,
                    ))
                    table_index += 1
    except Exception as exc:
        raise ValueError(f"Failed to read PDF '{path.name}': {exc}") from exc

    raw_text = "\n\n".join(page_texts)

    return ExtractionResult(
        raw_text=raw_text,
        tables=tables,
        file_path=str(path),
        file_extension=".pdf",
        format_type="format_a_pdf",
        metadata={
            "page_count": page_count,
            "table_count": len(tables),
        },
    )
