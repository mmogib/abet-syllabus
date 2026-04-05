"""Assemble all data needed to fill the ABET syllabus template."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from abet_syllabus.db import repository as repo
from abet_syllabus.db.schema import init_db


@dataclass
class SyllabusCLO:
    """A CLO renumbered for syllabus output."""
    label: str         # "CLO-1", "CLO-2", ...
    text: str
    category: str
    original_code: str  # e.g. "1.1", "K1", etc.
    clo_db_id: int = 0


@dataclass
class SyllabusTopic:
    """A course topic for the syllabus."""
    number: int
    title: str
    contact_hours: float


@dataclass
class SyllabusTextbook:
    """A textbook entry with type metadata for the syllabus."""
    text: str
    textbook_type: str  # "required" / "reference" / "recommended" / "electronic"


@dataclass
class SyllabusAssessment:
    """An assessment item for the syllabus."""
    task: str
    week_due: str
    proportion: float


@dataclass
class SyllabusData:
    """All data needed to fill the ABET syllabus template."""
    course_code: str = ""
    course_title: str = ""
    department: str = ""
    college: str = ""
    credit_hours: str = ""        # "3-0-3" or raw format
    lecture_credits: int = 0
    lab_credits: int = 0
    total_credits: int = 0
    catalog_description: str = ""
    prerequisites: str = ""
    corequisites: str = ""
    course_type: str = ""         # "Required" / "Elective" / etc.
    instructor_name: str = ""     # may be empty
    term_code: str = ""           # "T252"

    clos: list[SyllabusCLO] = field(default_factory=list)
    topics: list[SyllabusTopic] = field(default_factory=list)
    textbooks: list[SyllabusTextbook] = field(default_factory=list)
    assessments: list[SyllabusAssessment] = field(default_factory=list)

    # CLO-SO matrix data: list of dicts
    # Each: {"clo_label": "CLO-1", "so_mappings": {"SO-1": True, "SO-3": True}}
    clo_so_matrix: list[dict] = field(default_factory=list)

    # Credit categorization
    credit_categories: dict[str, float] = field(default_factory=dict)


def _renumber_clos(db_clos: list) -> list[SyllabusCLO]:
    """Convert hierarchical CLO codes (1.1, 2.1, K1) to flat CLO-1, CLO-2, ..."""
    result = []
    for i, clo in enumerate(db_clos, start=1):
        result.append(SyllabusCLO(
            label=f"CLO-{i}",
            text=clo.clo_text,
            category=clo.clo_category,
            original_code=clo.clo_code,
            clo_db_id=clo.id or 0,
        ))
    return result


def _build_clo_so_matrix(
    clos: list[SyllabusCLO],
    mappings: list[dict],
    plo_labels: list[str],
) -> list[dict]:
    """Build CLO-SO mapping matrix for the output.

    Maps internal CLO IDs to renumbered CLO labels and uses PLO labels
    as SO column headers.
    """
    # Build lookup: clo_db_id -> clo_label
    clo_id_to_label = {c.clo_db_id: c.label for c in clos}

    # Build lookup: clo_db_id -> set of plo_labels
    clo_plo_map: dict[int, set[str]] = {}
    for m in mappings:
        clo_id = m.get("course_clo_id")
        plo_label = m.get("plo_label", "")
        if clo_id and plo_label:
            clo_plo_map.setdefault(clo_id, set()).add(plo_label)

    result = []
    for clo in clos:
        so_mappings = {}
        mapped_plos = clo_plo_map.get(clo.clo_db_id, set())
        for plo_label in plo_labels:
            # Convert PLO label to SO label (e.g. "1" -> "SO-1", "a" -> "SO-a")
            so_label = f"SO-{plo_label}" if not plo_label.startswith("SO-") else plo_label
            so_mappings[so_label] = plo_label in mapped_plos
        result.append({
            "clo_label": clo.label,
            "so_mappings": so_mappings,
        })
    return result


def assemble_syllabus_data(
    db_path: str | Path,
    course_code: str,
    program_code: str | None = None,
    term: str | None = None,
    instructor: str | None = None,
) -> SyllabusData:
    """Pull all data from DB and assemble into SyllabusData.

    Args:
        db_path: Path to the SQLite database.
        course_code: Course code (e.g. "MATH 101").
        program_code: Optional program code for CLO-SO mappings.
        term: Optional term code (e.g. "T252").
        instructor: Optional instructor name override.

    Returns:
        SyllabusData with all fields populated from the database.

    Raises:
        ValueError: If the course is not found in the database.
    """
    conn = init_db(str(db_path))
    try:
        return _assemble_from_conn(conn, course_code, program_code, term, instructor)
    finally:
        conn.close()


def _assemble_from_conn(
    conn,
    course_code: str,
    program_code: str | None,
    term: str | None,
    instructor: str | None,
) -> SyllabusData:
    """Internal assembly using an open connection."""
    # Fetch course
    course = repo.get_course(conn, course_code.upper())
    if course is None:
        raise ValueError(f"Course not found: {course_code}")

    course_id = course.id

    # Fetch CLOs and renumber
    db_clos = repo.get_course_clos(conn, course_id)
    clos = _renumber_clos(db_clos)

    # Fetch topics
    db_topics = repo.get_course_topics(conn, course_id)
    topics = [
        SyllabusTopic(
            number=t.topic_number,
            title=t.topic_title,
            contact_hours=t.contact_hours,
        )
        for t in db_topics
    ]

    # Fetch textbooks (preserving type metadata)
    db_textbooks = repo.get_course_textbooks(conn, course_id)
    textbooks = [
        SyllabusTextbook(
            text=tb.textbook_text,
            textbook_type=tb.textbook_type,
        )
        for tb in db_textbooks
    ]

    # Fetch assessments
    db_assessments = repo.get_course_assessments(conn, course_id)
    assessments = [
        SyllabusAssessment(
            task=a.assessment_task,
            week_due=a.week_due,
            proportion=a.proportion,
        )
        for a in db_assessments
    ]

    # Build CLO-SO matrix if program is specified
    clo_so_matrix = []
    if program_code and clos:
        plos = repo.get_plos_for_program(conn, program_code)
        plo_labels = [p.plo_label for p in plos]
        mappings = repo.get_mappings_for_course(conn, course_id, program_code)
        clo_so_matrix = _build_clo_so_matrix(clos, mappings, plo_labels)

    # Credit categorization
    credit_categories = _get_credit_categories(conn, course_id)

    # Instructor: use override, or look up from DB
    instr_name = instructor or ""
    if not instr_name and term:
        instr_name = _get_instructor(conn, course_id, term)

    data = SyllabusData(
        course_code=course.course_code,
        course_title=course.course_title,
        department=course.department,
        college=course.college,
        credit_hours=course.credit_hours_raw or f"{course.lecture_credits}-{course.lab_credits}-{course.total_credits}",
        lecture_credits=course.lecture_credits,
        lab_credits=course.lab_credits,
        total_credits=course.total_credits,
        catalog_description=course.catalog_description,
        prerequisites=course.prerequisites,
        corequisites=course.corequisites,
        course_type=course.course_type,
        instructor_name=instr_name,
        term_code=term or "",
        clos=clos,
        topics=topics,
        textbooks=textbooks,
        assessments=assessments,
        clo_so_matrix=clo_so_matrix,
        credit_categories=credit_categories,
    )
    return data


def _get_credit_categories(conn, course_id: int) -> dict:
    """Fetch credit categorization from DB."""
    row = conn.execute(
        "SELECT * FROM credit_categorization WHERE course_id = ?",
        (course_id,),
    ).fetchone()
    if not row:
        return {}
    return {
        "math_science": row["math_science"],
        "engineering_cs": row["engineering_cs"],
        "humanities": row["humanities"],
        "social_sciences_business": row["social_sciences_business"],
        "general_education": row["general_education"],
        "other": row["other"],
    }


def _get_instructor(conn, course_id: int, term_code: str) -> str:
    """Look up instructor name from DB for the given term."""
    row = conn.execute(
        "SELECT instructor_name FROM course_instructors WHERE course_id = ? AND term_code = ? LIMIT 1",
        (course_id, term_code),
    ).fetchone()
    return row["instructor_name"] if row else ""
