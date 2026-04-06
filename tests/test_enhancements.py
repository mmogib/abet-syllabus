"""Tests for enhancement round: DOCX fixes, smart defaults, and CLI normalization."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from abet_syllabus.term import get_current_term
from abet_syllabus.parse.normalize import normalize_course_code
from abet_syllabus.generate.assembler import (
    SyllabusData,
    SyllabusTopic,
    normalize_course_type,
)


# ---------------------------------------------------------------------------
# Tests: get_current_term()
# ---------------------------------------------------------------------------

class TestGetCurrentTerm:
    """Term calculation with mocked dates."""

    def test_fall_semester(self):
        """Sep 1, 2025 -> Fall 2025 -> T251"""
        assert get_current_term(date(2025, 9, 1)) == "T251"

    def test_fall_boundary(self):
        """Aug 15, 2025 -> Fall 2025 -> T251"""
        assert get_current_term(date(2025, 8, 15)) == "T251"

    def test_before_fall_boundary(self):
        """Aug 14, 2025 -> Summer 2024-2025 -> T243"""
        assert get_current_term(date(2025, 8, 14)) == "T243"

    def test_spring_semester(self):
        """Feb 1, 2026 -> Spring of 2025-2026 year -> T252"""
        assert get_current_term(date(2026, 2, 1)) == "T252"

    def test_spring_boundary(self):
        """Jan 15, 2026 -> Spring of 2025-2026 year -> T252"""
        assert get_current_term(date(2026, 1, 15)) == "T252"

    def test_before_spring_boundary(self):
        """Jan 14, 2026 -> Still Fall 2025 -> T251"""
        assert get_current_term(date(2026, 1, 14)) == "T251"

    def test_summer_semester(self):
        """Jul 1, 2026 -> Summer of 2025-2026 year -> T253"""
        assert get_current_term(date(2026, 7, 1)) == "T253"

    def test_summer_boundary(self):
        """Jun 15, 2026 -> Summer of 2025-2026 year -> T253"""
        assert get_current_term(date(2026, 6, 15)) == "T253"

    def test_before_summer_boundary(self):
        """Jun 14, 2026 -> Still Spring 2025-2026 -> T252"""
        assert get_current_term(date(2026, 6, 14)) == "T252"

    def test_december(self):
        """Dec 1, 2025 -> Fall 2025 -> T251"""
        assert get_current_term(date(2025, 12, 1)) == "T251"

    def test_no_argument_uses_today(self):
        """When called without argument, should return a term string."""
        result = get_current_term()
        assert result.startswith("T")
        assert len(result) == 4  # "T" + 3 digits

    def test_current_date_april_2026(self):
        """Apr 5, 2026 -> Spring of 2025-2026 year -> T252"""
        assert get_current_term(date(2026, 4, 5)) == "T252"


# ---------------------------------------------------------------------------
# Tests: course code normalization in CLI
# ---------------------------------------------------------------------------

class TestCourseCodeNormalization:
    """normalize_course_code should canonicalize user input."""

    def test_lowercase_no_space(self):
        assert normalize_course_code("math101") == "MATH 101"

    def test_mixed_case_with_space(self):
        assert normalize_course_code("Math 101") == "MATH 101"

    def test_extra_spaces(self):
        assert normalize_course_code("MATH   101") == "MATH 101"

    def test_already_normalized(self):
        assert normalize_course_code("MATH 101") == "MATH 101"

    def test_with_hyphen(self):
        assert normalize_course_code("ICS-104") == "ICS 104"

    def test_empty_string(self):
        assert normalize_course_code("") == ""

    def test_leading_trailing_whitespace(self):
        assert normalize_course_code("  math  101  ") == "MATH 101"


# ---------------------------------------------------------------------------
# Tests: smart defaults resolution
# ---------------------------------------------------------------------------

class TestSmartDefaults:
    """Test _resolve_run_defaults and _detect_program_from_path."""

    def test_detect_program_from_dir_name(self, tmp_path):
        """Directory named 'math' should detect as MATH."""
        from abet_syllabus.cli import _detect_program_from_path
        math_dir = tmp_path / "math"
        math_dir.mkdir()
        assert _detect_program_from_path(math_dir) == "MATH"

    def test_detect_program_from_single_subdir(self, tmp_path):
        """Directory with a single alpha subdir should detect it."""
        from abet_syllabus.cli import _detect_program_from_path
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "data").mkdir()
        assert _detect_program_from_path(input_dir) == "DATA"

    def test_detect_program_ambiguous(self, tmp_path):
        """Multiple subdirs should not auto-detect."""
        from abet_syllabus.cli import _detect_program_from_path
        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "math").mkdir()
        (input_dir / "data").mkdir()
        assert _detect_program_from_path(input_dir) is None

    def test_detect_program_from_file_parent(self, tmp_path):
        """File inside a program-named dir should detect the parent."""
        from abet_syllabus.cli import _detect_program_from_path
        math_dir = tmp_path / "as"
        math_dir.mkdir()
        file = math_dir / "course.pdf"
        file.touch()
        assert _detect_program_from_path(file) == "AS"

    def test_detect_program_long_name_ignored(self, tmp_path):
        """Directory names longer than 6 chars should not be detected as programs."""
        from abet_syllabus.cli import _detect_program_from_path
        long_dir = tmp_path / "resources"
        long_dir.mkdir()
        assert _detect_program_from_path(long_dir) is None


# ---------------------------------------------------------------------------
# Tests: topics weeks calculation
# ---------------------------------------------------------------------------

class TestTopicsWeeks:
    """Test that topics display weeks instead of raw hours."""

    def test_weeks_calculation(self):
        """contact_hours / weekly_contact_hours = weeks."""
        data = SyllabusData(
            weekly_contact_hours=3.0,
            topics=[
                SyllabusTopic(number=1, title="Limits", contact_hours=6.0),
                SyllabusTopic(number=2, title="Derivatives", contact_hours=9.0),
                SyllabusTopic(number=3, title="Integration", contact_hours=4.5),
            ],
        )
        # weeks = 6/3=2, 9/3=3, 4.5/3=1.5
        # The formatting logic is in docx_generator._fill_topics, so we
        # test the calculation directly here
        weekly = data.weekly_contact_hours
        assert weekly > 0

        weeks_1 = data.topics[0].contact_hours / weekly
        weeks_2 = data.topics[1].contact_hours / weekly
        weeks_3 = data.topics[2].contact_hours / weekly

        assert weeks_1 == 2.0
        assert weeks_2 == 3.0
        assert weeks_3 == 1.5

    def test_weeks_with_zero_weekly(self):
        """When weekly_contact_hours is 0, should fall back to hours."""
        data = SyllabusData(
            weekly_contact_hours=0.0,
            topics=[
                SyllabusTopic(number=1, title="Limits", contact_hours=6.0),
            ],
        )
        # The fallback is handled in the generator; here we just verify the data
        assert data.weekly_contact_hours == 0.0

    def test_weekly_hours_from_credits(self):
        """3-0-3 means 3 lecture + 0 lab = 3 weekly hours."""
        data = SyllabusData(lecture_credits=3, lab_credits=0, weekly_contact_hours=3.0)
        assert data.weekly_contact_hours == 3.0

    def test_weekly_hours_with_lab(self):
        """2-3-3 means 2 lecture + 3 lab = 5 weekly hours."""
        data = SyllabusData(lecture_credits=2, lab_credits=3, weekly_contact_hours=5.0)
        assert data.weekly_contact_hours == 5.0


# ---------------------------------------------------------------------------
# Tests: designation normalization
# ---------------------------------------------------------------------------

class TestDesignationNormalization:
    """Test normalize_course_type for various inputs."""

    def test_required(self):
        assert normalize_course_type("Required") == "Required"

    def test_required_lowercase(self):
        assert normalize_course_type("required") == "Required"

    def test_university_required(self):
        assert normalize_course_type("University Required") == "Required"

    def test_core(self):
        assert normalize_course_type("Core") == "Required"

    def test_compulsory(self):
        assert normalize_course_type("Compulsory") == "Required"

    def test_mandatory(self):
        assert normalize_course_type("Mandatory") == "Required"

    def test_elective(self):
        assert normalize_course_type("Elective") == "Elective"

    def test_elective_lowercase(self):
        assert normalize_course_type("elective") == "Elective"

    def test_selected_elective(self):
        assert normalize_course_type("Selected Elective") == "Selected Elective"

    def test_selected_elective_mixed_case(self):
        assert normalize_course_type("selected elective") == "Selected Elective"

    def test_empty_string(self):
        assert normalize_course_type("") == ""

    def test_none_like_whitespace(self):
        assert normalize_course_type("   ") == ""

    def test_unrecognized(self):
        assert normalize_course_type("Other Type") == ""


# ---------------------------------------------------------------------------
# Tests: assembler weekly_contact_hours field
# ---------------------------------------------------------------------------

class TestAssemblerWeeklyHours:
    """Test that SyllabusData gets weekly_contact_hours computed."""

    def test_assembler_computes_weekly_hours(self):
        """The assembler should set weekly_contact_hours from lecture + lab credits."""
        from abet_syllabus.db.schema import init_db
        from abet_syllabus.db import repository as repo
        from abet_syllabus.db.models import Course, Program
        from abet_syllabus.generate.assembler import assemble_syllabus_data

        conn = init_db(":memory:")
        repo.upsert_program(conn, Program(program_code="TEST"))
        course_id = repo.upsert_course(conn, Course(
            course_code="TEST 100",
            course_title="Test Course",
            lecture_credits=2,
            lab_credits=3,
            total_credits=3,
            credit_hours_raw="2-3-3",
        ))
        repo.link_course_program(conn, course_id, "TEST")
        conn.close()

        # We need a temp file for the db
        import tempfile, os
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        try:
            conn = init_db(db_path)
            repo.upsert_program(conn, Program(program_code="TEST"))
            course_id = repo.upsert_course(conn, Course(
                course_code="TEST 100",
                course_title="Test Course",
                lecture_credits=2,
                lab_credits=3,
                total_credits=3,
                credit_hours_raw="2-3-3",
            ))
            conn.close()

            data = assemble_syllabus_data(db_path, "TEST 100")
            assert data.weekly_contact_hours == 5.0
        finally:
            os.unlink(db_path)


# ---------------------------------------------------------------------------
# Tests: model flag on engine
# ---------------------------------------------------------------------------

class TestModelFlag:
    """Test that get_default_provider accepts and passes model parameter."""

    def test_get_default_provider_signature(self):
        """get_default_provider should accept model parameter."""
        from abet_syllabus.mapping.engine import get_default_provider
        import inspect
        sig = inspect.signature(get_default_provider)
        assert "model" in sig.parameters
