"""Tests for force-ingest cascade bug fix and PLO aliases."""

from __future__ import annotations

import sqlite3
from io import StringIO
from unittest.mock import patch

import pytest

from abet_syllabus.db import repository as repo
from abet_syllabus.db.models import (
    CloPloMapping,
    Course,
    CourseClo,
    PloAlias,
    PloDefinition,
    Program,
)
from abet_syllabus.db.schema import init_db
from abet_syllabus.cli import main


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db():
    """Create an in-memory database with schema."""
    conn = init_db(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def db_with_course_and_mappings(db):
    """Set up a database with a course, CLOs, PLOs, and mappings."""
    # Program + PLOs
    repo.upsert_program(db, Program("MATH", "BS in Mathematics"))
    plo1_id = repo.upsert_plo(db, PloDefinition(
        program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
        plo_description="Identify and formulate", sequence=1,
    ))
    plo2_id = repo.upsert_plo(db, PloDefinition(
        program_code="MATH", plo_code="MATH_PLO_2", plo_label="SO2",
        plo_description="Formulate and solve", sequence=2,
    ))
    plo3_id = repo.upsert_plo(db, PloDefinition(
        program_code="MATH", plo_code="MATH_PLO_3", plo_label="SO3",
        plo_description="Communicate effectively", sequence=3,
    ))

    # Course
    course_id = repo.upsert_course(db, Course(
        course_code="MATH 101", course_title="Calculus I",
    ))

    # CLOs
    clo_ids = repo.replace_course_clos(db, course_id, [
        CourseClo(clo_code="1.1", clo_text="Identify basic functions",
                  clo_category="Knowledge", sequence=1),
        CourseClo(clo_code="2.1", clo_text="Compute limits and derivatives",
                  clo_category="Skills", sequence=2),
        CourseClo(clo_code="3.1", clo_text="Write mathematical proofs",
                  clo_category="Values", sequence=3),
    ])

    # Mappings
    repo.upsert_clo_plo_mapping(db, CloPloMapping(
        course_clo_id=clo_ids[0], plo_id=plo1_id, program_code="MATH",
        mapping_source="extracted", confidence=1.0,
        rationale="Extracted from source",
    ))
    repo.upsert_clo_plo_mapping(db, CloPloMapping(
        course_clo_id=clo_ids[1], plo_id=plo2_id, program_code="MATH",
        mapping_source="ai_suggested", confidence=0.85,
        rationale="AI suggested mapping", approved=True,
        approved_at="2025-01-15T12:00:00",
    ))
    repo.upsert_clo_plo_mapping(db, CloPloMapping(
        course_clo_id=clo_ids[2], plo_id=plo3_id, program_code="MATH",
        mapping_source="ai_suggested", confidence=0.9,
        rationale="Communication skills", approved=False,
    ))

    return {
        "conn": db,
        "course_id": course_id,
        "plo_ids": [plo1_id, plo2_id, plo3_id],
        "clo_ids": clo_ids,
    }


@pytest.fixture
def db_path(tmp_path):
    """Return path to a temporary database file."""
    return str(tmp_path / "test.db")


# ---------------------------------------------------------------------------
# Fix 1: Force-ingest cascade bug — preserve mappings
# ---------------------------------------------------------------------------

class TestForceIngestPreservesMappings:
    """Test that replace_course_clos_preserving_mappings keeps existing mappings."""

    def test_preserves_all_mappings_same_clo_codes(self, db_with_course_and_mappings):
        """When CLO codes don't change, all mappings should be preserved."""
        data = db_with_course_and_mappings
        conn = data["conn"]
        course_id = data["course_id"]

        # Verify mappings exist before
        before = conn.execute("SELECT COUNT(*) as c FROM clo_plo_mappings").fetchone()["c"]
        assert before == 3

        # Replace CLOs with same codes but different text (simulating re-parse)
        new_clos = [
            CourseClo(clo_code="1.1", clo_text="Updated: Identify basic functions",
                      clo_category="Knowledge", sequence=1),
            CourseClo(clo_code="2.1", clo_text="Updated: Compute limits and derivatives",
                      clo_category="Skills", sequence=2),
            CourseClo(clo_code="3.1", clo_text="Updated: Write mathematical proofs",
                      clo_category="Values", sequence=3),
        ]
        new_ids = repo.replace_course_clos_preserving_mappings(conn, course_id, new_clos)
        assert len(new_ids) == 3

        # Verify mappings are preserved
        after = conn.execute("SELECT COUNT(*) as c FROM clo_plo_mappings").fetchone()["c"]
        assert after == 3

        # Verify mapping details are intact
        mappings = repo.get_mappings_for_course(conn, course_id, "MATH")
        assert len(mappings) == 3

        # Check specific mapping attributes preserved
        mapping_by_clo = {m["clo_code"]: m for m in mappings}

        # Extracted mapping
        m1 = mapping_by_clo["1.1"]
        assert m1["mapping_source"] == "extracted"
        assert m1["confidence"] == 1.0
        assert m1["plo_label"] == "SO1"

        # Approved AI mapping
        m2 = mapping_by_clo["2.1"]
        assert m2["mapping_source"] == "ai_suggested"
        assert m2["confidence"] == 0.85
        assert m2["approved"] == 1
        assert m2["approved_at"] == "2025-01-15T12:00:00"

        # Unapproved AI mapping
        m3 = mapping_by_clo["3.1"]
        assert m3["mapping_source"] == "ai_suggested"
        assert m3["confidence"] == 0.9
        assert m3["approved"] == 0

    def test_preserves_mappings_for_kept_codes_drops_removed(self, db_with_course_and_mappings):
        """When a CLO code is removed during re-parse, its mappings are lost."""
        data = db_with_course_and_mappings
        conn = data["conn"]
        course_id = data["course_id"]

        # Replace with only 2 CLOs (3.1 removed)
        new_clos = [
            CourseClo(clo_code="1.1", clo_text="Identify basic functions",
                      clo_category="Knowledge", sequence=1),
            CourseClo(clo_code="2.1", clo_text="Compute limits",
                      clo_category="Skills", sequence=2),
        ]
        new_ids = repo.replace_course_clos_preserving_mappings(conn, course_id, new_clos)

        # Only 2 mappings should remain
        mappings = repo.get_mappings_for_course(conn, course_id, "MATH")
        assert len(mappings) == 2
        clo_codes = {m["clo_code"] for m in mappings}
        assert "1.1" in clo_codes
        assert "2.1" in clo_codes
        assert "3.1" not in clo_codes

    def test_new_clos_get_no_mappings(self, db_with_course_and_mappings):
        """New CLO codes that didn't exist before should have no mappings."""
        data = db_with_course_and_mappings
        conn = data["conn"]
        course_id = data["course_id"]

        # Replace with some old + some new codes
        new_clos = [
            CourseClo(clo_code="1.1", clo_text="Same code", sequence=1),
            CourseClo(clo_code="4.1", clo_text="Brand new CLO", sequence=2),
        ]
        new_ids = repo.replace_course_clos_preserving_mappings(conn, course_id, new_clos)

        mappings = repo.get_mappings_for_course(conn, course_id, "MATH")
        assert len(mappings) == 1
        assert mappings[0]["clo_code"] == "1.1"

    def test_regular_replace_destroys_mappings(self, db_with_course_and_mappings):
        """Verify the original replace_course_clos DOES destroy mappings (the bug)."""
        data = db_with_course_and_mappings
        conn = data["conn"]
        course_id = data["course_id"]

        # Use the old, non-preserving function
        new_clos = [
            CourseClo(clo_code="1.1", clo_text="Same code", sequence=1),
        ]
        repo.replace_course_clos(conn, course_id, new_clos)

        # All mappings should be gone
        mappings = repo.get_mappings_for_course(conn, course_id, "MATH")
        assert len(mappings) == 0

    def test_preserves_mappings_with_empty_clo_list(self, db_with_course_and_mappings):
        """Replacing with empty list should clear everything cleanly."""
        data = db_with_course_and_mappings
        conn = data["conn"]
        course_id = data["course_id"]

        new_ids = repo.replace_course_clos_preserving_mappings(conn, course_id, [])
        assert new_ids == []

        mappings = repo.get_mappings_for_course(conn, course_id, "MATH")
        assert len(mappings) == 0

    def test_preserves_multiple_mappings_per_clo(self, db_with_course_and_mappings):
        """A CLO mapped to multiple PLOs should keep all mappings."""
        data = db_with_course_and_mappings
        conn = data["conn"]
        course_id = data["course_id"]
        clo_ids = data["clo_ids"]
        plo_ids = data["plo_ids"]

        # Add a second mapping for CLO 1.1
        repo.upsert_clo_plo_mapping(conn, CloPloMapping(
            course_clo_id=clo_ids[0], plo_id=plo_ids[1], program_code="MATH",
            mapping_source="ai_suggested", confidence=0.7,
        ))

        before = conn.execute("SELECT COUNT(*) as c FROM clo_plo_mappings").fetchone()["c"]
        assert before == 4

        # Replace CLOs preserving mappings
        new_clos = [
            CourseClo(clo_code="1.1", clo_text="Updated", sequence=1),
            CourseClo(clo_code="2.1", clo_text="Updated", sequence=2),
            CourseClo(clo_code="3.1", clo_text="Updated", sequence=3),
        ]
        repo.replace_course_clos_preserving_mappings(conn, course_id, new_clos)

        after = conn.execute("SELECT COUNT(*) as c FROM clo_plo_mappings").fetchone()["c"]
        assert after == 4


# ---------------------------------------------------------------------------
# Fix 2: PLO Aliases — table, repository, resolution
# ---------------------------------------------------------------------------

class TestPloAliasesSchema:
    """Test that plo_aliases table exists and has correct constraints."""

    def test_table_exists(self, db):
        tables = [
            r["name"] for r in
            db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        ]
        assert "plo_aliases" in tables

    def test_unique_constraint(self, db):
        repo.upsert_program(db, Program("MATH"))
        plo_id = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))

        repo.upsert_plo_alias(db, "MATH", "K1", plo_id)

        # Inserting same alias should not raise (upsert)
        repo.upsert_plo_alias(db, "MATH", "K1", plo_id)

        aliases = repo.get_plo_aliases(db, "MATH")
        assert len(aliases) == 1


