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


def test_ingest_placeholder():
    result = main(["ingest", "somefile.docx"])
    assert result == 0


def test_query_courses_placeholder():
    result = main(["query", "courses"])
    assert result == 0


def test_map_placeholder():
    result = main(["map", "MATH101", "--program", "MATH"])
    assert result == 0


def test_generate_placeholder():
    result = main(["generate", "MATH101", "--program", "MATH", "--term", "T252"])
    assert result == 0
