"""Database operations for the ABET Syllabus catalog."""

from __future__ import annotations

import csv
import hashlib
import sqlite3
from pathlib import Path

from .models import (
    CloPloMapping,
    Course,
    CourseAssessment,
    CourseClo,
    CourseInstructor,
    CourseTextbook,
    CourseTopic,
    CreditCategorization,
    PloDefinition,
    Program,
)


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------

def upsert_program(conn: sqlite3.Connection, program: Program) -> str:
    conn.execute(
        "INSERT INTO programs (program_code, program_name) VALUES (?, ?)"
        " ON CONFLICT(program_code) DO UPDATE SET program_name = excluded.program_name",
        (program.program_code, program.program_name),
    )
    conn.commit()
    return program.program_code


def get_programs(conn: sqlite3.Connection) -> list[Program]:
    rows = conn.execute("SELECT program_code, program_name FROM programs ORDER BY program_code").fetchall()
    return [Program(program_code=r["program_code"], program_name=r["program_name"]) for r in rows]


# ---------------------------------------------------------------------------
# PLO Definitions
# ---------------------------------------------------------------------------

def upsert_plo(conn: sqlite3.Connection, plo: PloDefinition) -> int:
    conn.execute(
        """INSERT INTO plo_definitions (program_code, plo_code, plo_label, plo_description, sequence)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(program_code, plo_code) DO UPDATE SET
             plo_label = excluded.plo_label,
             plo_description = excluded.plo_description,
             sequence = excluded.sequence""",
        (plo.program_code, plo.plo_code, plo.label if hasattr(plo, 'label') else plo.plo_label,
         plo.plo_description, plo.sequence),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM plo_definitions WHERE program_code = ? AND plo_code = ?",
        (plo.program_code, plo.plo_code),
    ).fetchone()
    return row["id"]


def get_plos_for_program(conn: sqlite3.Connection, program_code: str) -> list[PloDefinition]:
    rows = conn.execute(
        "SELECT * FROM plo_definitions WHERE program_code = ? ORDER BY sequence",
        (program_code,),
    ).fetchall()
    return [
        PloDefinition(
            id=r["id"], program_code=r["program_code"], plo_code=r["plo_code"],
            plo_label=r["plo_label"], plo_description=r["plo_description"],
            sequence=r["sequence"],
        )
        for r in rows
    ]


