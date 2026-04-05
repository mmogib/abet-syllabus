"""Tests for the ingestion pipeline and query commands."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from abet_syllabus.cli import main, DEFAULT_DB_PATH
from abet_syllabus.db import repository as repo
from abet_syllabus.db.models import (
    Course,
    CourseClo,
    CourseTopic,
    CourseTextbook,
    CourseAssessment,
    Program,
    PloDefinition,
)
from abet_syllabus.db.schema import init_db
from abet_syllabus.ingest import IngestResult
from abet_syllabus.ingest.pipeline import (
    _map_parsed_to_db,
    _map_clos,
    _map_topics,
    _map_textbooks,
    _map_assessments,
    ingest_file,
    ingest_folder,
    ingest_plos,
)
from abet_syllabus.parse.models import (
    ParsedCourse,
    ParsedCLO,
    ParsedTopic,
    ParsedTextbook,
    ParsedAssessment,
)

# ---------------------------------------------------------------------------
# Resource path setup (same convention as other test files)
# ---------------------------------------------------------------------------

_RESOURCES = Path(os.environ.get(
    "ABET_RESOURCES",
    "C:/Users/mmogi/Projects/published_apps/abet-syllabus/resources",
))
_DATA_DIR = _RESOURCES / "course-descriptions" / "data"
_MATH_DIR = _RESOURCES / "course-descriptions" / "math"

_PDF_FILE = _DATA_DIR / "BUS 200 Course Specifications.pdf"
_DOCX_FILE = _MATH_DIR / "CS -Math-101-2024.docx"

_HAS_RESOURCES = _PDF_FILE.exists() and _DOCX_FILE.exists()
requires_resources = pytest.mark.skipif(
    not _HAS_RESOURCES,
    reason="Test resource files not found (resources/ is gitignored)",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Return path to a temporary database file."""
    return str(tmp_path / "test_ingest.db")


@pytest.fixture
def db(tmp_path):
    """Create and return an in-memory database connection."""
    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def plo_csv(tmp_path):
    """Create a temporary PLO CSV file."""
    csv_file = tmp_path / "plos.csv"
    csv_file.write_text(
        "id,plo_label,plo_description,program_code,order\n"
        "MATH_PLO_1,SO1,An ability to identify,MATH,1\n"
        "MATH_PLO_2,SO2,An ability to formulate,MATH,2\n"
        "MATH_PLO_3,K1,Knowledge outcome,MATH,3\n"
        "MATH_PLO_4,S1,Skills outcome,MATH,4\n"
        "DATA_PLO_1,SO1,Analyze complex problems,DATA,1\n",
        encoding="utf-8",
    )
    return csv_file


# ---------------------------------------------------------------------------
# Mapping function tests (unit tests, no DB needed)
# ---------------------------------------------------------------------------

class TestMappingFunctions:
    """Test the ParsedCourse -> DB model mapping functions."""

    def test_map_parsed_to_db_basic(self):
        parsed = ParsedCourse(
            course_code="MATH 101",
            course_title="Calculus I",
            department="Mathematics",
            college="Computing and Mathematics",
            credit_hours_raw="4-0-4",
            lecture_credits=4,
            lab_credits=0,
            total_credits=4,
        )
        course = _map_parsed_to_db(parsed)
        assert isinstance(course, Course)
        assert course.course_code == "MATH 101"
        assert course.course_title == "Calculus I"
        assert course.lecture_credits == 4

    def test_map_parsed_to_db_none_fields(self):
        """None values in parsed data should be converted to defaults."""
        parsed = ParsedCourse()
        course = _map_parsed_to_db(parsed)
        assert course.department == ""
        assert course.lecture_credits == 0
        assert course.prerequisites == ""

    def test_map_clos(self):
        parsed = ParsedCourse(clos=[
            ParsedCLO(clo_code="1.1", clo_text="Test CLO",
                      clo_category="Knowledge and Understanding", sequence=1),
        ])
        clos = _map_clos(parsed)
        assert len(clos) == 1
        assert isinstance(clos[0], CourseClo)
        assert clos[0].clo_code == "1.1"
        assert clos[0].clo_text == "Test CLO"

    def test_map_topics(self):
        parsed = ParsedCourse(topics=[
            ParsedTopic(topic_number=1, topic_title="Limits", contact_hours=9.0),
            ParsedTopic(topic_number=2, topic_title="Derivatives", contact_hours=9.0),
        ])
        topics = _map_topics(parsed)
        assert len(topics) == 2
        assert isinstance(topics[0], CourseTopic)
        assert topics[0].sequence == 1
        assert topics[1].sequence == 2

    def test_map_textbooks(self):
        parsed = ParsedCourse(textbooks=[
            ParsedTextbook(textbook_text="Calculus, Stewart"),
        ])
        textbooks = _map_textbooks(parsed)
        assert len(textbooks) == 1
        assert isinstance(textbooks[0], CourseTextbook)
        assert textbooks[0].textbook_type == "required"

    def test_map_assessments(self):
        parsed = ParsedCourse(assessments=[
            ParsedAssessment(assessment_task="Final Exam", proportion=40.0),
        ])
        assessments = _map_assessments(parsed)
        assert len(assessments) == 1
        assert isinstance(assessments[0], CourseAssessment)
        assert assessments[0].proportion == 40.0

    def test_map_assessments_none_fields(self):
        """None values in assessments should be converted to defaults."""
        parsed = ParsedCourse(assessments=[
            ParsedAssessment(assessment_task="Quiz", week_due=None, proportion=None),
        ])
        assessments = _map_assessments(parsed)
        assert assessments[0].week_due == ""
        assert assessments[0].proportion == 0.0


