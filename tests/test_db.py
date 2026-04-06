"""Tests for database schema and repository operations."""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from abet_syllabus.db.schema import init_db, get_schema_version
from abet_syllabus.db.models import (
    Course, CourseClo, CourseTextbook, CourseTopic,
    CreditCategorization, CourseInstructor, PloDefinition, Program,
    CloPloMapping, CourseAssessment,
)
from abet_syllabus.db import repository as repo


@pytest.fixture
def db():
    """Create a temporary in-memory database."""
    conn = init_db(":memory:")
    yield conn
    conn.close()


class TestSchema:
    def test_init_creates_tables(self, db):
        tables = [
            r["name"] for r in
            db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        ]
        assert "courses" in tables
        assert "course_clos" in tables
        assert "plo_definitions" in tables
        assert "clo_plo_mappings" in tables
        assert "programs" in tables
        assert "course_topics" in tables

    def test_schema_version(self, db):
        from abet_syllabus.db.schema import SCHEMA_VERSION
        assert get_schema_version(db) == SCHEMA_VERSION

    def test_foreign_keys_enabled(self, db):
        row = db.execute("PRAGMA foreign_keys").fetchone()
        assert row[0] == 1

    def test_idempotent_init(self):
        from abet_syllabus.db.schema import SCHEMA_VERSION
        conn = init_db(":memory:")
        init_db_conn2 = init_db(":memory:")
        assert get_schema_version(conn) == SCHEMA_VERSION
        conn.close()
        init_db_conn2.close()


class TestPrograms:
    def test_upsert_and_get(self, db):
        repo.upsert_program(db, Program("MATH", "BS in Mathematics"))
        programs = repo.get_programs(db)
        assert len(programs) == 1
        assert programs[0].program_code == "MATH"
        assert programs[0].program_name == "BS in Mathematics"

    def test_upsert_updates_name(self, db):
        repo.upsert_program(db, Program("MATH", "Old Name"))
        repo.upsert_program(db, Program("MATH", "BS in Mathematics"))
        programs = repo.get_programs(db)
        assert len(programs) == 1
        assert programs[0].program_name == "BS in Mathematics"


class TestPloDefinitions:
    def test_upsert_and_get(self, db):
        repo.upsert_program(db, Program("MATH"))
        plo_id = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1",
            plo_label="SO1", plo_description="An ability to identify...",
            sequence=1,
        ))
        assert plo_id > 0
        plos = repo.get_plos_for_program(db, "MATH")
        assert len(plos) == 1
        assert plos[0].plo_label == "SO1"


class TestCourses:
    def test_upsert_and_get(self, db):
        course_id = repo.upsert_course(db, Course(
            course_code="MATH 101", course_title="Calculus I",
            department="Mathematics", college="Computing and Mathematics",
            credit_hours_raw="4-0-4", lecture_credits=4, total_credits=4,
        ))
        assert course_id > 0
        course = repo.get_course(db, "MATH 101")
        assert course is not None
        assert course.course_title == "Calculus I"
        assert course.lecture_credits == 4

    def test_upsert_updates(self, db):
        repo.upsert_course(db, Course(course_code="MATH 101", course_title="Old Title"))
        repo.upsert_course(db, Course(course_code="MATH 101", course_title="Calculus I"))
        course = repo.get_course(db, "MATH 101")
        assert course.course_title == "Calculus I"

    def test_get_nonexistent_returns_none(self, db):
        assert repo.get_course(db, "FAKE 999") is None

    def test_get_all_courses(self, db):
        repo.upsert_course(db, Course(course_code="MATH 101"))
        repo.upsert_course(db, Course(course_code="DATA 201"))
        assert len(repo.get_all_courses(db)) == 2

    def test_get_courses_by_program(self, db):
        repo.upsert_program(db, Program("MATH"))
        repo.upsert_program(db, Program("DATA"))
        m_id = repo.upsert_course(db, Course(course_code="MATH 101"))
        d_id = repo.upsert_course(db, Course(course_code="DATA 201"))
        repo.link_course_program(db, m_id, "MATH")
        repo.link_course_program(db, d_id, "DATA")
        repo.link_course_program(db, m_id, "DATA")  # MATH 101 also in DATA

        math_courses = repo.get_all_courses(db, "MATH")
        data_courses = repo.get_all_courses(db, "DATA")
        assert len(math_courses) == 1
        assert len(data_courses) == 2


