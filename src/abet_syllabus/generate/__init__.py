"""ABET syllabus document generation."""

from .assembler import SyllabusData, SyllabusTextbook, assemble_syllabus_data
from .docx_generator import generate_docx
from .generator import GenerateResult, generate_program, generate_syllabus
from .pdf_converter import PdfConversionError, convert_to_pdf, is_pdf_available

__all__ = [
    "SyllabusData",
    "SyllabusTextbook",
    "assemble_syllabus_data",
    "generate_docx",
    "GenerateResult",
    "generate_program",
    "generate_syllabus",
    "PdfConversionError",
    "convert_to_pdf",
    "is_pdf_available",
]