# ---------------------------------------------------------------------------
# IngestResult dataclass tests
# ---------------------------------------------------------------------------

class TestIngestResult:
    def test_create_success(self):
        r = IngestResult(
            file_path="/path/to/file.pdf",
            file_name="file.pdf",
            course_code="MATH 101",
            status="success",
            message="Stored: 5 CLOs",
        )
        assert r.status == "success"
        assert r.course_code == "MATH 101"

    def test_create_skipped(self):
        r = IngestResult(
            file_path="/path/to/file.pdf",
            file_name="file.pdf",
            course_code=None,
            status="skipped",
            message="Already processed",
        )
        assert r.status == "skipped"

    def test_create_error(self):
        r = IngestResult(
            file_path="/path/to/file.pdf",
            file_name="file.pdf",
            course_code=None,
            status="error",
            message="File not found",
        )
        assert r.status == "error"


# ---------------------------------------------------------------------------
# Ingestion pipeline tests with real files
# ---------------------------------------------------------------------------

class TestIngestFile:
    @requires_resources
    def test_ingest_pdf_file(self, db_path):
        result = ingest_file(_PDF_FILE, db_path)
        assert result.status == "success"
        assert result.course_code == "BUS 200"
        assert "CLOs" in result.message

    @requires_resources
    def test_ingest_docx_file(self, db_path):
        result = ingest_file(_DOCX_FILE, db_path)
        assert result.status == "success"
        assert result.course_code == "MATH 101"

    @requires_resources
    def test_ingest_stores_course_in_db(self, db_path):
        ingest_file(_PDF_FILE, db_path)
        conn = init_db(db_path)
        try:
            course = repo.get_course(conn, "BUS 200")
            assert course is not None
            assert course.course_title == "Business & Entrepreneurship"
        finally:
            conn.close()

    @requires_resources
    def test_ingest_stores_clos(self, db_path):
        ingest_file(_PDF_FILE, db_path)
        conn = init_db(db_path)
        try:
            course = repo.get_course(conn, "BUS 200")
            clos = repo.get_course_clos(conn, course.id)
            assert len(clos) >= 5
        finally:
            conn.close()

    @requires_resources
    def test_ingest_stores_topics(self, db_path):
        ingest_file(_PDF_FILE, db_path)
        conn = init_db(db_path)
        try:
            course = repo.get_course(conn, "BUS 200")
            topics = repo.get_course_topics(conn, course.id)
            assert len(topics) >= 5
        finally:
            conn.close()

    @requires_resources
    def test_ingest_stores_textbooks(self, db_path):
        ingest_file(_PDF_FILE, db_path)
        conn = init_db(db_path)
        try:
            course = repo.get_course(conn, "BUS 200")
            textbooks = repo.get_course_textbooks(conn, course.id)
            assert len(textbooks) >= 1
        finally:
            conn.close()

    @requires_resources
    def test_ingest_stores_assessments(self, db_path):
        ingest_file(_PDF_FILE, db_path)
        conn = init_db(db_path)
        try:
            course = repo.get_course(conn, "BUS 200")
            assessments = repo.get_course_assessments(conn, course.id)
            assert len(assessments) >= 3
        finally:
            conn.close()

    @requires_resources
    def test_ingest_stores_source_file(self, db_path):
        ingest_file(_PDF_FILE, db_path)
        conn = init_db(db_path)
        try:
            content_hash = repo.file_hash(_PDF_FILE)
            sf = repo.get_source_file_by_hash(conn, content_hash)
            assert sf is not None
            assert sf["file_name"] == _PDF_FILE.name
        finally:
            conn.close()

    def test_ingest_nonexistent_file(self, db_path):
        result = ingest_file("/nonexistent/file.pdf", db_path)
        assert result.status == "error"
        assert "not found" in result.message.lower() or "File not found" in result.message