class TestPloAliasRepository:
    """Test PLO alias repository functions."""

    def test_upsert_and_get(self, db):
        repo.upsert_program(db, Program("MATH"))
        plo_id = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))

        repo.upsert_plo_alias(db, "MATH", "K1", plo_id)

        aliases = repo.get_plo_aliases(db, "MATH")
        assert len(aliases) == 1
        assert aliases[0].alias == "K1"
        assert aliases[0].plo_id == plo_id
        assert aliases[0].program_code == "MATH"

    def test_resolve_by_alias(self, db):
        repo.upsert_program(db, Program("MATH"))
        plo_id = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))

        repo.upsert_plo_alias(db, "MATH", "K1", plo_id)

        result = repo.resolve_plo_by_alias(db, "K1", "MATH")
        assert result == plo_id

    def test_resolve_nonexistent_alias(self, db):
        result = repo.resolve_plo_by_alias(db, "NOPE", "MATH")
        assert result is None

    def test_delete_alias(self, db):
        repo.upsert_program(db, Program("MATH"))
        plo_id = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))

        repo.upsert_plo_alias(db, "MATH", "K1", plo_id)
        assert repo.delete_plo_alias(db, "MATH", "K1") is True
        assert repo.delete_plo_alias(db, "MATH", "K1") is False

        aliases = repo.get_plo_aliases(db, "MATH")
        assert len(aliases) == 0

    def test_upsert_updates_plo_id(self, db):
        repo.upsert_program(db, Program("MATH"))
        plo1_id = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))
        plo2_id = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_2", plo_label="SO2",
            sequence=2,
        ))

        repo.upsert_plo_alias(db, "MATH", "K1", plo1_id)
        repo.upsert_plo_alias(db, "MATH", "K1", plo2_id)

        result = repo.resolve_plo_by_alias(db, "K1", "MATH")
        assert result == plo2_id

    def test_multiple_aliases_different_programs(self, db):
        repo.upsert_program(db, Program("MATH"))
        repo.upsert_program(db, Program("DATA"))
        plo_math = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))
        plo_data = repo.upsert_plo(db, PloDefinition(
            program_code="DATA", plo_code="DATA_PLO_1", plo_label="SO1",
            sequence=1,
        ))

        # Same alias "K1" for different programs
        repo.upsert_plo_alias(db, "MATH", "K1", plo_math)
        repo.upsert_plo_alias(db, "DATA", "K1", plo_data)

        assert repo.resolve_plo_by_alias(db, "K1", "MATH") == plo_math
        assert repo.resolve_plo_by_alias(db, "K1", "DATA") == plo_data


