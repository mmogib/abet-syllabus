"""Domain dataclasses for the ABET Syllabus catalog."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Program:
    program_code: str
    program_name: str = ""


@dataclass
class PloDefinition:
    id: int | None = None
    program_code: str = ""
    plo_code: str = ""
    plo_label: str = ""
    plo_description: str = ""
    sequence: int = 0


@dataclass
class PloAlias:
    id: int | None = None
    program_code: str = ""
    alias: str = ""
    plo_id: int = 0


@dataclass
class Course:
    id: int | None = None
    course_code: str = ""
    course_title: str = ""
    department: str = ""
    college: str = ""
    catalog_description: str = ""
    credit_hours_raw: str = ""
    lecture_credits: int = 0
    lab_credits: int = 0
    total_credits: int = 0
    course_type: str = ""
    level: str = ""
    prerequisites: str = ""
    corequisites: str = ""


@dataclass
class CourseClo:
    id: int | None = None
    course_id: int = 0
    clo_code: str = ""
    clo_category: str = ""
    clo_text: str = ""
    teaching_strategy: str = ""
    assessment_method: str = ""
    sequence: int = 0


@dataclass
class CloPloMapping:
    id: int | None = None
    course_clo_id: int = 0
    plo_id: int = 0
    program_code: str = ""
    mapping_source: str = "extracted"
    confidence: float = 0.0
    rationale: str = ""
    approved: bool = False
    approved_at: str | None = None


@dataclass
class CourseTopic:
    id: int | None = None
    course_id: int = 0
    topic_number: int = 0
    topic_title: str = ""
    contact_hours: float = 0.0
    topic_type: str = "lecture"
    sequence: int = 0


@dataclass
class CourseTextbook:
    id: int | None = None
    course_id: int = 0
    textbook_text: str = ""
    textbook_type: str = "required"
    sequence: int = 0


@dataclass
class CourseAssessment:
    id: int | None = None
    course_id: int = 0
    assessment_task: str = ""
    week_due: str = ""
    proportion: float = 0.0
    assessment_type: str = "lecture"
    sequence: int = 0


@dataclass
class CreditCategorization:
    course_id: int = 0
    engineering_cs: float = 0.0
    math_science: float = 0.0
    humanities: float = 0.0
    social_sciences_business: float = 0.0
    general_education: float = 0.0
    other: float = 0.0


@dataclass
class CourseInstructor:
    id: int | None = None
    course_id: int = 0
    instructor_name: str = ""
    term_code: str = ""
    role: str = "coordinator"


@dataclass
class ParsedCourse:
    """Complete parsed result from a source file, ready for DB insertion."""
    course: Course = field(default_factory=Course)
    clos: list[CourseClo] = field(default_factory=list)
    topics: list[CourseTopic] = field(default_factory=list)
    textbooks: list[CourseTextbook] = field(default_factory=list)
    assessments: list[CourseAssessment] = field(default_factory=list)
    credit_categorization: CreditCategorization = field(default_factory=CreditCategorization)
    instructors: list[CourseInstructor] = field(default_factory=list)
    programs: list[str] = field(default_factory=list)
    # Raw extracted CLO-PLO mappings from the source (if present)
    extracted_plo_codes: dict[str, list[str]] = field(default_factory=dict)
