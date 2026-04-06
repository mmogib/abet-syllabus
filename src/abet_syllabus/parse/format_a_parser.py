"""Parser for Format A (PDF) course specifications.

Format A is the standard KFUPM "COURSE SPECIFICATIONS" PDF with sections A-H.
Used by external departments: BUS, CGS, COE, ENGL, IAS, ICS, PE, SWE, etc.

The extraction result provides:
- ``raw_text``: full text with section headers, preserving layout
- ``tables``: structured table data (CLOs, topics, assessment, etc.)

Parsing strategy: rules-first (deterministic regex + table analysis).
"""

from __future__ import annotations

import re
from pathlib import Path

from abet_syllabus.extract.models import ExtractionResult, ExtractedTable
from abet_syllabus.parse._common import (
    CATEGORY_KNOWLEDGE,
    CATEGORY_MAP,
    CATEGORY_SKILLS,
    CATEGORY_VALUES,
    clean_text,
    extract_plo_codes,
    normalize_category,
    parse_float,
    parse_percentage,
)
from abet_syllabus.parse.models import (
    ParsedAssessment,
    ParsedCLO,
    ParsedCourse,
    ParsedTextbook,
    ParsedTopic,
)
from abet_syllabus.parse.normalize import (
    extract_course_code_from_filename,
    normalize_course_code,
)


# ---------------------------------------------------------------------------
# Section extraction from raw text
# ---------------------------------------------------------------------------

_SECTION_RE = re.compile(
    r"^([A-H])\.\s+(.+?)(?:\n|$)",
    re.MULTILINE,
)


def _split_sections(raw_text: str) -> dict[str, str]:
    """Split the raw text into sections A-H.

    Returns a dict mapping section letter (uppercase) to the text content
    of that section (from the section header to the next section or EOF).
    """
    positions: list[tuple[int, str]] = []
    for m in _SECTION_RE.finditer(raw_text):
        positions.append((m.start(), m.group(1).upper()))

    if not positions:
        return {}

    sections: dict[str, str] = {}
    for i, (start, letter) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(raw_text)
        sections[letter] = raw_text[start:end]

    return sections


# ---------------------------------------------------------------------------
# Identity parsing from raw text
# ---------------------------------------------------------------------------

def _parse_identity_from_text(raw_text: str, result: ExtractionResult) -> dict:
    """Extract course identity fields from the raw text header."""
    info: dict = {}

    # Course Title line: "Course Title <value>"
    m = re.search(r"Course\s+Title\s+(.+?)(?:\n|$)", raw_text, re.IGNORECASE)
    if m:
        info["course_title"] = m.group(1).strip()

    # Course Code line: "Course Code <value>"
    m = re.search(r"Course\s+Code\s+(\S+)", raw_text, re.IGNORECASE)
    if m:
        info["course_code"] = m.group(1).strip()

    # Program
    m = re.search(r"^Program\s+(\S+)", raw_text, re.MULTILINE | re.IGNORECASE)
    if m:
        info["program"] = m.group(1).strip()

    # Department
    m = re.search(r"Department\s+(.+?)(?:\n|$)", raw_text, re.IGNORECASE)
    if m:
        info["department"] = m.group(1).strip()

    # College
    m = re.search(r"College\s+(.+?)(?:\n|$)", raw_text, re.IGNORECASE)
    if m:
        info["college"] = m.group(1).strip()

    return info


def _parse_identity_from_tables(tables: list[ExtractedTable]) -> dict:
    """Extract course identity from the first identity table (Format A).

    Format A typically has a small table at the top:
        Course Code | BUS200
        Program     | BUS
        Department  | ...
        College     | ...
    """
    info: dict = {}
    if not tables:
        return info

    for table in tables[:3]:  # Check first few tables
        for row in table.rows:
            if len(row) < 2:
                continue
            key = row[0].strip().lower()
            val = row[1].strip()
            if not val:
                continue
            if "course code" in key:
                info["course_code"] = val
            elif "course title" in key:
                info["course_title"] = val
            elif key == "program":
                info["program"] = val
            elif "department" in key:
                info["department"] = val
            elif "college" in key:
                info["college"] = val
    return info


