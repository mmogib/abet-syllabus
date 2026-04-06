"""SQLite database schema for the ABET Syllabus catalog."""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 2

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Academic programs (MATH, AS, DATA, etc.)
CREATE TABLE IF NOT EXISTS programs (
    program_code TEXT PRIMARY KEY,
    program_name TEXT NOT NULL DEFAULT ''
);

-- Program Learning Outcomes (also called Student Outcomes / SOs)
CREATE TABLE IF NOT EXISTS plo_definitions (
    id           INTEGER PRIMARY KEY,
    program_code TEXT    NOT NULL REFERENCES programs(program_code) ON DELETE CASCADE,
    plo_code     TEXT    NOT NULL,
    plo_label    TEXT    NOT NULL DEFAULT '',
    plo_description TEXT NOT NULL DEFAULT '',
    sequence     INTEGER NOT NULL DEFAULT 0,
    UNIQUE(program_code, plo_code)
);

-- Courses (stable identity, not term-specific)
CREATE TABLE IF NOT EXISTS courses (
    id                  INTEGER PRIMARY KEY,
    course_code         TEXT NOT NULL,
    course_title        TEXT NOT NULL DEFAULT '',
    department          TEXT NOT NULL DEFAULT '',
    college             TEXT NOT NULL DEFAULT '',
    catalog_description TEXT NOT NULL DEFAULT '',
    credit_hours_raw    TEXT NOT NULL DEFAULT '',
    lecture_credits     INTEGER NOT NULL DEFAULT 0,
    lab_credits         INTEGER NOT NULL DEFAULT 0,
    total_credits       INTEGER NOT NULL DEFAULT 0,
    course_type         TEXT NOT NULL DEFAULT '',
    level               TEXT NOT NULL DEFAULT '',
    prerequisites       TEXT NOT NULL DEFAULT '',
    corequisites        TEXT NOT NULL DEFAULT '',
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(course_code)
);

-- Many-to-many: which programs include this course
CREATE TABLE IF NOT EXISTS course_programs (
    id           INTEGER PRIMARY KEY,
    course_id    INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    program_code TEXT    NOT NULL REFERENCES programs(program_code) ON DELETE CASCADE,
    designation  TEXT    NOT NULL DEFAULT '',
    UNIQUE(course_id, program_code)
);

-- Course Learning Outcomes
CREATE TABLE IF NOT EXISTS course_clos (
    id                INTEGER PRIMARY KEY,
    course_id         INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    clo_code          TEXT    NOT NULL DEFAULT '',
    clo_category      TEXT    NOT NULL DEFAULT '',
    clo_text          TEXT    NOT NULL,
    teaching_strategy TEXT    NOT NULL DEFAULT '',
    assessment_method TEXT    NOT NULL DEFAULT '',
    sequence          INTEGER NOT NULL DEFAULT 0
);

-- CLO-to-PLO mappings (unique per course + program)
CREATE TABLE IF NOT EXISTS clo_plo_mappings (
    id             INTEGER PRIMARY KEY,
    course_clo_id  INTEGER NOT NULL REFERENCES course_clos(id) ON DELETE CASCADE,
    plo_id         INTEGER NOT NULL REFERENCES plo_definitions(id) ON DELETE CASCADE,
    program_code   TEXT    NOT NULL REFERENCES programs(program_code) ON DELETE CASCADE,
    mapping_source TEXT    NOT NULL DEFAULT 'extracted',
    confidence     REAL    NOT NULL DEFAULT 0.0,
    rationale      TEXT    NOT NULL DEFAULT '',
    approved       INTEGER NOT NULL DEFAULT 0,
    approved_at    TEXT,
    UNIQUE(course_clo_id, plo_id, program_code)
);

-- Course topics (lecture and lab)
CREATE TABLE IF NOT EXISTS course_topics (
    id            INTEGER PRIMARY KEY,
    course_id     INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    topic_number  INTEGER NOT NULL DEFAULT 0,
    topic_title   TEXT    NOT NULL,
    contact_hours REAL    NOT NULL DEFAULT 0.0,
    topic_type    TEXT    NOT NULL DEFAULT 'lecture',
    sequence      INTEGER NOT NULL DEFAULT 0
);

-- Textbooks and references
CREATE TABLE IF NOT EXISTS course_textbooks (
    id            INTEGER PRIMARY KEY,
    course_id     INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    textbook_text TEXT    NOT NULL,
    textbook_type TEXT    NOT NULL DEFAULT 'required',
    sequence      INTEGER NOT NULL DEFAULT 0
);

