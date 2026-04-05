"""Main parser entry point — dispatches to format-specific parsers.

Usage::

    from abet_syllabus.parse import parse_file, parse_extraction

    # Parse a file (extract + parse in one step)
    course = parse_file("path/to/course.pdf")

    # Parse from an already-extracted result
    result = extract_file("path/to/course.docx")
    course = parse_extraction(result)
"""

from __future__ import annotations

import sys
from pathlib import Path

from abet_syllabus.extract import extract_file, extract_folder
from abet_syllabus.extract.models import ExtractionResult
from abet_syllabus.parse.format_a_parser import parse_format_a
from abet_syllabus.parse.format_b_parser import parse_format_b
from abet_syllabus.parse.models import ParsedCourse

# Map format type strings to parser functions
_PARSERS = {
    "format_a_pdf": parse_format_a,
    "format_b_crf2": parse_format_b,
}


def parse_extraction(result: ExtractionResult) -> ParsedCourse:
    """Parse an already-extracted result into a ParsedCourse.

    Dispatches to the appropriate format-specific parser based on
    ``result.format_type``.

    Args:
        result: ExtractionResult from the extraction module.

    Returns:
        ParsedCourse with all extracted fields populated.

    Raises:
        ValueError: If the format type is unknown.
    """
    parser = _PARSERS.get(result.format_type)
    if parser is None:
        raise ValueError(
            f"Unknown format type '{result.format_type}'. "
            f"Supported: {', '.join(sorted(_PARSERS.keys()))}"
        )
    return parser(result)


def parse_file(file_path: str | Path) -> ParsedCourse:
    """Extract and parse a single course specification file.

    Combines extraction and parsing in one step.

    Args:
        file_path: Path to a PDF or DOCX file.

    Returns:
        ParsedCourse with all extracted fields populated.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file type is unsupported.
    """
    result = extract_file(file_path)
    return parse_extraction(result)


def parse_folder(
    folder_path: str | Path,
    *,
    recursive: bool = False,
) -> list[ParsedCourse]:
    """Extract and parse all supported files in a folder.

    Args:
        folder_path: Path to a directory containing PDF/DOCX files.
        recursive: If True, search subdirectories as well.

    Returns:
        List of ParsedCourse objects, one per successfully processed file.
        Files that fail are skipped with a warning printed to stderr.
    """
    results = extract_folder(folder_path, recursive=recursive)
    courses: list[ParsedCourse] = []
    for result in results:
        try:
            course = parse_extraction(result)
            courses.append(course)
        except (ValueError, OSError) as exc:
            name = Path(result.file_path).name
            print(f"Warning: parsing failed for '{name}': {exc}", file=sys.stderr)
    return courses