# ---------------------------------------------------------------------------
# Credit hours parsing
# ---------------------------------------------------------------------------

_CREDIT_RE = re.compile(r"(\d+)\s*[-\u2013]\s*(\d+)\s*[-\u2013]\s*(\d+)")


def _parse_credits_from_text(section_text: str) -> dict:
    """Parse credit hours from section A text.

    Looks for patterns like "3-0-3" (lecture-lab-total).
    """
    info: dict = {}
    m = _CREDIT_RE.search(section_text)
    if m:
        lec = int(m.group(1))
        lab = int(m.group(2))
        total = int(m.group(3))
        info["credit_hours_raw"] = f"{lec}-{lab}-{total}"
        info["lecture_credits"] = lec
        info["lab_credits"] = lab
        info["total_credits"] = total
    return info


def _parse_credits_from_tables(tables: list[ExtractedTable]) -> dict:
    """Parse credits from the contact/credit hours table.

    Looks for a table with rows like:
        Credit Hours | 3 | 0 | 0 | 0 | 3
    """
    info: dict = {}
    for table in tables:
        for row in table.rows:
            joined = " ".join(c.strip() for c in row).lower()
            if "credit hours" in joined and len(row) >= 4:
                # Try to extract numeric values
                nums = []
                for cell in row[1:]:
                    cell_stripped = cell.strip()
                    try:
                        nums.append(int(float(cell_stripped)))
                    except (ValueError, TypeError):
                        pass
                if len(nums) >= 3:
                    # Typical: lecture, lab/studio, tutorial, other, total
                    info["lecture_credits"] = nums[0]
                    info["lab_credits"] = nums[1]
                    info["total_credits"] = nums[-1]
                    info["credit_hours_raw"] = f"{nums[0]}-{nums[1]}-{nums[-1]}"
                    return info
    return info


# ---------------------------------------------------------------------------
# Prerequisites / corequisites
# ---------------------------------------------------------------------------

