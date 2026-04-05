"""Data models for the extraction module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExtractedTable:
    """A single table extracted from a document.

    Attributes:
        rows: List of rows, each row is a list of cell strings.
        header: Optional header row (first row of the table).
        table_index: Position of this table in the document (0-based).
    """

    rows: list[list[str]] = field(default_factory=list)
    header: list[str] | None = None
    table_index: int | None = None


@dataclass
class ExtractionResult:
    """Complete extraction result from a single file.

    Attributes:
        raw_text: Full text content extracted from the document.
        tables: All tables found in the document.
        file_path: Absolute path to the source file.
        file_extension: File extension (e.g., ".pdf", ".docx").
        format_type: Detected format ("format_a_pdf" or "format_b_crf2").
        metadata: Additional extraction metadata (page count, etc.).
    """

    raw_text: str = ""
    tables: list[ExtractedTable] = field(default_factory=list)
    file_path: str = ""
    file_extension: str = ""
    format_type: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
