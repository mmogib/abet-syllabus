"""Ingestion pipeline — extract, parse, and store course specifications.

Wires together the extract, parse, and db layers into a single pipeline
that processes course specification files into the SQLite database.

Usage::

    from abet_syllabus.ingest import ingest_file, ingest_folder, ingest_plos

    # Process a single file
    result = ingest_file("path/to/course.pdf", "abet_syllabus.db")

    # Process a folder
    results = ingest_folder("resources/course-descriptions/", "abet_syllabus.db", recursive=True)

    # Load PLO definitions
    count = ingest_plos("resources/plos/plos.csv", "abet_syllabus.db")
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

from abet_syllabus.db import repository as repo
from abet_syllabus.db.models import (
    Course,
    CourseAssessment,
    CourseClo,
    CourseTextbook,
    CourseTopic,
    CreditCategorization,
    Program,
)
from abet_syllabus.db.schema import init_db
from abet_syllabus.extract import extract_file
from abet_syllabus.extract.detector import is_supported
from abet_syllabus.parse import parse_extraction
from abet_syllabus.parse.models import ParsedCourse as ParsedCourseData

logger = logging.getLogger(__name__)


@dataclass
class IngestResult:
    """Result of ingesting a single file."""

    file_path: str
    file_name: str
    course_code: str | None
    status: str  # "success" / "skipped" / "error"
    message: str  # details
    unmatched_plo_codes: set[str] = field(default_factory=set)


def _map_parsed_to_db(parsed: ParsedCourseData) -> Course:
    """Map a ParsedCourse from the parse layer to a DB Course model."""
    return Course(
        course_code=parsed.course_code or "",
        course_title=parsed.course_title or "",
        department=parsed.department or "",
        college=parsed.college or "",
        catalog_description=parsed.catalog_description or "",
        credit_hours_raw=parsed.credit_hours_raw or "",
        lecture_credits=parsed.lecture_credits or 0,
        lab_credits=parsed.lab_credits or 0,
        total_credits=parsed.total_credits or 0,
        course_type=parsed.course_type or "",
        level=parsed.level or "",
        prerequisites=parsed.prerequisites or "",
        corequisites=parsed.corequisites or "",
    )


def _map_clos(parsed: ParsedCourseData) -> list[CourseClo]:
    """Map parsed CLOs to DB CourseClo models."""
    return [
        CourseClo(
            clo_code=clo.clo_code,
            clo_category=clo.clo_category,
            clo_text=clo.clo_text,
            teaching_strategy=clo.teaching_strategy or "",
            assessment_method=clo.assessment_method or "",
            sequence=clo.sequence,
        )
        for clo in parsed.clos
    ]


def _map_topics(parsed: ParsedCourseData) -> list[CourseTopic]:
    """Map parsed topics to DB CourseTopic models."""
    return [
        CourseTopic(
            topic_number=topic.topic_number,
            topic_title=topic.topic_title,
            contact_hours=topic.contact_hours,
            topic_type=topic.topic_type,
            sequence=i + 1,
        )
        for i, topic in enumerate(parsed.topics)
    ]


def _map_textbooks(parsed: ParsedCourseData) -> list[CourseTextbook]:
    """Map parsed textbooks to DB CourseTextbook models."""
    return [
        CourseTextbook(
            textbook_text=tb.textbook_text,
            textbook_type=tb.textbook_type,
            sequence=i + 1,
        )
        for i, tb in enumerate(parsed.textbooks)
    ]


def _map_assessments(parsed: ParsedCourseData) -> list[CourseAssessment]:
    """Map parsed assessments to DB CourseAssessment models."""
    return [
        CourseAssessment(
            assessment_task=a.assessment_task,
            week_due=a.week_due or "",
            proportion=a.proportion or 0.0,
            assessment_type=a.assessment_type,
            sequence=i + 1,
        )
        for i, a in enumerate(parsed.assessments)
    ]


def ingest_file(
    file_path: str | Path,
    db_path: str | Path,
    program: str | None = None,
    force: bool = False,
) -> IngestResult:
    """Extract, parse, and store a single file.

    Steps:
        1. Compute file hash (SHA-256) for deduplication
        2. Check if already processed (by hash)
        3. Extract (extract_file)
        4. Parse (parse_extraction)
        5. Map ParsedCourse fields to DB models
        6. Store in DB via Repository
        7. Record in source_files table
        8. Return result with status

    Args:
        file_path: Path to a PDF or DOCX file.
        db_path: Path to the SQLite database.
        program: Optional program code (e.g., "MATH") to tag the course.

    Returns:
        IngestResult with status and details.
    """
    path = Path(file_path).resolve()
    file_name = path.name

    if not path.exists():
        return IngestResult(
            file_path=str(path),
            file_name=file_name,
            course_code=None,
            status="error",
            message=f"File not found: {path}",
        )

    if not path.is_file():
        return IngestResult(
            file_path=str(path),
            file_name=file_name,
            course_code=None,
            status="error",
            message=f"Not a file: {path}",
        )

    conn = init_db(db_path)
    try:
        # 1. Compute file hash for deduplication
        content_hash = repo.file_hash(path)

        # 2. Check if already processed (skip if force=True)
        if not force:
            existing = repo.get_source_file_by_hash(conn, content_hash)
            if existing is not None:
                return IngestResult(
                    file_path=str(path),
                    file_name=file_name,
                    course_code=None,
                    status="skipped",
                    message="File already processed (duplicate hash)",
                )

        # 3. Extract
        extraction = extract_file(path)

        # 4. Parse
        parsed = parse_extraction(extraction)

        if not parsed.course_code:
            return IngestResult(
                file_path=str(path),
                file_name=file_name,
                course_code=None,
                status="error",
                message="Could not extract course code from file",
            )

        # 5. Map to DB models
        course = _map_parsed_to_db(parsed)
        clos = _map_clos(parsed)
        topics = _map_topics(parsed)
        textbooks = _map_textbooks(parsed)
        assessments = _map_assessments(parsed)

        # 6. Store in DB
        course_id = repo.upsert_course(conn, course)
        # When force-ingesting, preserve existing CLO-PLO mappings
        if force:
            clo_ids = repo.replace_course_clos_preserving_mappings(conn, course_id, clos)
        else:
            clo_ids = repo.replace_course_clos(conn, course_id, clos)
        repo.replace_course_topics(conn, course_id, topics)
        repo.replace_course_textbooks(conn, course_id, textbooks)
        repo.replace_course_assessment(conn, course_id, assessments)

        # Store credit categorization if extracted
        if parsed.credit_categorization:
            cc = CreditCategorization(
                course_id=course_id,
                engineering_cs=parsed.credit_categorization.get("engineering_cs", 0.0),
                math_science=parsed.credit_categorization.get("math_science", 0.0),
                humanities=parsed.credit_categorization.get("humanities", 0.0),
                social_sciences_business=parsed.credit_categorization.get("social_sciences_business", 0.0),
                general_education=parsed.credit_categorization.get("general_education", 0.0),
                other=parsed.credit_categorization.get("other", 0.0),
            )
            repo.upsert_credit_categorization(conn, cc)

        # Link to program if specified
        if program:
            repo.upsert_program(conn, Program(program_code=program))
            repo.link_course_program(conn, course_id, program)

        # Store CLO-PLO mappings if present
        unmatched_plo_codes: set[str] = set()
        if parsed.clos and clo_ids:
            for clo_data, clo_db_id in zip(parsed.clos, clo_ids):
                if clo_data.aligned_plos:
                    for plo_code in clo_data.aligned_plos:
                        stored = _store_extracted_plo_mapping(
                            conn, clo_db_id, plo_code,
                            program=program,
                        )
                        if not stored and program:
                            unmatched_plo_codes.add(plo_code)

        # 7. Record source file
        repo.upsert_source_file(
            conn,
            file_path=str(path),
            file_name=file_name,
            file_extension=path.suffix.lower(),
            file_size=path.stat().st_size,
            content_hash=content_hash,
            format_type=parsed.format_type,
            course_id=course_id,
        )

        # 8. Return result
        return IngestResult(
            file_path=str(path),
            file_name=file_name,
            course_code=parsed.course_code,
            status="success",
            message=(
                f"Stored: {len(clos)} CLOs, {len(topics)} topics, "
                f"{len(textbooks)} textbooks, {len(assessments)} assessments"
            ),
            unmatched_plo_codes=unmatched_plo_codes,
        )

    except Exception as exc:
        return IngestResult(
            file_path=str(path),
            file_name=file_name,
            course_code=None,
            status="error",
            message=str(exc),
        )
    finally:
        conn.close()


def _store_extracted_plo_mapping(
    conn, clo_db_id: int, plo_short_code: str,
    program: str | None = None,
) -> bool:
    """Attempt to store a CLO-PLO mapping from extracted data.

    PLO codes from extraction are short codes like "K1", "S2".
    We search for matching PLO definitions in the database,
    falling back to PLO aliases if no direct match is found.

    Returns True if a mapping was stored, False otherwise.
    """
    from abet_syllabus.db.models import CloPloMapping

    # Search for PLO by plo_label matching the short code
    if program:
        rows = conn.execute(
            "SELECT id, program_code FROM plo_definitions WHERE plo_label = ? AND program_code = ?",
            (plo_short_code, program),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, program_code FROM plo_definitions WHERE plo_label = ?",
            (plo_short_code,),
        ).fetchall()

    if rows:
        for row in rows:
            repo.upsert_clo_plo_mapping(conn, CloPloMapping(
                course_clo_id=clo_db_id,
                plo_id=row["id"],
                program_code=row["program_code"],
                mapping_source="extracted",
                confidence=1.0,
                rationale="Extracted from source document",
            ))
        return True

    # Fallback: check PLO aliases
    if program:
        alias_row = conn.execute(
            "SELECT plo_id FROM plo_aliases WHERE alias = ? AND program_code = ?",
            (plo_short_code, program),
        ).fetchone()
        if alias_row:
            repo.upsert_clo_plo_mapping(conn, CloPloMapping(
                course_clo_id=clo_db_id,
                plo_id=alias_row["plo_id"],
                program_code=program,
                mapping_source="extracted",
                confidence=1.0,
                rationale="Extracted from source document (via alias)",
            ))
            return True

    return False


def prompt_plo_aliases(
    conn,
    unmatched_codes: set[str],
    program_code: str,
) -> int:
    """Interactively prompt the user to map unmatched PLO codes to existing PLO definitions.

    Only prompts if stdin is a tty. Returns the number of aliases created.
    """
    if not unmatched_codes or not sys.stdin.isatty():
        return 0

    plos = repo.get_plos_for_program(conn, program_code)
    if not plos:
        return 0

    plo_labels = [p.plo_label for p in plos]
    plo_display = ", ".join(plo_labels)
    sorted_codes = sorted(unmatched_codes)

    print(f"\nFound unmapped PLO codes: {', '.join(sorted_codes)}")
    print(f"These don't match PLO definitions for {program_code} ({plo_display}).")
    print()

    try:
        answer = input("Map them now? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return 0

    if answer and answer not in ("y", "yes"):
        return 0

    # Build numbered choices
    choices = {str(i + 1): plo for i, plo in enumerate(plos)}
    choices_display = ", ".join(f"{k}={p.plo_label}" for k, p in choices.items())

    alias_count = 0
    for code in sorted_codes:
        try:
            pick = input(f"  {code} -> ? [{choices_display}, s=skip]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if pick == "s" or not pick:
            continue

        if pick in choices:
            plo = choices[pick]
            repo.upsert_plo_alias(conn, program_code, code, plo.id)
            alias_count += 1
            print(f"    {code} -> {plo.plo_label} (saved)")
        else:
            # Try matching by label directly
            matched = [p for p in plos if p.plo_label.lower() == pick]
            if matched:
                repo.upsert_plo_alias(conn, program_code, code, matched[0].id)
                alias_count += 1
                print(f"    {code} -> {matched[0].plo_label} (saved)")
            else:
                print(f"    Skipped (invalid choice)")

    if alias_count:
        print(f"\nSaved {alias_count} alias(es). Re-ingest to apply mappings.")

    return alias_count


def ingest_folder(
    folder_path: str | Path,
    db_path: str | Path,
    program: str | None = None,
    recursive: bool = False,
) -> list[IngestResult]:
    """Process all supported files in a folder.

    Args:
        folder_path: Path to a directory containing PDF/DOCX files.
        db_path: Path to the SQLite database.
        program: Optional program code to tag all courses.
        recursive: If True, search subdirectories.

    Returns:
        List of IngestResult objects, one per file attempted.
    """
    folder = Path(folder_path).resolve()
    if not folder.exists():
        return [IngestResult(
            file_path=str(folder),
            file_name=folder.name,
            course_code=None,
            status="error",
            message=f"Folder not found: {folder}",
        )]
    if not folder.is_dir():
        return [IngestResult(
            file_path=str(folder),
            file_name=folder.name,
            course_code=None,
            status="error",
            message=f"Not a directory: {folder}",
        )]

    # Collect all supported files
    pattern = "**/*" if recursive else "*"
    files = sorted(
        p for p in folder.glob(pattern)
        if p.is_file() and is_supported(p)
    )

    if not files:
        return []

    # Create a processing run record
    conn = init_db(db_path)
    try:
        run_id = repo.create_processing_run(
            conn,
            input_path=str(folder),
            program_code=program or "",
            total_files=len(files),
        )
    finally:
        conn.close()

    # Process each file
    results: list[IngestResult] = []
    success_count = 0
    error_count = 0

    for file_path in files:
        result = ingest_file(file_path, db_path, program=program)
        results.append(result)

        if result.status == "success":
            success_count += 1
        elif result.status == "error":
            error_count += 1

    # Update processing run with final counts
    conn = init_db(db_path)
    try:
        skipped = sum(1 for r in results if r.status == "skipped")
        repo.update_processing_run(
            conn, run_id,
            success_count=success_count,
            error_count=error_count,
            notes=f"Processed {len(files)} files: {success_count} success, {skipped} skipped, {error_count} errors",
        )
    finally:
        conn.close()

    return results


def ingest_plos(
    csv_path: str | Path,
    db_path: str | Path,
) -> int:
    """Load PLO definitions from a CSV file into the database.

    Args:
        csv_path: Path to the PLO definitions CSV file.
        db_path: Path to the SQLite database.

    Returns:
        Number of PLO definitions loaded.
    """
    conn = init_db(db_path)
    try:
        return repo.load_plos_from_csv(conn, csv_path)
    finally:
        conn.close()