class TestCLOs:
    def test_replace_and_get(self, db):
        course_id = repo.upsert_course(db, Course(course_code="MATH 101"))
        clo_ids = repo.replace_course_clos(db, course_id, [
            CourseClo(clo_code="1.1", clo_category="Knowledge and Understanding",
                      clo_text="Identify basic functions", sequence=1),
            CourseClo(clo_code="2.1", clo_category="Skills",
                      clo_text="Compute limits", sequence=2),
        ])
        assert len(clo_ids) == 2
        clos = repo.get_course_clos(db, course_id)
        assert len(clos) == 2
        assert clos[0].clo_text == "Identify basic functions"

    def test_replace_deletes_old(self, db):
        course_id = repo.upsert_course(db, Course(course_code="MATH 101"))
        repo.replace_course_clos(db, course_id, [
            CourseClo(clo_code="1.1", clo_text="Old CLO", sequence=1),
        ])
        repo.replace_course_clos(db, course_id, [
            CourseClo(clo_code="1.1", clo_text="New CLO", sequence=1),
        ])
        clos = repo.get_course_clos(db, course_id)
        assert len(clos) == 1
        assert clos[0].clo_text == "New CLO"


class TestTopics:
    def test_replace_topics(self, db):
        course_id = repo.upsert_course(db, Course(course_code="MATH 101"))
        repo.replace_course_topics(db, course_id, [
            CourseTopic(topic_number=1, topic_title="Limits", contact_hours=9.0, sequence=1),
            CourseTopic(topic_number=2, topic_title="Derivatives", contact_hours=9.0, sequence=2),
        ])
        rows = db.execute("SELECT * FROM course_topics WHERE course_id = ? ORDER BY sequence", (course_id,)).fetchall()
        assert len(rows) == 2
        assert rows[0]["topic_title"] == "Limits"


class TestCloPloMappings:
    def test_full_mapping_flow(self, db):
        repo.upsert_program(db, Program("MATH"))
        plo_id = repo.upsert_plo(db, PloDefinition(
            program_code="MATH", plo_code="MATH_PLO_1", plo_label="SO1",
            plo_description="An ability...", sequence=1,
        ))
        course_id = repo.upsert_course(db, Course(course_code="MATH 101"))
        clo_ids = repo.replace_course_clos(db, course_id, [
            CourseClo(clo_code="1.1", clo_text="Identify functions", sequence=1),
        ])

        mapping_id = repo.upsert_clo_plo_mapping(db, CloPloMapping(
            course_clo_id=clo_ids[0], plo_id=plo_id, program_code="MATH",
            mapping_source="ai_suggested", confidence=0.85,
            rationale="CLO involves identification which maps to SO1",
        ))
        assert mapping_id > 0

        mappings = repo.get_mappings_for_course(db, course_id, "MATH")
        assert len(mappings) == 1
        assert mappings[0]["clo_code"] == "1.1"
        assert mappings[0]["plo_label"] == "SO1"
        assert mappings[0]["confidence"] == 0.85


class TestStats:
    def test_stats(self, db):
        repo.upsert_program(db, Program("MATH"))
        repo.upsert_course(db, Course(course_code="MATH 101"))
        stats = repo.get_stats(db)
        assert stats["programs"] == 1
        assert stats["courses"] == 1


class TestPloLoading:
    def test_load_from_csv(self, db, tmp_path):
        csv_file = tmp_path / "plos.csv"
        csv_file.write_text(
            "id,plo_label,plo_description,program_code,order\n"
            "MATH_PLO_1,SO1,An ability to identify,MATH,1\n"
            "MATH_PLO_2,SO2,An ability to formulate,MATH,2\n"
            "DATA_PLO_1,SO1,Analyze complex problems,,1\n",
            encoding="utf-8",
        )
        count = repo.load_plos_from_csv(db, csv_file)
        assert count == 3

        math_plos = repo.get_plos_for_program(db, "MATH")
        assert len(math_plos) == 2

        # DATA program_code was inferred from plo_code prefix
        data_plos = repo.get_plos_for_program(db, "DATA")
        assert len(data_plos) == 1