-- Assessment plan
CREATE TABLE IF NOT EXISTS course_assessment (
    id              INTEGER PRIMARY KEY,
    course_id       INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    assessment_task TEXT    NOT NULL,
    week_due        TEXT    NOT NULL DEFAULT '',
    proportion      REAL    NOT NULL DEFAULT 0.0,
    assessment_type TEXT    NOT NULL DEFAULT 'lecture',
    sequence        INTEGER NOT NULL DEFAULT 0
);

-- Credit hours categorization (one row per course)
CREATE TABLE IF NOT EXISTS credit_categorization (
    course_id              INTEGER PRIMARY KEY REFERENCES courses(id) ON DELETE CASCADE,
    engineering_cs         REAL NOT NULL DEFAULT 0.0,
    math_science           REAL NOT NULL DEFAULT 0.0,
    humanities             REAL NOT NULL DEFAULT 0.0,
    social_sciences_business REAL NOT NULL DEFAULT 0.0,
    general_education      REAL NOT NULL DEFAULT 0.0,
    other                  REAL NOT NULL DEFAULT 0.0
);

-- Term-specific instructor assignments
CREATE TABLE IF NOT EXISTS course_instructors (
    id              INTEGER PRIMARY KEY,
    course_id       INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
    instructor_name TEXT    NOT NULL,
    term_code       TEXT    NOT NULL DEFAULT '',
    role            TEXT    NOT NULL DEFAULT 'coordinator',
    UNIQUE(course_id, instructor_name, term_code)
);

-- PLO aliases (alternative codes that map to canonical PLO definitions)
CREATE TABLE IF NOT EXISTS plo_aliases (
    id           INTEGER PRIMARY KEY,
    program_code TEXT NOT NULL REFERENCES programs(program_code) ON DELETE CASCADE,
    alias        TEXT NOT NULL,
    plo_id       INTEGER NOT NULL REFERENCES plo_definitions(id) ON DELETE CASCADE,
    UNIQUE(program_code, alias)
);

-- Source file tracking
CREATE TABLE IF NOT EXISTS source_files (
    id              INTEGER PRIMARY KEY,
    file_path       TEXT    NOT NULL,
    file_name       TEXT    NOT NULL,
    file_extension  TEXT    NOT NULL DEFAULT '',
    file_size       INTEGER NOT NULL DEFAULT 0,
    file_hash       TEXT    NOT NULL UNIQUE,
    format_type     TEXT    NOT NULL DEFAULT '',
    processed_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    course_id       INTEGER REFERENCES courses(id) ON DELETE SET NULL
);

-- Processing runs
CREATE TABLE IF NOT EXISTS processing_runs (
    id             INTEGER PRIMARY KEY,
    started_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    completed_at   TEXT,
    input_path     TEXT    NOT NULL DEFAULT '',
    program_code   TEXT    NOT NULL DEFAULT '',
    total_files    INTEGER NOT NULL DEFAULT 0,
    success_count  INTEGER NOT NULL DEFAULT 0,
    error_count    INTEGER NOT NULL DEFAULT 0,
    notes          TEXT    NOT NULL DEFAULT ''
);

-- Per-file results within a run
CREATE TABLE IF NOT EXISTS run_files (
    id             INTEGER PRIMARY KEY,
    run_id         INTEGER NOT NULL REFERENCES processing_runs(id) ON DELETE CASCADE,
    source_file_id INTEGER NOT NULL REFERENCES source_files(id) ON DELETE CASCADE,
    status         TEXT    NOT NULL DEFAULT 'pending',
    error_message  TEXT    NOT NULL DEFAULT '',
    extracted_text TEXT    NOT NULL DEFAULT '',
    parsed_json    TEXT    NOT NULL DEFAULT ''
);
"""


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Create or open the catalog database and ensure the schema exists."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_SQL)

    # Store schema version
    conn.execute(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        ("schema_version", str(SCHEMA_VERSION)),
    )
    conn.commit()
    return conn


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return the current schema version, or 0 if not set."""
    try:
        row = conn.execute(
            "SELECT value FROM schema_meta WHERE key = 'schema_version'"
        ).fetchone()
        return int(row["value"]) if row else 0
    except sqlite3.OperationalError:
        return 0