class TestResolvePloIdWithAlias:
    """Test that _resolve_plo_id in engine.py uses aliases as fallback."""

    def test_resolve_via_alias(self, db):
        from abet_syllabus.mapping.engine import _resolve_plo_id

        repo.upsert_program(db, Program("MATH"))
        plo_id = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))
        repo.upsert_plo_alias(db, "MATH", "K1", plo_id)

        # K1 should resolve via alias
        result = _resolve_plo_id(db, "K1", "MATH")
        assert result == plo_id

    def test_direct_match_takes_precedence_over_alias(self, db):
        from abet_syllabus.mapping.engine import _resolve_plo_id

        repo.upsert_program(db, Program("MATH"))
        plo1_id = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))
        plo2_id = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_2", plo_label="SO2",
            sequence=2,
        ))
        # Alias SO1 -> PLO2 (misleading, but tests precedence)
        repo.upsert_plo_alias(db, "MATH", "SO1", plo2_id)

        # Direct label match should take precedence
        result = _resolve_plo_id(db, "SO1", "MATH")
        assert result == plo1_id

    def test_no_match_returns_none(self, db):
        from abet_syllabus.mapping.engine import _resolve_plo_id

        repo.upsert_program(db, Program("MATH"))
        result = _resolve_plo_id(db, "UNKNOWN", "MATH")
        assert result is None


