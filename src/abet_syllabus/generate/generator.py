"""Main entry point for ABET syllabus generation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from abet_syllabus.db import repository as repo
from abet_syllabus.db.schema import init_db

from .assembler import assemble_syllabus_data
from .docx_generator import generate_docx
from .pdf_converter import PdfConversionError, convert_to_pdf, is_pdf_available

logger = logging.getLogger(__name__)


@dataclass
class GenerateResult:
    """Result of generating a single syllabus."""
    course_code: str
    docx_path: str | None
    pdf_path: str | None
    status: str       # "success" / "error"
    message: str


def _make_output_filename(
    course_code: str,
    term: str | None,
) -> str:
    """Build the output filename stem: {term}_{course_code}_ABET_Syllabus.

    Spaces in course code are replaced with underscores.
    """
    code_part = course_code.replace(" ", "_")
    if term:
        return f"{term}_{code_part}_ABET_Syllabus"
    return f"{code_part}_ABET_Syllabus"


def generate_syllabus(
    db_path: str | Path,
    course_code: str,
    program_code: str | None = None,
    term: str | None = None,
    instructor: str | None = None,
    template_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    pdf: bool = True,
) -> GenerateResult:
    """Generate ABET syllabus for a single course.

    Args:
        db_path: Path to the SQLite database.
        course_code: Course code (e.g. "MATH 101").
        program_code: Optional program code for CLO-SO mappings.
        term: Optional term code (e.g. "T252").
        instructor: Optional instructor name.
        template_path: Path to the DOCX template. Defaults to
            resources/templates/ABETSyllabusTemplate.docx.
        output_dir: Output directory. Defaults to current directory.
        pdf: Whether to also generate PDF output.

    Returns:
        GenerateResult with paths and status.
    """
    # Resolve template path
    if template_path is None:
        template_path = _find_default_template()
    template_path = Path(template_path)

    # Resolve output directory
    if output_dir is None:
        output_dir = Path.cwd()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Build output paths
    stem = _make_output_filename(course_code, term)
    docx_path = output_dir / f"{stem}.docx"

    try:
        # Assemble data
        data = assemble_syllabus_data(
            db_path=db_path,
            course_code=course_code,
            program_code=program_code,
            term=term,
            instructor=instructor,
        )

        # Generate DOCX
        generate_docx(data, template_path, docx_path)

        # Generate PDF if requested
        pdf_out = None
        pdf_msg = ""
        if pdf:
            pdf_file = output_dir / f"{stem}.pdf"
            if is_pdf_available():
                try:
                    convert_to_pdf(docx_path, pdf_file)
                    pdf_out = str(pdf_file)
                except PdfConversionError as exc:
                    pdf_msg = f" (PDF skipped: {exc})"
            else:
                pdf_msg = " (PDF skipped: no converter available)"

        msg = f"Generated {docx_path.name}"
        if pdf_out:
            msg += f" and {Path(pdf_out).name}"
        msg += pdf_msg

        return GenerateResult(
            course_code=course_code,
            docx_path=str(docx_path),
            pdf_path=pdf_out,
            status="success",
            message=msg,
        )

    except Exception as exc:
        logger.exception("Failed to generate syllabus for %s", course_code)
        return GenerateResult(
            course_code=course_code,
            docx_path=None,
            pdf_path=None,
            status="error",
            message=str(exc),
        )


def generate_program(
    db_path: str | Path,
    program_code: str,
    term: str | None = None,
    template_path: str | Path | None = None,
    output_dir: str | Path | None = None,
    pdf: bool = True,
) -> list[GenerateResult]:
    """Generate syllabi for all courses in a program.

    Args:
        db_path: Path to the SQLite database.
        program_code: Program code (e.g. "MATH").
        term: Optional term code.
        template_path: Path to the DOCX template.
        output_dir: Output directory.
        pdf: Whether to also generate PDF.

    Returns:
        List of GenerateResult, one per course.
    """
    conn = init_db(str(db_path))
    try:
        courses = repo.get_all_courses(conn, program_code=program_code)
    finally:
        conn.close()

    if not courses:
        return [GenerateResult(
            course_code="",
            docx_path=None,
            pdf_path=None,
            status="error",
            message=f"No courses found for program: {program_code}",
        )]

    results = []
    for course in courses:
        result = generate_syllabus(
            db_path=db_path,
            course_code=course.course_code,
            program_code=program_code,
            term=term,
            template_path=template_path,
            output_dir=output_dir,
            pdf=pdf,
        )
        results.append(result)

    return results


def _find_default_template() -> Path:
    """Locate the default template file.

    Searches in order:
    1. resources/templates/ABETSyllabusTemplate.docx (relative to cwd)
    2. Bundled inside the installed package
    """
    template_name = "ABETSyllabusTemplate.docx"

    # Try relative to cwd
    cwd_template = Path("resources/templates") / template_name
    if cwd_template.exists():
        return cwd_template

    # Try bundled template inside the package
    pkg_template = Path(__file__).resolve().parent.parent / "templates" / template_name
    if pkg_template.exists():
        return pkg_template

    raise FileNotFoundError(
        "Default template not found. Provide --template path or ensure "
        "resources/templates/ABETSyllabusTemplate.docx exists."
    )