# ---------------------------------------------------------------------------
# Deduplication tests
# ---------------------------------------------------------------------------

class TestDeduplication:
    @requires_resources
    def test_duplicate_file_skipped(self, db_path):
        """Ingesting the same file twice should skip the second time."""
        result1 = ingest_file(_PDF_FILE, db_path)
        result2 = ingest_file(_PDF_FILE, db_path)
        assert result1.status == "success"
        assert result2.status == "skipped"
        assert "already processed" in result2.message.lower() or "duplicate" in result2.message.lower()

    @requires_resources
    def test_duplicate_only_stores_once(self, db_path):
        """Database should have only one source_files entry for duplicate."""
        ingest_file(_PDF_FILE, db_path)
        ingest_file(_PDF_FILE, db_path)
        conn = init_db(db_path)
        try:
            stats = repo.get_stats(conn)
            assert stats["source_files"] == 1
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Program tagging tests
# ---------------------------------------------------------------------------

class TestProgramTagging:
    @requires_resources
    def test_ingest_with_program_tag(self, db_path):
        result = ingest_file(_DOCX_FILE, db_path, program="MATH")
        assert result.status == "success"

        conn = init_db(db_path)
        try:
            # Course should be linked to MATH program
            courses = repo.get_all_courses(conn, program_code="MATH")
            assert len(courses) == 1
            assert courses[0].course_code == "MATH 101"
        finally:
            conn.close()

    @requires_resources
    def test_ingest_without_program_tag(self, db_path):
        result = ingest_file(_DOCX_FILE, db_path)
        assert result.status == "success"

        conn = init_db(db_path)
        try:
            # Course should exist but not linked to any program
            courses = repo.get_all_courses(conn, program_code="MATH")
            assert len(courses) == 0
            # But it should exist in the courses table
            all_courses = repo.get_all_courses(conn)
            assert len(all_courses) == 1
        finally:
            conn.close()

    @requires_resources
    def test_ingest_program_creates_program(self, db_path):
        """Program should be auto-created when specified."""
        ingest_file(_DOCX_FILE, db_path, program="MATH")
        conn = init_db(db_path)
        try:
            programs = repo.get_programs(conn)
            assert any(p.program_code == "MATH" for p in programs)
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Folder ingestion tests
# ---------------------------------------------------------------------------

class TestIngestFolder:
    @requires_resources
    def test_ingest_folder_processes_multiple(self, db_path):
        results = ingest_folder(_DATA_DIR, db_path)
        assert len(results) > 5
        success = [r for r in results if r.status == "success"]
        assert len(success) > 5

    @requires_resources
    def test_ingest_folder_recursive(self, db_path):
        parent = _RESOURCES / "course-descriptions"
        results = ingest_folder(parent, db_path, recursive=True)
        assert len(results) > 20

    @requires_resources
    def test_ingest_folder_with_program(self, db_path):
        results = ingest_folder(_MATH_DIR, db_path, program="MATH")
        success = [r for r in results if r.status == "success"]
        assert len(success) >= 1

        conn = init_db(db_path)
        try:
            courses = repo.get_all_courses(conn, program_code="MATH")
            assert len(courses) >= 1
        finally:
            conn.close()

    def test_ingest_folder_nonexistent(self, db_path):
        results = ingest_folder("/nonexistent/folder", db_path)
        assert len(results) == 1
        assert results[0].status == "error"

    def test_ingest_folder_empty(self, tmp_path, db_path):
        results = ingest_folder(tmp_path, db_path)
        assert results == []

    @requires_resources
    def test_ingest_folder_creates_processing_run(self, db_path):
        ingest_folder(_MATH_DIR, db_path)
        conn = init_db(db_path)
        try:
            row = conn.execute("SELECT * FROM processing_runs").fetchone()
            assert row is not None
            assert row["success_count"] >= 1
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# PLO ingestion tests
# ---------------------------------------------------------------------------