def _parse_prereqs(raw_text: str) -> dict:
    """Extract prerequisites and corequisites from raw text."""
    info: dict = {}

    # Prerequisites
    m = re.search(
        r"(?:Pre-?requisites?|Pre-?reqs?)(?:\s*(?:for this course)?\s*:?\s*)\n?\s*(.+?)(?:\n\d|\n[A-Z]\.|\nCo)",
        raw_text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        val = m.group(1).strip()
        if val.lower() not in ("none", "n/a", ""):
            info["prerequisites"] = val

    # Corequisites
    m = re.search(
        r"Co-?requisites?(?:\s*(?:for this course)?\s*:?\s*)\n?\s*(.+?)(?:\n\d|\n[A-Z]\.|\n(?:Not|Other))",
        raw_text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        val = m.group(1).strip()
        if val.lower() not in ("none", "n/a", ""):
            info["corequisites"] = val

    return info


# ---------------------------------------------------------------------------
# Catalog description
# ---------------------------------------------------------------------------

def _parse_catalog_description(sections: dict[str, str], raw_text: str) -> str | None:
    """Extract the catalog description from section B."""
    section_b = sections.get("B", "")
    if not section_b:
        # Try to find it in raw text
        m = re.search(
            r"(?:Catalog\s+)?(?:Course\s+)?Description\s*:\s*\n(.+?)(?:\n\s*\d+\.\s*Course\s+Main|\n[A-Z]\.)",
            raw_text,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            return clean_text(m.group(1))
        return None

    m = re.search(
        r"(?:Catalog\s+)?(?:Course\s+)?Description\s*:\s*\n(.+?)(?:\n\s*\d+\.\s*Course\s+Main|\n[A-Z]\.)",
        section_b,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return clean_text(m.group(1))
    return None


# ---------------------------------------------------------------------------
# CLO parsing
# ---------------------------------------------------------------------------

def _is_category_row(row: list[str]) -> str | None:
    """Check if a table row is a CLO category header.

    Returns the canonical category name, or None.
    """
    # A category row typically has a single-digit code in col 0
    # and a category name in col 1.
    if len(row) < 2:
        return None
    code = row[0].strip()
    text = row[1].strip().lower().rstrip(".")
    if code in ("1", "2", "3") and text in CATEGORY_MAP:
        return normalize_category(text)
    return None


def _is_clo_row(row: list[str]) -> bool:
    """Check if a table row contains a CLO entry (not a header/category)."""
    if len(row) < 2:
        return False
    code = row[0].strip()
    # CLO codes look like "1.1", "2.3", "3.1", etc.
    # But NOT things like "45.00" (numeric values from other tables)
    if not re.match(r"^\d+\.\d+$", code):
        return False
    # The prefix should be a small number (1-9), not a large number
    prefix = code.split(".")[0]
    if int(prefix) > 9:
        return False
    # The CLO text column should have actual text (not just a number)
    text = row[1].strip()
    if not text or re.match(r"^[\d.]+$", text):
        return False
    return True


def _parse_clos_from_tables(tables: list[ExtractedTable]) -> list[ParsedCLO]:
    """Extract CLOs from the CLO tables.

    Format A typically has two CLO-related tables:
    1. Section B.3 table -- CLO Code | CLO Text | PLO's Code (3 cols)
    2. Section D.1 table -- CLO Code | CLO Text | Teaching Strategy | Assessment Method (4 cols)

    We try to merge data from both.
    """
    # Find CLO tables: tables with rows matching CLO code pattern
    clo_tables: list[ExtractedTable] = []
    for table in tables:
        clo_row_count = sum(1 for row in table.rows if _is_clo_row(row))
        if clo_row_count >= 1:
            clo_tables.append(table)

    if not clo_tables:
        return []

    # Build CLO entries from each table, keyed by code
    clo_map: dict[str, dict] = {}
    sequence = 0

    for table in clo_tables:
        current_category = CATEGORY_KNOWLEDGE  # default

        for row in table.rows:
            # Check for category header
            cat = _is_category_row(row)
            if cat is not None:
                current_category = cat
                continue

            if not _is_clo_row(row):
                continue

            code = row[0].strip()
            text = clean_text(row[1]) if len(row) > 1 else ""

            if code not in clo_map:
                sequence += 1
                clo_map[code] = {
                    "clo_code": code,
                    "clo_text": text,
                    "clo_category": current_category,
                    "sequence": sequence,
                    "teaching_strategy": None,
                    "assessment_method": None,
                    "aligned_plos": [],
                }

            entry = clo_map[code]

            # Update text if we got a better (longer) version
            if text and len(text) > len(entry["clo_text"]):
                entry["clo_text"] = text

            # Extract PLO codes (3-column table)
            if len(row) == 3:
                plo_raw = row[2].strip()
                if plo_raw and plo_raw.lower() not in ("", "plo", "plo's code"):
                    plos = extract_plo_codes(plo_raw)
                    if plos and not entry["aligned_plos"]:
                        entry["aligned_plos"] = plos

            # Extract teaching strategy and assessment (4-column table)
            if len(row) >= 4:
                strat = clean_text(row[2]) if len(row) > 2 else None
                assess = clean_text(row[3]) if len(row) > 3 else None
                if strat and not entry["teaching_strategy"]:
                    entry["teaching_strategy"] = strat
                if assess and not entry["assessment_method"]:
                    entry["assessment_method"] = assess

    # Determine category from CLO code prefix if not set by headers
    for code, entry in clo_map.items():
        prefix = code.split(".")[0] if "." in code else ""
        if prefix == "1" and entry["clo_category"] == CATEGORY_KNOWLEDGE:
            pass  # Already correct
        elif prefix == "2":
            if entry["clo_category"] == CATEGORY_KNOWLEDGE:
                entry["clo_category"] = CATEGORY_SKILLS
        elif prefix == "3":
            if entry["clo_category"] == CATEGORY_KNOWLEDGE:
                entry["clo_category"] = CATEGORY_VALUES

    return [
        ParsedCLO(**entry)
        for entry in sorted(clo_map.values(), key=lambda e: e["sequence"])
    ]


# ---------------------------------------------------------------------------
# Topics parsing
# ---------------------------------------------------------------------------

def _parse_topics_from_tables(tables: list[ExtractedTable]) -> list[ParsedTopic]:
    """Extract topics from tables.

    Look for tables with rows like: [number, topic_title, contact_hours]
    where the number is sequential starting from 1.
    """
    topics: list[ParsedTopic] = []

    for table in tables:
        # Check if this table looks like a topics table
        candidate_topics: list[ParsedTopic] = []
        for row in table.rows:
            if len(row) < 3:
                continue
            num_str = row[0].strip()
            title = clean_text(row[1])
            hours_str = row[-1].strip()  # Last column is usually hours

            # Skip header rows and total rows
            if num_str.lower() in ("no", "total", ""):
                continue
            if "topic" in num_str.lower() or "contact" in num_str.lower():
                continue

            try:
                num = int(num_str)
            except ValueError:
                continue

            hours = parse_float(hours_str)
            if hours is None or hours <= 0:
                continue

            if not title:
                continue

            candidate_topics.append(ParsedTopic(
                topic_number=num,
                topic_title=title,
                contact_hours=hours,
                topic_type="lecture",
            ))

        # Accept this table as topics if it has sequential entries
        if len(candidate_topics) >= 3:
            # Determine topic type from context
            topic_type = "lecture"
            # Check if any row mentions "lab" in the table context
            for row in table.rows:
                joined = " ".join(row).lower()
                if "lab" in joined and "topic" not in joined:
                    topic_type = "lab"
                    break

            for t in candidate_topics:
                t.topic_type = topic_type

            topics.extend(candidate_topics)

    return topics


# ---------------------------------------------------------------------------
# Assessment parsing
# ---------------------------------------------------------------------------

def _parse_assessments_from_tables(
    tables: list[ExtractedTable],
) -> list[ParsedAssessment]:
    """Extract assessment tasks from tables.

    Look for tables with rows like: [task, week_due, proportion]
    """
    assessments: list[ParsedAssessment] = []

    # Detect if there are separate lecture and lab assessment sections
    # by checking the raw text between tables
    for table in tables:
        candidate: list[ParsedAssessment] = []
        has_percentage = False
        assessment_type = "lecture"

        for row in table.rows:
            if len(row) < 3:
                continue

            # Try different column layouts
            # Layout 1: [task, week, proportion] (3 cols)
            # Layout 2: [number, task, week, proportion] (4 cols)
            if len(row) >= 4:
                # Check if first col is a number
                try:
                    int(row[0].strip())
                    task = clean_text(row[1])
                    week = row[2].strip() if len(row) > 2 else None
                    prop_str = row[3].strip() if len(row) > 3 else ""
                except ValueError:
                    task = clean_text(row[0])
                    week = row[1].strip() if len(row) > 1 else None
                    prop_str = row[2].strip() if len(row) > 2 else ""
            else:
                task = clean_text(row[0])
                week = row[1].strip() if len(row) > 1 else None
                prop_str = row[2].strip() if len(row) > 2 else ""

            if not task:
                continue

            # Skip header-like rows
            task_lower = task.lower()
            if any(
                kw in task_lower
                for kw in ("assessment task", "assessment activities", "total")
            ):
                continue
            if "e.g.," in task_lower or "proportion" in task_lower:
                continue

            prop = parse_percentage(prop_str)
            if prop is not None:
                has_percentage = True

            if week and week.lower() in ("week due", ""):
                week = None

            # Detect lab assessments by task name
            a_type = assessment_type
            if any(
                kw in task_lower
                for kw in ("lab ", "lab\t", "project")
            ):
                a_type = "lab"

            candidate.append(ParsedAssessment(
                assessment_task=task,
                week_due=week if week else None,
                proportion=prop,
                assessment_type=a_type,
            ))

        if candidate and has_percentage:
            assessments.extend(candidate)

    return assessments


# ---------------------------------------------------------------------------
# Textbook parsing
# ---------------------------------------------------------------------------

def _parse_textbooks_from_text(raw_text: str) -> list[ParsedTextbook]:
    """Extract textbooks from the raw text (section F).

    Format A textbooks appear in the text as:
        F. LEARNING RESOURCES:
        1. Required Textbooks:
        <bullet> textbook text
        2. Essential References Materials:
        ...
    """
    textbooks: list[ParsedTextbook] = []

    # Find section F
    m = re.search(
        r"F\.\s+LEARNING\s+RESOURCES\s*:?\s*\n(.+?)(?:\nG\.\s|\Z)",
        raw_text,
        re.IGNORECASE | re.DOTALL,
    )
    if not m:
        return textbooks

    section_f = m.group(1)

    # Required Textbooks
    _extract_textbook_section(
        section_f,
        r"Required\s+Textbooks?\s*:\s*\n(.+?)(?:\n\s*\d+\.\s|\Z)",
        "required",
        textbooks,
    )

    # Essential References
    _extract_textbook_section(
        section_f,
        r"Essential\s+References?\s+Materials?\s*:\s*\n(.+?)(?:\n\s*\d+\.\s|\Z)",
        "reference",
        textbooks,
    )

    # Recommended
    _extract_textbook_section(
        section_f,
        r"Recommended\s+(?:Reference\s+)?Materials?\s*:\s*\n(.+?)(?:\n\s*\d+\.\s|\Z)",
        "recommended",
        textbooks,
    )

    # Electronic Material
    _extract_textbook_section(
        section_f,
        r"Electronic\s+Materials?\s*:\s*\n(.+?)(?:\n\s*\d+\.\s|\Z)",
        "electronic",
        textbooks,
    )

    return textbooks


def _extract_textbook_section(
    text: str,
    pattern: str,
    book_type: str,
    textbooks: list[ParsedTextbook],
) -> None:
    """Helper to extract textbooks from a subsection."""
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if not m:
        return
    content = m.group(1).strip()
    if content.lower() in ("none", "n/a", ""):
        return

    # Split on bullet points or newlines.
    # The bullet character may be \u2022 (bullet), \u25cf (circle),
    # a hyphen, or other Unicode bullet variants.
    lines = re.split(r"\n\s*[\u2022\u25cf\u2023\u25e6\u2043\u2219\-]\s*", content)
    for line in lines:
        line = clean_text(line)
        if line and line.lower() not in ("none", "n/a"):
            textbooks.append(ParsedTextbook(
                textbook_text=line,
                textbook_type=book_type,
            ))


# ---------------------------------------------------------------------------
# Credit categorization
# ---------------------------------------------------------------------------

_CREDIT_CAT_RE = re.compile(
    r"Subject\s+Area\s+Credit\s+Hours\s*:\s*\n"
    r".*?"                          # category labels line 1 (may span lines)
    r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\n"  # val1, val2, val3
    r".*?"                          # category labels line 2 (may span lines)
    r"([\d.]+)\s+([\d.]+)\s+([\d.]+)",      # val4, val5, val6
    re.DOTALL | re.IGNORECASE,
)


def _parse_credit_categorization(raw_text: str) -> dict[str, float]:
    """Extract credit categorization from Format A raw text.

    The pattern in the raw text (with pdfplumber line breaks) is::

        Subject Area Credit Hours:
        Engineering / Computer
        Science Mathematics/Science Humanities
        <val1> <val2> <val3>
        Social Sciences and
        Business General Education Other Subject Areas
        <val4> <val5> <val6>

    Mapping:
        val1 = engineering_cs
        val2 = math_science
        val3 = humanities
        val4 = social_sciences_business
        val5 = general_education
        val6 = other
    """
    m = _CREDIT_CAT_RE.search(raw_text)
    if not m:
        return {}

    try:
        return {
            "engineering_cs": float(m.group(1)),
            "math_science": float(m.group(2)),
            "humanities": float(m.group(3)),
            "social_sciences_business": float(m.group(4)),
            "general_education": float(m.group(5)),
            "other": float(m.group(6)),
        }
    except (ValueError, IndexError):
        return {}


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_format_a(result: ExtractionResult) -> ParsedCourse:
    """Parse a Format A (PDF) extraction result into a ParsedCourse.

    Args:
        result: ExtractionResult from a Format A PDF.

    Returns:
        ParsedCourse with all extracted fields populated.
    """
    course = ParsedCourse(
        format_type="format_a_pdf",
        source_file=result.file_path,
    )

    raw = result.raw_text
    tables = result.tables
    sections = _split_sections(raw)

    # --- Identity ---
    text_info = _parse_identity_from_text(raw, result)
    table_info = _parse_identity_from_tables(tables)

    # Prefer table data for code (more structured), text for title
    code_raw = table_info.get("course_code") or text_info.get("course_code", "")
    if code_raw:
        course.course_code = normalize_course_code(code_raw)
        course.confidence["course_code"] = 0.9
    else:
        # Fallback to filename
        filename = Path(result.file_path).name
        code_from_file = extract_course_code_from_filename(filename)
        if code_from_file:
            course.course_code = code_from_file
            course.confidence["course_code"] = 0.6
            course.warnings.append("Course code extracted from filename (fallback)")

    course.course_title = (
        text_info.get("course_title")
        or table_info.get("course_title", "")
    )
    if course.course_title:
        course.confidence["course_title"] = 0.9

    course.department = (
        table_info.get("department")
        or text_info.get("department")
    )
    course.college = (
        table_info.get("college")
        or text_info.get("college")
    )

    # --- Credits ---
    credit_info: dict = {}
    if "A" in sections:
        credit_info = _parse_credits_from_text(sections["A"])
    if not credit_info:
        credit_info = _parse_credits_from_text(raw)
    table_credits = _parse_credits_from_tables(tables)
    # Merge: prefer text if available (it's the "x-y-z" notation), table for nums
    if credit_info.get("credit_hours_raw"):
        course.credit_hours_raw = credit_info["credit_hours_raw"]
        course.lecture_credits = credit_info.get("lecture_credits")
        course.lab_credits = credit_info.get("lab_credits")
        course.total_credits = credit_info.get("total_credits")
        course.confidence["credits"] = 0.9
    elif table_credits:
        course.credit_hours_raw = table_credits.get("credit_hours_raw")
        course.lecture_credits = table_credits.get("lecture_credits")
        course.lab_credits = table_credits.get("lab_credits")
        course.total_credits = table_credits.get("total_credits")
        course.confidence["credits"] = 0.8

    # --- Prerequisites / Corequisites ---
    prereq_info = _parse_prereqs(raw)
    course.prerequisites = prereq_info.get("prerequisites")
    course.corequisites = prereq_info.get("corequisites")

    # --- Catalog Description ---
    course.catalog_description = _parse_catalog_description(sections, raw)
    if course.catalog_description:
        course.confidence["catalog_description"] = 0.85

    # --- CLOs ---
    course.clos = _parse_clos_from_tables(tables)
    if course.clos:
        course.confidence["clos"] = 0.9
    else:
        course.warnings.append("No CLOs found in tables")

    # --- Topics ---
    course.topics = _parse_topics_from_tables(tables)
    if course.topics:
        course.confidence["topics"] = 0.85
    else:
        course.warnings.append("No topics found in tables")

    # --- Textbooks ---
    course.textbooks = _parse_textbooks_from_text(raw)
    if course.textbooks:
        course.confidence["textbooks"] = 0.8

    # --- Assessment ---
    course.assessments = _parse_assessments_from_tables(tables)
    if course.assessments:
        course.confidence["assessments"] = 0.8

    # --- Credit Categorization ---
    course.credit_categorization = _parse_credit_categorization(raw)
    if course.credit_categorization:
        course.confidence["credit_categorization"] = 0.9

    return course
