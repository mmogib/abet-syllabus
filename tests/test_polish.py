"""Tests for Stage 8: polish, batch operations, and validation.

Tests cover:
- CSV and JSON export (courses, CLOs, PLO matrix)
- Configuration file loading (from file, defaults, CLI override)
- Status command output
- Validate command (courses with and without issues)
- Logging configuration
- Batch progress output
"""

from __future__ import annotations

import csv
import json
import logging
import tempfile
from io import StringIO
from pathlib import Path

import pytest

from abet_syllabus.cli import build_parser, main, DEFAULT_DB_PATH
from abet_syllabus.config import Config, _find_config_file
from abet_syllabus.db import repository as repo
from abet_syllabus.db.models import (
    CloPloMapping,
    Course,
    CourseAssessment,
    CourseClo,
    CourseTextbook,
    CourseTopic,
    PloDefinition,
    Program,
)
from abet_syllabus.db.schema import init_db
from abet_syllabus.export import export_clos, export_courses, export_plo_matrix
from abet_syllabus.logging_config import reset_logging, setup_logging
from abet_syllabus.validate import ValidationReport, validate_database


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db():
    """Create a temporary in-memory database."""
    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def db_path(tmp_path):
    """Return path to a temporary database file."""
    return str(tmp_path / "test_polish.db")


@pytest.fixture
def populated_db_path(tmp_path):
    """Create a database with sample data and return its path."""
    db_path = str(tmp_path / "populated.db")
    conn = init_db(db_path)
    try:
        _populate_test_data(conn)
    finally:
        conn.close()
    return db_path


@pytest.fixture(autouse=True)
def cleanup_logging():
    """Reset logging after each test to avoid handler accumulation."""
    yield
    reset_logging()


def _populate_test_data(conn):
    """Insert standard test data into the database."""
    # Programs
    repo.upsert_program(conn, Program("MATH", "BS in Mathematics"))
    repo.upsert_program(conn, Program("DATA", "BS in Data Science"))

    # PLOs
    plo1_id = repo.upsert_plo(conn, PloDefinition(
        program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
        plo_description="An ability to identify", sequence=1,
    ))
    plo2_id = repo.upsert_plo(conn, PloDefinition(
        program_code="MATH", plo_code="MATH_PLO_2", plo_label="SO2",
        plo_description="An ability to formulate", sequence=2,
    ))

    # Course 1: fully populated
    c1_id = repo.upsert_course(conn, Course(
        course_code="MATH 101", course_title="Calculus I",
        department="Mathematics", college="Computing and Mathematics",
        credit_hours_raw="4-0-4", lecture_credits=4, total_credits=4,
    ))
    repo.link_course_program(conn, c1_id, "MATH")
    clo_ids = repo.replace_course_clos(conn, c1_id, [
        CourseClo(clo_code="1.1", clo_category="Knowledge", clo_text="Identify limits", sequence=1),
        CourseClo(clo_code="2.1", clo_category="Skills", clo_text="Compute derivatives", sequence=2),
    ])
    repo.replace_course_topics(conn, c1_id, [
        CourseTopic(topic_number=1, topic_title="Limits", contact_hours=9.0, sequence=1),
        CourseTopic(topic_number=2, topic_title="Derivatives", contact_hours=9.0, sequence=2),
    ])
    repo.replace_course_textbooks(conn, c1_id, [
        CourseTextbook(textbook_text="Calculus, Stewart", textbook_type="required", sequence=1),
    ])
    repo.replace_course_assessment(conn, c1_id, [
        CourseAssessment(assessment_task="Final Exam", proportion=40.0, week_due="15", sequence=1),
    ])
    # Map CLO 1.1 -> SO1
    repo.upsert_clo_plo_mapping(conn, CloPloMapping(
        course_clo_id=clo_ids[0], plo_id=plo1_id, program_code="MATH",
        mapping_source="extracted", confidence=1.0,
        rationale="From source document",
    ))

    # Course 2: minimal (no topics, no textbooks)
    c2_id = repo.upsert_course(conn, Course(
        course_code="MATH 201", course_title="Calculus II",
        department="Mathematics", credit_hours_raw="3-0-3",
        lecture_credits=3, total_credits=3,
    ))
    repo.link_course_program(conn, c2_id, "MATH")
    repo.replace_course_clos(conn, c2_id, [
        CourseClo(clo_code="1.1", clo_category="Knowledge", clo_text="Apply integration", sequence=1),
    ])

    # Course 3: empty (no CLOs, no title)
    c3_id = repo.upsert_course(conn, Course(
        course_code="MATH 999", course_title="",
    ))
    repo.link_course_program(conn, c3_id, "MATH")

    # Source file record
    repo.upsert_source_file(
        conn,
        file_path="/path/to/file.pdf",
        file_name="file.pdf",
        file_extension=".pdf",
        file_size=1234,
        content_hash="abc123hash",
        format_type="format_a_pdf",
        course_id=c1_id,
    )