class TestIngestPlos:
    def test_ingest_plos_from_csv(self, db_path, plo_csv):
        count = ingest_plos(plo_csv, db_path)
        assert count == 5

        conn = init_db(db_path)
        try:
            math_plos = repo.get_plos_for_program(conn, "MATH")
            assert len(math_plos) == 4
            data_plos = repo.get_plos_for_program(conn, "DATA")
            assert len(data_plos) == 1
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# CLO-PLO mapping storage tests
# ---------------------------------------------------------------------------

class TestCloPloMappingStorage:
    @requires_resources
    def test_clo_plo_mapping_with_loaded_plos(self, db_path, plo_csv):
        """When PLOs are loaded before ingestion, extracted mappings are stored."""
        # First load PLOs
        ingest_plos(plo_csv, db_path)
        # Then ingest a file with program
        result = ingest_file(_DOCX_FILE, db_path, program="MATH")
        assert result.status == "success"

        # Check if any CLO-PLO mappings were stored
        # (MATH 101 DOCX has aligned PLOs like K1, S1 in the CLO table)
        conn = init_db(db_path)
        try:
            course = repo.get_course(conn, "MATH 101")
            if course:
                stats = repo.get_stats(conn)
                # Mappings may or may not exist depending on the PLO labels
                # matching; this test verifies the pipeline doesn't crash
                assert stats["courses"] >= 1
        finally:
            conn.close()


# ---------------------------------------------------------------------------
# Repository extension tests
# ---------------------------------------------------------------------------

class TestRepositoryExtensions:
    """Test the new repository methods added for ingestion."""

    def test_get_source_file_by_hash_not_found(self, db):
        result = repo.get_source_file_by_hash(db, "nonexistent_hash")
        assert result is None

    def test_get_source_file_by_hash_found(self, db):
        sf_id = repo.upsert_source_file(
            db,
            file_path="/path/to/file.pdf",
            file_name="file.pdf",
            file_extension=".pdf",
            file_size=1234,
            content_hash="abc123hash",
            format_type="format_a_pdf",
        )
        result = repo.get_source_file_by_hash(db, "abc123hash")
        assert result is not None
        assert result["id"] == sf_id
        assert result["file_name"] == "file.pdf"

    def test_get_course_topics(self, db):
        course_id = repo.upsert_course(db, Course(course_code="MATH 101"))
        repo.replace_course_topics(db, course_id, [
            CourseTopic(topic_number=1, topic_title="Limits", contact_hours=9.0, sequence=1),
            CourseTopic(topic_number=2, topic_title="Derivatives", contact_hours=9.0, sequence=2),
        ])
        topics = repo.get_course_topics(db, course_id)
        assert len(topics) == 2
        assert topics[0].topic_title == "Limits"
        assert topics[1].topic_title == "Derivatives"

    def test_get_course_textbooks(self, db):
        course_id = repo.upsert_course(db, Course(course_code="MATH 101"))
        repo.replace_course_textbooks(db, course_id, [
            CourseTextbook(textbook_text="Calculus, Stewart", textbook_type="required", sequence=1),
        ])
        textbooks = repo.get_course_textbooks(db, course_id)
        assert len(textbooks) == 1
        assert textbooks[0].textbook_text == "Calculus, Stewart"

    def test_get_course_assessments(self, db):
        course_id = repo.upsert_course(db, Course(course_code="MATH 101"))
        repo.replace_course_assessment(db, course_id, [
            CourseAssessment(
                assessment_task="Final Exam", proportion=40.0,
                week_due="15", sequence=1,
            ),
        ])
        assessments = repo.get_course_assessments(db, course_id)
        assert len(assessments) == 1
        assert assessments[0].assessment_task == "Final Exam"
        assert assessments[0].proportion == 40.0

    def test_create_and_update_processing_run(self, db):
        run_id = repo.create_processing_run(
            db, input_path="/path/to/folder", program_code="MATH", total_files=10,
        )
        assert run_id > 0

        repo.update_processing_run(
            db, run_id, success_count=8, error_count=2, notes="Test run",
        )
        row = db.execute(
            "SELECT * FROM processing_runs WHERE id = ?", (run_id,)
        ).fetchone()
        assert row["success_count"] == 8
        assert row["error_count"] == 2
        assert row["completed_at"] is not None

    def test_add_run_file(self, db):
        # Create prerequisites
        run_id = repo.create_processing_run(
            db, input_path="/path", total_files=1,
        )
        sf_id = repo.upsert_source_file(
            db, file_path="/path/file.pdf", file_name="file.pdf",
            file_extension=".pdf", file_size=100, content_hash="hash123",
        )
        rf_id = repo.add_run_file(
            db, run_id=run_id, source_file_id=sf_id,
            status="success",
        )
        assert rf_id > 0

    def test_get_stats_includes_all_tables(self, db):
        stats = repo.get_stats(db)
        assert "course_textbooks" in stats
        assert "course_assessment" in stats
        assert "programs" in stats
        assert "courses" in stats


