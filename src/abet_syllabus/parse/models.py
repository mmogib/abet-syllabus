"""Parsed data models for the parsing module.

These dataclasses represent the structured output from parsing a course
specification file. They are format-agnostic and map closely to the DB
schema in ``abet_syllabus.db.models``.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ParsedCLO:
    """A single Course Learning Outcome extracted from a specification."""

    clo_code: str  # "1.1", "2.3", "CLO-1"
    clo_text: str
    clo_category: str  # "Knowledge and Understanding" / "Skills" / "Values"
    sequence: int
    teaching_strategy: str | None = None
    assessment_method: str | None = None
    aligned_plos: list[str] = field(default_factory=list)  # ["K1", "S2"]


@dataclass
class ParsedTopic:
    """A single lecture/lab topic extracted from a specification."""

    topic_number: int
    topic_title: str
    contact_hours: float
    topic_type: str = "lecture"  # "lecture" / "lab"


@dataclass
class ParsedTextbook:
    """A textbook or reference extracted from a specification."""

    textbook_text: str
    textbook_type: str = "required"  # "required"/"reference"/"recommended"/"electronic"


@dataclass
class ParsedAssessment:
    """An assessment task extracted from a specification."""

    assessment_task: str
    week_due: str | None = None
    proportion: float | None = None  # percentage value (e.g. 25.0)
    assessment_type: str = "lecture"  # "lecture" / "lab"


@dataclass
class ParsedCourse:
    """Complete parsed result from a course specification file.

    Holds all structured data ready for validation and DB insertion.
    """

    # Identity
    course_code: str = ""  # normalized: "MATH 101"
    course_title: str = ""
    department: str | None = None
    college: str | None = None

    # Credits
    credit_hours_raw: str | None = None  # "4-0-4" or "3-0-3"
    lecture_credits: int | None = None
    lab_credits: int | None = None
    total_credits: int | None = None

    # Description
    catalog_description: str | None = None
    prerequisites: str | None = None
    corequisites: str | None = None

    # Classification
    course_type: str | None = None
    level: str | None = None

    # Structured data
    clos: list[ParsedCLO] = field(default_factory=list)
    topics: list[ParsedTopic] = field(default_factory=list)
    textbooks: list[ParsedTextbook] = field(default_factory=list)
    assessments: list[ParsedAssessment] = field(default_factory=list)

    # Credit categorization
    # Keys: engineering_cs, math_science, humanities, social_sciences_business,
    #        general_education, other
    credit_categorization: dict[str, float] = field(default_factory=dict)

    # Metadata
    format_type: str = ""  # "format_a_pdf" / "format_b_crf2"
    source_file: str = ""
    confidence: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