class TestStoreExtractedPloMappingWithAlias:
    """Test that _store_extracted_plo_mapping uses aliases."""

    def test_stores_via_alias(self, db):
        from abet_syllabus.ingest.pipeline import _store_extracted_plo_mapping

        repo.upsert_program(db, Program("MATH"))
        plo_id = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))
        repo.upsert_plo_alias(db, "MATH", "K1", plo_id)

        course_id = repo.upsert_course(db, Course(course_code="MATH 101"))
        clo_ids = repo.replace_course_clos(db, course_id, [
            CourseClo(clo_code="1.1", clo_text="Test", sequence=1),
        ])

        result = _store_extracted_plo_mapping(db, clo_ids[0], "K1", program="MATH")
        assert result is True

        mappings = repo.get_mappings_for_course(db, course_id, "MATH")
        assert len(mappings) == 1
        assert mappings[0]["plo_label"] == "SO1"
        assert "alias" in mappings[0]["rationale"].lower()

    def test_returns_false_when_no_match(self, db):
        from abet_syllabus.ingest.pipeline import _store_extracted_plo_mapping

        repo.upsert_program(db, Program("MATH"))
        repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))

        course_id = repo.upsert_course(db, Course(course_code="MATH 101"))
        clo_ids = repo.replace_course_clos(db, course_id, [
            CourseClo(clo_code="1.1", clo_text="Test", sequence=1),
        ])

        result = _store_extracted_plo_mapping(db, clo_ids[0], "NOPE", program="MATH")
        assert result is False

    def test_direct_label_match_returns_true(self, db):
        from abet_syllabus.ingest.pipeline import _store_extracted_plo_mapping

        repo.upsert_program(db, Program("MATH"))
        repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))

        course_id = repo.upsert_course(db, Course(course_code="MATH 101"))
        clo_ids = repo.replace_course_clos(db, course_id, [
            CourseClo(clo_code="1.1", clo_text="Test", sequence=1),
        ])

        result = _store_extracted_plo_mapping(db, clo_ids[0], "SO1", program="MATH")
        assert result is True


# ---------------------------------------------------------------------------
# Interactive alias prompt
# ---------------------------------------------------------------------------

