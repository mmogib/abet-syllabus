"""CSV and JSON export functions for database data.

Uses only standard library csv and json modules.
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from io import StringIO
from pathlib import Path

from abet_syllabus.db import repository as repo
from abet_syllabus.db.schema import init_db

logger = logging.getLogger(__name__)


def export_courses(
    db_path: str | Path,
    fmt: str = "csv",
    output: str | None = None,
    program: str | None = None,
) -> str:
    """Export all courses to CSV or JSON.

    Args:
        db_path: Path to the SQLite database.
        fmt: Output format, either "csv" or "json".
        output: Output file path. If None, returns the content as a string.
        program: Optional program code to filter courses.

    Returns:
        The exported content as a string.
    """
    conn = init_db(str(db_path))
    try:
        courses = repo.get_all_courses(conn, program_code=program)

        rows = []
        for c in courses:
            clo_count = len(repo.get_course_clos(conn, c.id))
            topic_count = len(repo.get_course_topics(conn, c.id))
            textbook_count = len(repo.get_course_textbooks(conn, c.id))
            assessment_count = len(repo.get_course_assessments(conn, c.id))

            rows.append({
                "course_code": c.course_code,
                "course_title": c.course_title,
                "department": c.department,
                "college": c.college,
                "credit_hours_raw": c.credit_hours_raw,
                "lecture_credits": c.lecture_credits,
                "lab_credits": c.lab_credits,
                "total_credits": c.total_credits,
                "course_type": c.course_type,
                "level": c.level,
                "prerequisites": c.prerequisites,
                "corequisites": c.corequisites,
                "clo_count": clo_count,
                "topic_count": topic_count,
                "textbook_count": textbook_count,
                "assessment_count": assessment_count,
            })
    finally:
        conn.close()

    content = _format_output(rows, fmt)
    _write_output(content, output)
    return content


def export_clos(
    db_path: str | Path,
    course_code: str,
    fmt: str = "csv",
    output: str | None = None,
) -> str:
    """Export CLOs for a specific course to CSV or JSON.

    Args:
        db_path: Path to the SQLite database.
        course_code: Course code (e.g., "MATH 101").
        fmt: Output format, either "csv" or "json".
        output: Output file path. If None, returns the content as a string.

    Returns:
        The exported content as a string.

    Raises:
        ValueError: If the course is not found.
    """
    conn = init_db(str(db_path))
    try:
        course = repo.get_course(conn, course_code.upper())
        if course is None:
            raise ValueError(f"Course not found: {course_code}")

        clos = repo.get_course_clos(conn, course.id)
        rows = []
        for clo in clos:
            # Look up PLO mappings
            plo_rows = conn.execute(
                """SELECT p.plo_label FROM clo_plo_mappings m
                   JOIN plo_definitions p ON m.plo_id = p.id
                   WHERE m.course_clo_id = ?
                   ORDER BY p.sequence""",
                (clo.id,),
            ).fetchall()
            plo_labels = [r["plo_label"] for r in plo_rows]

            rows.append({
                "course_code": course.course_code,
                "clo_code": clo.clo_code,
                "clo_category": clo.clo_category,
                "clo_text": clo.clo_text,
                "teaching_strategy": clo.teaching_strategy,
                "assessment_method": clo.assessment_method,
                "mapped_plos": "; ".join(plo_labels) if plo_labels else "",
            })
    finally:
        conn.close()

    content = _format_output(rows, fmt)
    _write_output(content, output)
    return content


def export_plo_matrix(
    db_path: str | Path,
    program_code: str,
    fmt: str = "csv",
    output: str | None = None,
) -> str:
    """Export CLO-PLO mapping matrix for a program.

    Produces a table where rows are (course, CLO) and columns are PLOs,
    with 'X' marking active mappings.

    Args:
        db_path: Path to the SQLite database.
        program_code: Program code (e.g., "MATH").
        fmt: Output format, either "csv" or "json".
        output: Output file path. If None, returns the content as a string.

    Returns:
        The exported content as a string.
    """
    conn = init_db(str(db_path))
    try:
        # Get all PLOs for the program (these become columns)
        plos = repo.get_plos_for_program(conn, program_code)
        plo_labels = [p.plo_label for p in plos]

        # Get all courses in the program
        courses = repo.get_all_courses(conn, program_code=program_code)

        rows = []
        for course in courses:
            clos = repo.get_course_clos(conn, course.id)
            mappings = repo.get_mappings_for_course(conn, course.id, program_code)

            # Build a lookup: clo_id -> set of plo_labels
            clo_plo_map: dict[int, set[str]] = {}
            for m in mappings:
                clo_id = m["course_clo_id"]
                if clo_id not in clo_plo_map:
                    clo_plo_map[clo_id] = set()
                clo_plo_map[clo_id].add(m["plo_label"])

            for clo in clos:
                row: dict[str, str] = {
                    "course_code": course.course_code,
                    "clo_code": clo.clo_code,
                    "clo_text": clo.clo_text,
                }
                mapped_plos = clo_plo_map.get(clo.id, set())
                for label in plo_labels:
                    row[label] = "X" if label in mapped_plos else ""
                rows.append(row)
    finally:
        conn.close()

    content = _format_output(rows, fmt)
    _write_output(content, output)
    return content


def _format_output(rows: list[dict], fmt: str) -> str:
    """Format rows as CSV or JSON string.

    Args:
        rows: List of row dicts.
        fmt: "csv" or "json".

    Returns:
        Formatted string.
    """
    if not rows:
        if fmt == "json":
            return "[]"
        return ""

    if fmt == "json":
        return json.dumps(rows, indent=2, ensure_ascii=False)

    # CSV format
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _write_output(content: str, output: str | None) -> None:
    """Write content to file or stdout.

    Args:
        content: The string content to write.
        output: File path, or None for stdout.
    """
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        logger.info("Exported to %s", output)
    else:
        print(content, end="")
