"""Tests for the extraction module."""

import os
from pathlib import Path

import pytest

from abet_syllabus.extract import extract_file, extract_folder, ExtractionResult, ExtractedTable
from abet_syllabus.extract.detector import detect_format, is_supported
from abet_syllabus.extract.pdf_extractor import extract_pdf
from abet_syllabus.extract.docx_extractor import extract_docx

# Resolve resource paths relative to the main repo (resources are gitignored
# and live only in the primary checkout, not in the worktree).
_MAIN_REPO = Path(__file__).resolve().parent.parent
# Walk up from worktree to find the main repo resources
_RESOURCES = Path(os.environ.get(
    "ABET_RESOURCES",
    "C:/Users/mmogi/Projects/published_apps/abet-syllabus/resources",
))
_DATA_DIR = _RESOURCES / "course-descriptions" / "data"
_MATH_DIR = _RESOURCES / "course-descriptions" / "math"

_PDF_FILE = _DATA_DIR / "BUS 200 Course Specifications.pdf"
_DOCX_FILE = _MATH_DIR / "CS -Math-101-2024.docx"

# Skip all real-file tests if resources are not available
_HAS_RESOURCES = _PDF_FILE.exists() and _DOCX_FILE.exists()
requires_resources = pytest.mark.skipif(
    not _HAS_RESOURCES,
    reason="Test resource files not found (resources/ is gitignored)",
)


# --- Format detection tests ---


class TestDetector:
    def test_pdf_detected_as_format_a(self, tmp_path):
        pdf = tmp_path / "test.pdf"
        pdf.write_bytes(b"%PDF-1.4 dummy")
        assert detect_format(pdf) == "format_a_pdf"

    def test_docx_detected_as_format_b(self, tmp_path):
        # Create a minimal valid-looking file (just needs the extension)
        docx = tmp_path / "test.docx"
        docx.write_bytes(b"PK dummy")
        assert detect_format(docx) == "format_b_crf2"

    def test_unsupported_extension_raises(self, tmp_path):
        txt = tmp_path / "test.txt"
        txt.write_text("hello")
        with pytest.raises(ValueError, match="Unsupported file extension"):
            detect_format(txt)

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            detect_format("/nonexistent/file.pdf")

    def test_is_supported_pdf(self, tmp_path):
        assert is_supported(tmp_path / "file.pdf")

    def test_is_supported_docx(self, tmp_path):
        assert is_supported(tmp_path / "file.docx")

    def test_is_supported_txt(self, tmp_path):
        assert not is_supported(tmp_path / "file.txt")


# --- PDF extraction tests ---


class TestPdfExtractor:
    @requires_resources
    def test_extract_pdf_returns_result(self):
        result = extract_pdf(_PDF_FILE)
        assert isinstance(result, ExtractionResult)

    @requires_resources
    def test_extract_pdf_raw_text_nonempty(self):
        result = extract_pdf(_PDF_FILE)
        assert len(result.raw_text) > 0

    @requires_resources
    def test_extract_pdf_tables_populated(self):
        result = extract_pdf(_PDF_FILE)
        assert len(result.tables) > 0
        for table in result.tables:
            assert isinstance(table, ExtractedTable)
            assert len(table.rows) > 0

    @requires_resources
    def test_extract_pdf_format_type(self):
        result = extract_pdf(_PDF_FILE)
        assert result.format_type == "format_a_pdf"

    @requires_resources
    def test_extract_pdf_extension(self):
        result = extract_pdf(_PDF_FILE)
        assert result.file_extension == ".pdf"

    @requires_resources
    def test_extract_pdf_metadata(self):
        result = extract_pdf(_PDF_FILE)
        assert "page_count" in result.metadata
        assert result.metadata["page_count"] > 0

    def test_extract_pdf_nonexistent(self):
        with pytest.raises(FileNotFoundError):
            extract_pdf("/nonexistent/file.pdf")


# --- DOCX extraction tests ---


class TestDocxExtractor:
    @requires_resources
    def test_extract_docx_returns_result(self):
        result = extract_docx(_DOCX_FILE)
        assert isinstance(result, ExtractionResult)

    @requires_resources
    def test_extract_docx_raw_text_nonempty(self):
        result = extract_docx(_DOCX_FILE)
        assert len(result.raw_text) > 0

    @requires_resources
    def test_extract_docx_tables_populated(self):
        result = extract_docx(_DOCX_FILE)
        assert len(result.tables) > 0
        for table in result.tables:
            assert isinstance(table, ExtractedTable)
            assert len(table.rows) > 0

    @requires_resources
    def test_extract_docx_format_type(self):
        result = extract_docx(_DOCX_FILE)
        assert result.format_type == "format_b_crf2"

    @requires_resources
    def test_extract_docx_extension(self):
        result = extract_docx(_DOCX_FILE)
        assert result.file_extension == ".docx"

    @requires_resources
    def test_extract_docx_metadata(self):
        result = extract_docx(_DOCX_FILE)
        assert "paragraph_count" in result.metadata
        assert result.metadata["paragraph_count"] > 0

    def test_extract_docx_nonexistent(self):
        with pytest.raises(FileNotFoundError):
            extract_docx("/nonexistent/file.docx")


# --- Dispatcher tests ---


class TestExtractFile:
    @requires_resources
    def test_dispatch_pdf(self):
        result = extract_file(_PDF_FILE)
        assert result.format_type == "format_a_pdf"
        assert len(result.raw_text) > 0

    @requires_resources
    def test_dispatch_docx(self):
        result = extract_file(_DOCX_FILE)
        assert result.format_type == "format_b_crf2"
        assert len(result.raw_text) > 0

    def test_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            extract_file("/nonexistent/file.pdf")

    def test_unsupported_raises(self, tmp_path):
        txt = tmp_path / "test.txt"
        txt.write_text("hello")
        with pytest.raises(ValueError, match="Unsupported file extension"):
            extract_file(txt)


# --- Folder extraction tests ---


class TestExtractFolder:
    @requires_resources
    def test_extract_folder_data(self):
        results = extract_folder(_DATA_DIR)
        assert len(results) > 0
        # Should have both PDFs and DOCXs
        formats = {r.format_type for r in results}
        assert "format_a_pdf" in formats or "format_b_crf2" in formats

    @requires_resources
    def test_extract_folder_recursive(self):
        # Extract from the parent directory recursively
        parent = _RESOURCES / "course-descriptions"
        results = extract_folder(parent, recursive=True)
        assert len(results) > 5  # We know there are 72 files total

    def test_extract_folder_nonexistent(self):
        with pytest.raises(FileNotFoundError):
            extract_folder("/nonexistent/folder")

    def test_extract_folder_not_a_dir(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("hello")
        with pytest.raises(ValueError, match="Not a directory"):
            extract_folder(f)

    def test_extract_folder_empty(self, tmp_path):
        results = extract_folder(tmp_path)
        assert results == []

    def test_extract_folder_skips_unsupported(self, tmp_path):
        # Create an unsupported file
        (tmp_path / "notes.txt").write_text("some notes")
        results = extract_folder(tmp_path)
        assert results == []