def load_plos_from_csv(conn: sqlite3.Connection, csv_path: str | Path) -> int:
    """Load PLO definitions from a CSV file. Returns count of rows loaded."""
    path = Path(csv_path)
    count = 0
    with path.open(encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            plo_code = row.get("id", "").strip()
            program_code = row.get("program_code", "").strip()

            # Handle missing program_code: infer from plo_code prefix
            if not program_code and "_PLO_" in plo_code:
                program_code = plo_code.split("_PLO_")[0]

            if not program_code or not plo_code:
                continue

            upsert_program(conn, Program(program_code=program_code))
            upsert_plo(conn, PloDefinition(
                program_code=program_code,
                plo_code=plo_code,
                plo_label=row.get("plo_label", "").strip(),
                plo_description=row.get("plo_description", "").strip(),
                sequence=int(row.get("order", "0").strip() or "0"),
            ))
            count += 1
    return count


# ---------------------------------------------------------------------------
# Courses
# ---------------------------------------------------------------------------

def upsert_course(conn: sqlite3.Connection, course: Course) -> int:
    conn.execute(
        """INSERT INTO courses (
             course_code, course_title, department, college,
             catalog_description, credit_hours_raw,
             lecture_credits, lab_credits, total_credits,
             course_type, level, prerequisites, corequisites, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(course_code) DO UPDATE SET
             course_title = excluded.course_title,
             department = excluded.department,
             college = excluded.college,
             catalog_description = excluded.catalog_description,
             credit_hours_raw = excluded.credit_hours_raw,
             lecture_credits = excluded.lecture_credits,
             lab_credits = excluded.lab_credits,
             total_credits = excluded.total_credits,
             course_type = excluded.course_type,
             level = excluded.level,
             prerequisites = excluded.prerequisites,
             corequisites = excluded.corequisites,
             updated_at = datetime('now')""",
        (
            course.course_code, course.course_title, course.department,
            course.college, course.catalog_description, course.credit_hours_raw,
            course.lecture_credits, course.lab_credits, course.total_credits,
            course.course_type, course.level, course.prerequisites,
            course.corequisites,
        ),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM courses WHERE course_code = ?", (course.course_code,)
    ).fetchone()
    return row["id"]


def get_course(conn: sqlite3.Connection, course_code: str) -> Course | None:
    row = conn.execute("SELECT * FROM courses WHERE course_code = ?", (course_code,)).fetchone()
    if not row:
        return None
    return Course(
        id=row["id"], course_code=row["course_code"], course_title=row["course_title"],
        department=row["department"], college=row["college"],
        catalog_description=row["catalog_description"],
        credit_hours_raw=row["credit_hours_raw"],
        lecture_credits=row["lecture_credits"], lab_credits=row["lab_credits"],
        total_credits=row["total_credits"], course_type=row["course_type"],
        level=row["level"], prerequisites=row["prerequisites"],
        corequisites=row["corequisites"],
    )


def get_all_courses(conn: sqlite3.Connection, program_code: str | None = None) -> list[Course]:
    if program_code:
        rows = conn.execute(
            """SELECT c.* FROM courses c
               JOIN course_programs cp ON c.id = cp.course_id
               WHERE cp.program_code = ?
               ORDER BY c.course_code""",
            (program_code,),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM courses ORDER BY course_code").fetchall()
    return [
        Course(
            id=r["id"], course_code=r["course_code"], course_title=r["course_title"],
            department=r["department"], college=r["college"],
            catalog_description=r["catalog_description"],
            credit_hours_raw=r["credit_hours_raw"],
            lecture_credits=r["lecture_credits"], lab_credits=r["lab_credits"],
            total_credits=r["total_credits"], course_type=r["course_type"],
            level=r["level"], prerequisites=r["prerequisites"],
            corequisites=r["corequisites"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Course-Program association
# ---------------------------------------------------------------------------

def link_course_program(conn: sqlite3.Connection, course_id: int, program_code: str, designation: str = "") -> None:
    conn.execute(
        """INSERT INTO course_programs (course_id, program_code, designation)
           VALUES (?, ?, ?)
           ON CONFLICT(course_id, program_code) DO UPDATE SET designation = excluded.designation""",
        (course_id, program_code, designation),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# CLOs
# ---------------------------------------------------------------------------

def replace_course_clos(conn: sqlite3.Connection, course_id: int, clos: list[CourseClo]) -> list[int]:
    """Delete existing CLOs for the course and insert new ones. Returns list of new IDs."""
    conn.execute("DELETE FROM course_clos WHERE course_id = ?", (course_id,))
    ids = []
    for clo in clos:
        cur = conn.execute(
            """INSERT INTO course_clos (course_id, clo_code, clo_category, clo_text,
                 teaching_strategy, assessment_method, sequence)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (course_id, clo.clo_code, clo.clo_category, clo.clo_text,
             clo.teaching_strategy, clo.assessment_method, clo.sequence),
        )
        ids.append(cur.lastrowid)
    conn.commit()
    return ids


def get_course_clos(conn: sqlite3.Connection, course_id: int) -> list[CourseClo]:
    rows = conn.execute(
        "SELECT * FROM course_clos WHERE course_id = ? ORDER BY sequence", (course_id,)
    ).fetchall()
    return [
        CourseClo(
            id=r["id"], course_id=r["course_id"], clo_code=r["clo_code"],
            clo_category=r["clo_category"], clo_text=r["clo_text"],
            teaching_strategy=r["teaching_strategy"],
            assessment_method=r["assessment_method"], sequence=r["sequence"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Topics
# ---------------------------------------------------------------------------

def replace_course_topics(conn: sqlite3.Connection, course_id: int, topics: list[CourseTopic]) -> None:
    conn.execute("DELETE FROM course_topics WHERE course_id = ?", (course_id,))
    for t in topics:
        conn.execute(
            """INSERT INTO course_topics (course_id, topic_number, topic_title,
                 contact_hours, topic_type, sequence)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (course_id, t.topic_number, t.topic_title, t.contact_hours,
             t.topic_type, t.sequence),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Textbooks
# ---------------------------------------------------------------------------

def replace_course_textbooks(conn: sqlite3.Connection, course_id: int, books: list[CourseTextbook]) -> None:
    conn.execute("DELETE FROM course_textbooks WHERE course_id = ?", (course_id,))
    for b in books:
        conn.execute(
            "INSERT INTO course_textbooks (course_id, textbook_text, textbook_type, sequence) VALUES (?, ?, ?, ?)",
            (course_id, b.textbook_text, b.textbook_type, b.sequence),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Assessment
# ---------------------------------------------------------------------------

def replace_course_assessment(conn: sqlite3.Connection, course_id: int, items: list[CourseAssessment]) -> None:
    conn.execute("DELETE FROM course_assessment WHERE course_id = ?", (course_id,))
    for a in items:
        conn.execute(
            """INSERT INTO course_assessment (course_id, assessment_task, week_due,
                 proportion, assessment_type, sequence)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (course_id, a.assessment_task, a.week_due, a.proportion,
             a.assessment_type, a.sequence),
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Credit categorization
# ---------------------------------------------------------------------------

def upsert_credit_categorization(conn: sqlite3.Connection, cat: CreditCategorization) -> None:
    conn.execute(
        """INSERT INTO credit_categorization (course_id, engineering_cs, math_science,
             humanities, social_sciences_business, general_education, other)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(course_id) DO UPDATE SET
             engineering_cs = excluded.engineering_cs,
             math_science = excluded.math_science,
             humanities = excluded.humanities,
             social_sciences_business = excluded.social_sciences_business,
             general_education = excluded.general_education,
             other = excluded.other""",
        (cat.course_id, cat.engineering_cs, cat.math_science, cat.humanities,
         cat.social_sciences_business, cat.general_education, cat.other),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Instructors
# ---------------------------------------------------------------------------

def upsert_instructor(conn: sqlite3.Connection, inst: CourseInstructor) -> int:
    conn.execute(
        """INSERT INTO course_instructors (course_id, instructor_name, term_code, role)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(course_id, instructor_name, term_code) DO UPDATE SET
             role = excluded.role""",
        (inst.course_id, inst.instructor_name, inst.term_code, inst.role),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM course_instructors WHERE course_id = ? AND instructor_name = ? AND term_code = ?",
        (inst.course_id, inst.instructor_name, inst.term_code),
    ).fetchone()
    return row["id"]


# ---------------------------------------------------------------------------
# CLO-PLO Mappings
# ---------------------------------------------------------------------------

def upsert_clo_plo_mapping(conn: sqlite3.Connection, mapping: CloPloMapping) -> int:
    conn.execute(
        """INSERT INTO clo_plo_mappings (course_clo_id, plo_id, program_code,
             mapping_source, confidence, rationale, approved, approved_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(course_clo_id, plo_id, program_code) DO UPDATE SET
             mapping_source = excluded.mapping_source,
             confidence = excluded.confidence,
             rationale = excluded.rationale,
             approved = excluded.approved,
             approved_at = excluded.approved_at""",
        (mapping.course_clo_id, mapping.plo_id, mapping.program_code,
         mapping.mapping_source, mapping.confidence, mapping.rationale,
         1 if mapping.approved else 0, mapping.approved_at),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM clo_plo_mappings WHERE course_clo_id = ? AND plo_id = ? AND program_code = ?",
        (mapping.course_clo_id, mapping.plo_id, mapping.program_code),
    ).fetchone()
    return row["id"]


def get_mappings_for_course(conn: sqlite3.Connection, course_id: int, program_code: str) -> list[dict]:
    """Return CLO-PLO mappings for a course within a program, joined with CLO and PLO details."""
    rows = conn.execute(
        """SELECT m.*, c.clo_code, c.clo_text, p.plo_code, p.plo_label
           FROM clo_plo_mappings m
           JOIN course_clos c ON m.course_clo_id = c.id
           JOIN plo_definitions p ON m.plo_id = p.id
           WHERE c.course_id = ? AND m.program_code = ?
           ORDER BY c.sequence, p.sequence""",
        (course_id, program_code),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Source files
# ---------------------------------------------------------------------------

def file_hash(path: str | Path) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def upsert_source_file(
    conn: sqlite3.Connection, *, file_path: str, file_name: str,
    file_extension: str, file_size: int, content_hash: str,
    format_type: str = "", course_id: int | None = None,
) -> int:
    conn.execute(
        """INSERT INTO source_files (file_path, file_name, file_extension,
             file_size, file_hash, format_type, course_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(file_hash) DO UPDATE SET
             file_path = excluded.file_path,
             file_name = excluded.file_name,
             course_id = excluded.course_id""",
        (file_path, file_name, file_extension, file_size, content_hash,
         format_type, course_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT id FROM source_files WHERE file_hash = ?", (content_hash,)
    ).fetchone()
    return row["id"]


# ---------------------------------------------------------------------------
# Query helpers for topics, textbooks, assessments
# ---------------------------------------------------------------------------

def get_course_topics(conn: sqlite3.Connection, course_id: int) -> list[CourseTopic]:
    rows = conn.execute(
        "SELECT * FROM course_topics WHERE course_id = ? ORDER BY sequence",
        (course_id,),
    ).fetchall()
    return [
        CourseTopic(
            id=r["id"], course_id=r["course_id"], topic_number=r["topic_number"],
            topic_title=r["topic_title"], contact_hours=r["contact_hours"],
            topic_type=r["topic_type"], sequence=r["sequence"],
        )
        for r in rows
    ]


def get_course_textbooks(conn: sqlite3.Connection, course_id: int) -> list[CourseTextbook]:
    rows = conn.execute(
        "SELECT * FROM course_textbooks WHERE course_id = ? ORDER BY sequence",
        (course_id,),
    ).fetchall()
    return [
        CourseTextbook(
            id=r["id"], course_id=r["course_id"],
            textbook_text=r["textbook_text"],
            textbook_type=r["textbook_type"], sequence=r["sequence"],
        )
        for r in rows
    ]


def get_course_assessments(conn: sqlite3.Connection, course_id: int) -> list[CourseAssessment]:
    rows = conn.execute(
        "SELECT * FROM course_assessment WHERE course_id = ? ORDER BY sequence",
        (course_id,),
    ).fetchall()
    return [
        CourseAssessment(
            id=r["id"], course_id=r["course_id"],
            assessment_task=r["assessment_task"],
            week_due=r["week_due"], proportion=r["proportion"],
            assessment_type=r["assessment_type"], sequence=r["sequence"],
        )
        for r in rows
    ]


# ---------------------------------------------------------------------------
# Source file deduplication
# ---------------------------------------------------------------------------

def get_source_file_by_hash(conn: sqlite3.Connection, content_hash: str) -> dict | None:
    """Return source file record by content hash, or None if not found."""
    row = conn.execute(
        "SELECT * FROM source_files WHERE file_hash = ?", (content_hash,)
    ).fetchone()
    if row is None:
        return None
    return dict(row)


# ---------------------------------------------------------------------------
# Processing runs
# ---------------------------------------------------------------------------

def create_processing_run(
    conn: sqlite3.Connection, *,
    input_path: str, program_code: str = "",
    total_files: int = 0,
) -> int:
    """Create a new processing run record. Returns the run ID."""
    cur = conn.execute(
        """INSERT INTO processing_runs (input_path, program_code, total_files)
           VALUES (?, ?, ?)""",
        (input_path, program_code, total_files),
    )
    conn.commit()
    return cur.lastrowid


def update_processing_run(
    conn: sqlite3.Connection, run_id: int, *,
    success_count: int = 0, error_count: int = 0,
    notes: str = "",
) -> None:
    """Update a processing run with final counts and completion time."""
    conn.execute(
        """UPDATE processing_runs
           SET completed_at = datetime('now'),
               success_count = ?,
               error_count = ?,
               notes = ?
           WHERE id = ?""",
        (success_count, error_count, notes, run_id),
    )
    conn.commit()


def add_run_file(
    conn: sqlite3.Connection, *,
    run_id: int, source_file_id: int,
    status: str = "success", error_message: str = "",
) -> int:
    """Record a per-file result within a processing run."""
    cur = conn.execute(
        """INSERT INTO run_files (run_id, source_file_id, status, error_message)
           VALUES (?, ?, ?, ?)""",
        (run_id, source_file_id, status, error_message),
    )
    conn.commit()
    return cur.lastrowid


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def get_stats(conn: sqlite3.Connection) -> dict:
    """Return summary statistics for the catalog."""
    stats = {}
    for table in ["programs", "courses", "course_clos", "plo_definitions",
                   "clo_plo_mappings", "source_files", "course_topics"]:
        row = conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()  # noqa: S608
        stats[table] = row["c"]
    # Also include textbooks and assessments
    for table in ["course_textbooks", "course_assessment"]:
        row = conn.execute(f"SELECT COUNT(*) as c FROM {table}").fetchone()  # noqa: S608
        stats[table] = row["c"]
    return stats