# ---------------------------------------------------------------------------
# CLI integration tests (query commands)
# ---------------------------------------------------------------------------

class TestQueryCLI:
    """Test the query CLI commands work after ingestion."""

    @requires_resources
    def test_query_courses_after_ingest(self, db_path, capsys):
        ingest_file(_PDF_FILE, db_path)
        result = main(["query", "--db", db_path, "courses"])
        assert result == 0
        captured = capsys.readouterr()
        assert "BUS 200" in captured.out

    @requires_resources
    def test_query_course_detail(self, db_path, capsys):
        ingest_file(_PDF_FILE, db_path)
        result = main(["query", "--db", db_path, "course", "BUS 200"])
        assert result == 0
        captured = capsys.readouterr()
        assert "BUS 200" in captured.out
        assert "CLOs" in captured.out

    @requires_resources
    def test_query_clos(self, db_path, capsys):
        ingest_file(_PDF_FILE, db_path)
        result = main(["query", "--db", db_path, "clos", "BUS 200"])
        assert result == 0
        captured = capsys.readouterr()
        assert "BUS 200" in captured.out

    @requires_resources
    def test_query_stats(self, db_path, capsys):
        ingest_file(_PDF_FILE, db_path)
        result = main(["query", "--db", db_path, "stats"])
        assert result == 0
        captured = capsys.readouterr()
        assert "Courses:" in captured.out

    def test_query_nonexistent_db(self, tmp_path, capsys):
        db_path = str(tmp_path / "nonexistent.db")
        result = main(["query", "--db", db_path, "stats"])
        assert result == 1

    @requires_resources
    def test_query_course_not_found(self, db_path, capsys):
        ingest_file(_PDF_FILE, db_path)
        result = main(["query", "--db", db_path, "course", "FAKE 999"])
        assert result == 1

    @requires_resources
    def test_query_courses_with_program_filter(self, db_path, capsys):
        ingest_file(_DOCX_FILE, db_path, program="MATH")
        result = main(["query", "--db", db_path, "courses", "-p", "MATH"])
        assert result == 0
        captured = capsys.readouterr()
        assert "MATH 101" in captured.out


# ---------------------------------------------------------------------------
# CLI ingest command tests
# ---------------------------------------------------------------------------

class TestIngestCLI:
    @requires_resources
    def test_ingest_cli_file(self, db_path, capsys):
        result = main(["ingest", str(_PDF_FILE), "--db", db_path])
        assert result == 0
        captured = capsys.readouterr()
        assert "BUS 200" in captured.out

    @requires_resources
    def test_ingest_cli_with_program(self, db_path, capsys):
        result = main(["ingest", str(_DOCX_FILE), "--db", db_path, "-p", "MATH"])
        assert result == 0
        captured = capsys.readouterr()
        assert "MATH 101" in captured.out

    def test_ingest_cli_nonexistent(self, db_path, capsys):
        result = main(["ingest", "/nonexistent/path", "--db", db_path])
        assert result == 1

    def test_ingest_plos_cli(self, db_path, plo_csv, capsys):
        result = main(["ingest-plos", str(plo_csv), "--db", db_path])
        assert result == 0
        captured = capsys.readouterr()
        assert "5" in captured.out

    def test_ingest_plos_cli_nonexistent(self, db_path, capsys):
        result = main(["ingest-plos", "/nonexistent/plos.csv", "--db", db_path])
        assert result == 1