class TestInteractiveAliasPrompt:
    """Test the interactive alias prompt function."""

    def test_prompt_not_tty_does_nothing(self, db):
        from abet_syllabus.ingest.pipeline import prompt_plo_aliases

        repo.upsert_program(db, Program("MATH"))
        repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))

        # Non-tty stdin -> should return 0
        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            count = prompt_plo_aliases(db, {"K1", "S1"}, "MATH")

        assert count == 0

    def test_prompt_empty_codes_does_nothing(self, db):
        from abet_syllabus.ingest.pipeline import prompt_plo_aliases

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            count = prompt_plo_aliases(db, set(), "MATH")

        assert count == 0

    def test_prompt_creates_aliases(self, db):
        from abet_syllabus.ingest.pipeline import prompt_plo_aliases

        repo.upsert_program(db, Program("MATH"))
        plo1_id = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))
        plo2_id = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_2", plo_label="SO2",
            sequence=2,
        ))

        # Simulate user input: "y" to confirm, "1" for K1->SO1, "2" for S1->SO2
        user_input = "y\n1\n2\n"

        with patch("sys.stdin", new_callable=StringIO) as mock_stdin:
            mock_stdin.write(user_input)
            mock_stdin.seek(0)
            # isatty() on StringIO returns False, so we need to mock it
            with patch("sys.stdin.isatty", return_value=True):
                count = prompt_plo_aliases(db, {"K1", "S1"}, "MATH")

        assert count == 2
        assert repo.resolve_plo_by_alias(db, "K1", "MATH") == plo1_id
        assert repo.resolve_plo_by_alias(db, "S1", "MATH") == plo2_id

    def test_prompt_skip_individual_alias(self, db):
        from abet_syllabus.ingest.pipeline import prompt_plo_aliases

        repo.upsert_program(db, Program("MATH"))
        repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))

        # Simulate: "y" to confirm, "s" to skip K1
        user_input = "y\ns\n"

        with patch("sys.stdin", new_callable=StringIO) as mock_stdin:
            mock_stdin.write(user_input)
            mock_stdin.seek(0)
            with patch("sys.stdin.isatty", return_value=True):
                count = prompt_plo_aliases(db, {"K1"}, "MATH")

        assert count == 0

    def test_prompt_decline_mapping(self, db):
        from abet_syllabus.ingest.pipeline import prompt_plo_aliases

        repo.upsert_program(db, Program("MATH"))
        repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))

        # Simulate: "n" to decline
        user_input = "n\n"

        with patch("sys.stdin", new_callable=StringIO) as mock_stdin:
            mock_stdin.write(user_input)
            mock_stdin.seek(0)
            with patch("sys.stdin.isatty", return_value=True):
                count = prompt_plo_aliases(db, {"K1"}, "MATH")

        assert count == 0


# ---------------------------------------------------------------------------
# CLI plo-alias command
# ---------------------------------------------------------------------------

class TestPloAliasCLI:
    """Test the plo-alias CLI subcommand."""

    def test_create_alias(self, db_path, capsys):
        # First set up PLOs
        conn = init_db(db_path)
        repo.upsert_program(conn, Program("MATH"))
        repo.upsert_plo(conn, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))
        conn.close()

        result = main(["plo-alias", "K1", "SO1", "-p", "MATH", "--db", db_path])
        assert result == 0
        captured = capsys.readouterr()
        assert "K1" in captured.out
        assert "SO1" in captured.out

    def test_list_aliases(self, db_path, capsys):
        # Set up
        conn = init_db(db_path)
        repo.upsert_program(conn, Program("MATH"))
        plo_id = repo.upsert_plo(conn, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))
        repo.upsert_plo_alias(conn, "MATH", "K1", plo_id)
        conn.close()

        result = main(["plo-alias", "--list", "-p", "MATH", "--db", db_path])
        assert result == 0
        captured = capsys.readouterr()
        assert "K1" in captured.out

    def test_delete_alias(self, db_path, capsys):
        # Set up
        conn = init_db(db_path)
        repo.upsert_program(conn, Program("MATH"))
        plo_id = repo.upsert_plo(conn, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))
        repo.upsert_plo_alias(conn, "MATH", "K1", plo_id)
        conn.close()

        result = main(["plo-alias", "--delete", "K1", "-p", "MATH", "--db", db_path])
        assert result == 0
        captured = capsys.readouterr()
        assert "Deleted" in captured.out

    def test_list_empty_aliases(self, db_path, capsys):
        conn = init_db(db_path)
        repo.upsert_program(conn, Program("MATH"))
        conn.close()

        result = main(["plo-alias", "--list", "-p", "MATH", "--db", db_path])
        assert result == 0
        captured = capsys.readouterr()
        assert "No PLO aliases" in captured.out

    def test_create_alias_invalid_target(self, db_path, capsys):
        conn = init_db(db_path)
        repo.upsert_program(conn, Program("MATH"))
        repo.upsert_plo(conn, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            sequence=1,
        ))
        conn.close()

        result = main(["plo-alias", "K1", "INVALID", "-p", "MATH", "--db", db_path])
        assert result == 1

    def test_delete_nonexistent_alias(self, db_path, capsys):
        conn = init_db(db_path)
        repo.upsert_program(conn, Program("MATH"))
        conn.close()

        result = main(["plo-alias", "--delete", "K1", "-p", "MATH", "--db", db_path])
        assert result == 0
        captured = capsys.readouterr()
        assert "not found" in captured.out