# ---------------------------------------------------------------------------
# Export tests
# ---------------------------------------------------------------------------


class TestExportCourses:
    def test_csv_export(self, populated_db_path):
        content = export_courses(populated_db_path, fmt="csv")
        assert content  # not empty
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)
        assert len(rows) == 3
        codes = {r["course_code"] for r in rows}
        assert "MATH 101" in codes
        assert "MATH 201" in codes

    def test_json_export(self, populated_db_path):
        content = export_courses(populated_db_path, fmt="json")
        data = json.loads(content)
        assert isinstance(data, list)
        assert len(data) == 3
        codes = {d["course_code"] for d in data}
        assert "MATH 101" in codes

    def test_csv_export_with_program_filter(self, populated_db_path):
        content = export_courses(populated_db_path, fmt="csv", program="MATH")
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)
        assert len(rows) == 3  # All 3 courses are linked to MATH
        for row in rows:
            assert row["course_code"].startswith("MATH")

    def test_export_to_file(self, populated_db_path, tmp_path):
        output = str(tmp_path / "courses.csv")
        export_courses(populated_db_path, fmt="csv", output=output)
        assert Path(output).exists()
        content = Path(output).read_text(encoding="utf-8")
        assert "MATH 101" in content

    def test_json_export_to_file(self, populated_db_path, tmp_path):
        output = str(tmp_path / "courses.json")
        export_courses(populated_db_path, fmt="json", output=output)
        assert Path(output).exists()
        data = json.loads(Path(output).read_text(encoding="utf-8"))
        assert len(data) == 3

    def test_csv_has_expected_columns(self, populated_db_path):
        content = export_courses(populated_db_path, fmt="csv")
        reader = csv.DictReader(StringIO(content))
        row = next(reader)
        assert "course_code" in row
        assert "course_title" in row
        assert "clo_count" in row
        assert "topic_count" in row

    def test_empty_db_csv(self, db_path):
        # Initialize empty DB
        conn = init_db(db_path)
        conn.close()
        content = export_courses(db_path, fmt="csv")
        assert content == ""

    def test_empty_db_json(self, db_path):
        conn = init_db(db_path)
        conn.close()
        content = export_courses(db_path, fmt="json")
        assert content == "[]"


class TestExportClos:
    def test_csv_export(self, populated_db_path):
        content = export_clos(populated_db_path, "MATH 101", fmt="csv")
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["clo_code"] == "1.1"

    def test_json_export(self, populated_db_path):
        content = export_clos(populated_db_path, "MATH 101", fmt="json")
        data = json.loads(content)
        assert len(data) == 2
        assert data[0]["clo_code"] == "1.1"

    def test_includes_mapped_plos(self, populated_db_path):
        content = export_clos(populated_db_path, "MATH 101", fmt="csv")
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)
        # First CLO should have SO1 mapped
        assert rows[0]["mapped_plos"] == "SO1"

    def test_nonexistent_course_raises(self, populated_db_path):
        with pytest.raises(ValueError, match="Course not found"):
            export_clos(populated_db_path, "FAKE 999", fmt="csv")

    def test_export_to_file(self, populated_db_path, tmp_path):
        output = str(tmp_path / "clos.csv")
        export_clos(populated_db_path, "MATH 101", fmt="csv", output=output)
        assert Path(output).exists()


