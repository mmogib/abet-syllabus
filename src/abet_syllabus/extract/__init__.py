"""Extraction module — reads PDF and DOCX course specification files."""

from abet_syllabus.extract.extractor import extract_file, extract_folder
from abet_syllabus.extract.models import ExtractedTable, ExtractionResult

__all__ = [
    "extract_file",
    "extract_folder",
    "ExtractedTable",
    "ExtractionResult",
]
