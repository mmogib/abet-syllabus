"""Data validation for the ABET Syllabus Generator.

Checks data quality and reports issues that would block or degrade
syllabus generation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from abet_syllabus.db import repository as repo
from abet_syllabus.db.schema import init_db

logger = logging.getLogger(__name__)


@dataclass
class ValidationIssue:
    """A single validation issue."""

    level: str  # "error" or "warning"
    course_code: str
    message: str


@dataclass
class ValidationReport:
    """Complete validation report."""

    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "error"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [i for i in self.issues if i.level == "warning"]

    @property
    def course_count(self) -> int:
        """Number of unique courses checked."""
        return len({i.course_code for i in self.issues} | self._checked_courses)

    _checked_courses: set[str] = field(default_factory=set, repr=False)

    def add_checked(self, course_code: str) -> None:
        """Record that a course was checked (even if no issues found)."""
        self._checked_courses.add(course_code)

    def format(self) -> str:
        """Format the report as a human-readable string."""
        lines = [
            "Validation Report",
            "=================",
            "",
        ]

        errors = self.errors
        warnings = self.warnings

        if errors:
            lines.append("ERRORS (block generation):")
            for e in errors:
                lines.append(f"  - {e.course_code}: {e.message}")
            lines.append("")

        if warnings:
            lines.append("WARNINGS (generation possible but incomplete):")
            for w in warnings:
                lines.append(f"  - {w.course_code}: {w.message}")
            lines.append("")

        if not errors and not warnings:
            lines.append("No issues found.")
            lines.append("")

        total_courses = len(self._checked_courses)
        lines.append(
            f"Summary: {len(errors)} error(s), {len(warnings)} warning(s) "
            f"across {total_courses} course(s)"
        )

        return "\n".join(lines)


def validate_database(
    db_path: str | Path,
    program_code: str | None = None,
) -> ValidationReport:
    """Validate data quality in the database.

    Checks:
    - Courses missing course title
    - Courses missing CLOs (error)
    - Courses with no topics (warning)
    - Courses with no textbooks (warning)
    - CLOs without PLO mappings per program (warning)
    - Programs with no PLO definitions (warning)

    Args:
        db_path: Path to the SQLite database.
        program_code: Optional program code to scope validation.

    Returns:
        ValidationReport with all issues found.
    """
    report = ValidationReport()

    conn = init_db(str(db_path))
    try:
        courses = repo.get_all_courses(conn, program_code=program_code)

        if not courses:
            logger.info("No courses found in database")
            return report

        # Check for programs with no PLO definitions
        if program_code:
            programs_to_check = [program_code]
        else:
            programs = repo.get_programs(conn)
            programs_to_check = [p.program_code for p in programs]

        for prog in programs_to_check:
            plos = repo.get_plos_for_program(conn, prog)
            if not plos:
                report.issues.append(ValidationIssue(
                    level="warning",
                    course_code=f"Program {prog}",
                    message="no PLO definitions loaded",
                ))

        # Check each course
        for course in courses:
            report.add_checked(course.course_code)

            # Missing title (error)
            if not course.course_title or not course.course_title.strip():
                report.issues.append(ValidationIssue(
                    level="error",
                    course_code=course.course_code,
                    message="missing course title",
                ))

            # Missing CLOs (error)
            clos = repo.get_course_clos(conn, course.id)
            if not clos:
                report.issues.append(ValidationIssue(
                    level="error",
                    course_code=course.course_code,
                    message="missing CLOs",
                ))

            # No topics (warning)
            topics = repo.get_course_topics(conn, course.id)
            if not topics:
                report.issues.append(ValidationIssue(
                    level="warning",
                    course_code=course.course_code,
                    message="no topics",
                ))

            # No textbooks (warning)
            textbooks = repo.get_course_textbooks(conn, course.id)
            if not textbooks:
                report.issues.append(ValidationIssue(
                    level="warning",
                    course_code=course.course_code,
                    message="no textbooks",
                ))

            # CLOs without PLO mappings (warning, per program)
            if clos and program_code:
                plos = repo.get_plos_for_program(conn, program_code)
                if plos:  # Only check if PLOs exist
                    mappings = repo.get_mappings_for_course(
                        conn, course.id, program_code
                    )
                    mapped_clo_ids = {m["course_clo_id"] for m in mappings}
                    unmapped = [c for c in clos if c.id not in mapped_clo_ids]
                    if unmapped:
                        report.issues.append(ValidationIssue(
                            level="warning",
                            course_code=course.course_code,
                            message=(
                                f"no PLO mappings for program {program_code} "
                                f"({len(unmapped)} CLO(s) unmapped)"
                            ),
                        ))
    finally:
        conn.close()

    return report