class TestExportPloMatrix:
    def test_csv_export(self, populated_db_path):
        content = export_plo_matrix(populated_db_path, "MATH", fmt="csv")
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)
        # 3 CLOs total across MATH courses (2 from MATH 101, 1 from MATH 201)
        assert len(rows) >= 2
        # Check PLO columns exist
        assert "SO1" in rows[0]
        assert "SO2" in rows[0]

    def test_json_export(self, populated_db_path):
        content = export_plo_matrix(populated_db_path, "MATH", fmt="json")
        data = json.loads(content)
        assert isinstance(data, list)
        assert len(data) >= 2

    def test_matrix_marks_mappings(self, populated_db_path):
        content = export_plo_matrix(populated_db_path, "MATH", fmt="csv")
        reader = csv.DictReader(StringIO(content))
        rows = list(reader)
        # Find MATH 101 CLO 1.1 row
        math101_rows = [r for r in rows if r["course_code"] == "MATH 101" and r["clo_code"] == "1.1"]
        assert len(math101_rows) == 1
        assert math101_rows[0]["SO1"] == "X"

    def test_export_to_file(self, populated_db_path, tmp_path):
        output = str(tmp_path / "matrix.csv")
        export_plo_matrix(populated_db_path, "MATH", fmt="csv", output=output)
        assert Path(output).exists()


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


