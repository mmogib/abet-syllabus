"""Smoke tests for CLI scaffold."""

import pytest

from abet_syllabus.cli import build_parser, main


def test_parser_builds():
    parser = build_parser()
    assert parser is not None


def test_no_command_returns_1():
    result = main([])
    assert result == 1


def test_version(capsys):
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0


def test_ingest_nonexistent_file():
    """Ingest with a nonexistent file should return error (1)."""
    result = main(["ingest", "somefile.docx"])
    assert result == 1


def test_query_courses_no_db(tmp_path):
    """Query without a real database should return error (1)."""
    # Use a non-existent path that init_db won't auto-create
    result = main(["query", "--db", str(tmp_path / "noexist" / "nope.db"), "courses"])
    assert result == 1


def test_map_missing_course(tmp_path):
    """Map with a nonexistent course should return error (1)."""
    db = str(tmp_path / "test.db")
    result = main(["map", "MATH101", "--program", "MATH", "--db", db])
    assert result == 1


def test_generate_no_db(tmp_path):
    """Generate without a database should return error (1)."""
    fake_db = str(tmp_path / "nonexistent" / "nope.db")
    result = main(["generate", "MATH101", "--program", "MATH", "--term", "T252", "--db", fake_db])
    assert result == 1


def test_run_nonexistent_path():
    """Run with a nonexistent path should return error (1)."""
    result = main(["run", "nonexistent/path", "-t", "T252"])
    assert result == 1


def test_run_parser():
    """Run subcommand parses all flags correctly."""
    parser = build_parser()
    args = parser.parse_args([
        "run", "somepath", "-p", "MATH", "-t", "T252",
        "-o", "./output", "-r", "--no-pdf", "--instructor", "Dr. X",
    ])
    assert args.command == "run"
    assert args.path == "somepath"
    assert args.program == "MATH"
    assert args.term == "T252"
    assert args.output == "./output"
    assert args.recursive is True
    assert args.no_pdf is True
    assert args.instructor == "Dr. X"