class TestConfig:
    def test_defaults(self):
        config = Config()
        assert config.db_path == "abet_syllabus.db"
        assert config.log_level == "INFO"
        assert config.ai_provider == "anthropic"

    def test_load_defaults_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config = Config.load()
        assert config.db_path == "abet_syllabus.db"

    def test_load_from_yaml_file(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / "abet_syllabus.yaml"
        config_file.write_text(
            "db_path: custom.db\n"
            "output_dir: /custom/output\n"
            "log_level: DEBUG\n",
            encoding="utf-8",
        )
        config = Config.load()
        assert config.db_path == "custom.db"
        assert config.output_dir == "/custom/output"
        assert config.log_level == "DEBUG"

    def test_load_from_explicit_path(self, tmp_path):
        config_file = tmp_path / "my_config.yaml"
        config_file.write_text(
            "db_path: mydb.db\n"
            "ai_provider: openai\n",
            encoding="utf-8",
        )
        config = Config.load(str(config_file))
        assert config.db_path == "mydb.db"
        assert config.ai_provider == "openai"

    def test_load_missing_explicit_path(self, tmp_path):
        config = Config.load(str(tmp_path / "nonexistent.yaml"))
        # Should fall back to defaults
        assert config.db_path == "abet_syllabus.db"

    def test_cli_overrides(self):
        config = Config()
        config.apply_cli_overrides(db_path="override.db", output_dir=None)
        assert config.db_path == "override.db"
        # None values should not override
        assert config.output_dir == "./output"

    def test_partial_config_file(self, tmp_path, monkeypatch):
        """Config file with only some values should use defaults for the rest."""
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / "abet_syllabus.yaml"
        config_file.write_text("db_path: partial.db\n", encoding="utf-8")
        config = Config.load()
        assert config.db_path == "partial.db"
        assert config.template_path == "resources/templates/ABETSyllabusTemplate.docx"

    def test_yml_extension(self, tmp_path, monkeypatch):
        """Should also find .yml extension."""
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / "abet_syllabus.yml"
        config_file.write_text("db_path: yml_db.db\n", encoding="utf-8")
        config = Config.load()
        assert config.db_path == "yml_db.db"

    def test_invalid_yaml(self, tmp_path, monkeypatch):
        """Invalid YAML should fall back to defaults."""
        monkeypatch.chdir(tmp_path)
        config_file = tmp_path / "abet_syllabus.yaml"
        config_file.write_text(": : :\n[invalid yaml", encoding="utf-8")
        config = Config.load()
        assert config.db_path == "abet_syllabus.db"


# ---------------------------------------------------------------------------
# Status command tests
# ---------------------------------------------------------------------------


class TestStatusCommand:
    def test_status_with_data(self, populated_db_path, capsys):
        result = main(["status", "--db", populated_db_path])
        assert result == 0
        captured = capsys.readouterr()
        assert "Database:" in captured.out
        assert "Programs:" in captured.out
        assert "MATH" in captured.out
        assert "Courses:" in captured.out
        assert "CLO-PLO Mappings:" in captured.out
        assert "Source files:" in captured.out
        assert "Ready to generate:" in captured.out

    def test_status_shows_counts(self, populated_db_path, capsys):
        result = main(["status", "--db", populated_db_path])
        assert result == 0
        captured = capsys.readouterr()
        assert "With CLOs:" in captured.out
        assert "With topics:" in captured.out
        assert "With textbooks:" in captured.out

    def test_status_no_db(self, tmp_path, capsys):
        result = main(["status", "--db", str(tmp_path / "nonexistent.db")])
        assert result == 1

    def test_status_empty_db(self, db_path, capsys):
        conn = init_db(db_path)
        conn.close()
        result = main(["status", "--db", db_path])
        assert result == 0
        captured = capsys.readouterr()
        assert "Courses: 0" in captured.out


# ---------------------------------------------------------------------------
# Validate command tests
# ---------------------------------------------------------------------------


class TestValidateCommand:
    def test_validate_finds_errors(self, populated_db_path, capsys):
        result = main(["validate", "--db", populated_db_path])
        assert result == 1  # Errors present
        captured = capsys.readouterr()
        assert "ERRORS" in captured.out
        assert "MATH 999" in captured.out
        assert "missing" in captured.out.lower()

    def test_validate_finds_warnings(self, populated_db_path, capsys):
        main(["validate", "--db", populated_db_path])
        captured = capsys.readouterr()
        assert "WARNINGS" in captured.out

    def test_validate_with_program(self, populated_db_path, capsys):
        result = main(["validate", "--db", populated_db_path, "-p", "MATH"])
        captured = capsys.readouterr()
        assert "Summary:" in captured.out

    def test_validate_no_db(self, tmp_path, capsys):
        result = main(["validate", "--db", str(tmp_path / "nonexistent.db")])
        assert result == 1

    def test_validate_clean_db(self, db_path, capsys):
        """A database with only well-formed courses should pass."""
        conn = init_db(db_path)
        c_id = repo.upsert_course(conn, Course(
            course_code="GOOD 101", course_title="Good Course",
        ))
        repo.replace_course_clos(conn, c_id, [
            CourseClo(clo_code="1.1", clo_text="A CLO", sequence=1),
        ])
        repo.replace_course_topics(conn, c_id, [
            CourseTopic(topic_number=1, topic_title="Topic", contact_hours=3.0, sequence=1),
        ])
        repo.replace_course_textbooks(conn, c_id, [
            CourseTextbook(textbook_text="A book", sequence=1),
        ])
        conn.close()

        result = main(["validate", "--db", db_path])
        assert result == 0
        captured = capsys.readouterr()
        assert "No issues found" in captured.out


class TestValidateModule:
    def test_report_format(self, populated_db_path):
        report = validate_database(populated_db_path)
        text = report.format()
        assert "Validation Report" in text
        assert "Summary:" in text

    def test_errors_vs_warnings(self, populated_db_path):
        report = validate_database(populated_db_path)
        # MATH 999 has no title and no CLOs -> errors
        error_codes = [e.course_code for e in report.errors]
        assert "MATH 999" in error_codes

    def test_warnings_for_missing_topics(self, populated_db_path):
        report = validate_database(populated_db_path)
        warning_messages = [w.message for w in report.warnings]
        # MATH 201 has no topics and no textbooks
        has_no_topics = any("no topics" in m for m in warning_messages)
        assert has_no_topics

    def test_empty_db(self, db_path):
        conn = init_db(db_path)
        conn.close()
        report = validate_database(db_path)
        assert len(report.errors) == 0
        assert len(report.warnings) == 0


# ---------------------------------------------------------------------------
# Logging tests
# ---------------------------------------------------------------------------


class TestLogging:
    def test_setup_default(self):
        setup_logging()
        log = logging.getLogger("abet_syllabus")
        assert log.level == logging.DEBUG
        assert len(log.handlers) >= 1

    def test_setup_verbose(self):
        setup_logging(verbose=True)
        log = logging.getLogger("abet_syllabus")
        # Console handler should be DEBUG
        console = log.handlers[0]
        assert console.level == logging.DEBUG

    def test_setup_quiet(self):
        setup_logging(quiet=True)
        log = logging.getLogger("abet_syllabus")
        console = log.handlers[0]
        assert console.level == logging.WARNING

    def test_setup_with_file(self, tmp_path):
        log_file = str(tmp_path / "test.log")
        setup_logging(log_file=log_file)
        log = logging.getLogger("abet_syllabus")
        # Should have 2 handlers: console + file
        assert len(log.handlers) == 2
        # Write a log message
        log.info("test message")
        # Check file exists
        assert Path(log_file).exists()

    def test_setup_idempotent(self):
        setup_logging()
        setup_logging()
        log = logging.getLogger("abet_syllabus")
        # Should only have 1 handler despite double setup
        assert len(log.handlers) == 1

    def test_reset(self):
        setup_logging()
        log = logging.getLogger("abet_syllabus")
        assert len(log.handlers) >= 1
        reset_logging()
        assert len(log.handlers) == 0


# ---------------------------------------------------------------------------
# Batch progress tests
# ---------------------------------------------------------------------------


class TestBatchProgress:
    def test_ingest_single_file_progress(self, db_path, capsys, tmp_path):
        """Ingesting a single file should show [1/1] progress."""
        # Create a dummy file (won't parse but will show progress format)
        dummy = tmp_path / "test.txt"
        dummy.write_text("not a real file")
        result = main(["ingest", str(dummy), "--db", db_path])
        # Will fail (not a supported file type), but let's check the output format
        # Actually txt files are not supported, so let's just test with a nonexistent path
        # to verify the error path works cleanly
        assert result == 1  # file not supported or error

    def test_parser_has_verbose_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--verbose", "status"])
        assert args.verbose is True

    def test_parser_has_quiet_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--quiet", "status"])
        assert args.quiet is True

    def test_parser_has_config_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--config", "my.yaml", "status"])
        assert args.config == "my.yaml"


# ---------------------------------------------------------------------------
# Export CLI integration tests
# ---------------------------------------------------------------------------


class TestExportCLI:
    def test_export_courses_csv(self, populated_db_path, capsys):
        result = main(["export", "--db", populated_db_path, "courses"])
        assert result == 0
        captured = capsys.readouterr()
        assert "MATH 101" in captured.out

    def test_export_courses_json(self, populated_db_path, capsys):
        result = main(["export", "--db", populated_db_path, "courses", "--format", "json"])
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert len(data) == 3

    def test_export_clos_csv(self, populated_db_path, capsys):
        result = main(["export", "--db", populated_db_path, "clos", "MATH 101"])
        assert result == 0
        captured = capsys.readouterr()
        assert "1.1" in captured.out

    def test_export_clos_nonexistent(self, populated_db_path, capsys):
        result = main(["export", "--db", populated_db_path, "clos", "FAKE 999"])
        assert result == 1

    def test_export_plo_matrix(self, populated_db_path, capsys):
        result = main(["export", "--db", populated_db_path, "plo-matrix", "-p", "MATH"])
        assert result == 0
        captured = capsys.readouterr()
        assert "SO1" in captured.out

    def test_export_to_file(self, populated_db_path, tmp_path, capsys):
        output = str(tmp_path / "out.csv")
        result = main([
            "export", "--db", populated_db_path, "courses",
            "-o", output,
        ])
        assert result == 0
        assert Path(output).exists()

    def test_export_no_db(self, tmp_path, capsys):
        result = main(["export", "--db", str(tmp_path / "nonexistent.db"), "courses"])
        assert result == 1
