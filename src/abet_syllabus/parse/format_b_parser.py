"""Parser for Format B (DOCX CRF2) course specifications.

Format B is the "CRF2. COURSE SPECIFICATIONS" DOCX used by MATH, AS, and
DATA departments. Key characteristics:
- Almost all content is in tables (raw_text is typically < 500 chars)
- Consistent table structure across files
- CLO table has merged cells resulting in duplicated column values
- Course identity may use Structured Document Tags (SDTs / content controls)

Typical table layout (19 tables):
    0  - Course identity (title, code, program, dept, college)
    1  - Checklist
    2  - Approval data
    3  - Section A header
    4  - Course identification fields (credits, prereqs, etc.)
    5  - Section B header
    6  - Catalog description
    7  - Course objectives
    8  - CLO table (map CLOs to PLOs, with teaching/assessment)
    9  - Topics table (or blank if merged into table 8)
    10 - Section D header
    11 - Assessment activities table
    12 - Section E header
    13 - Office hours
    14 - Section F header
    15 - Textbooks/references
    16 - Facilities
    17 - Section G header
    18 - Course quality assessment
"""

from __future__ import annotations

import re
from pathlib import Path

from abet_syllabus.extract.models import ExtractionResult, ExtractedTable
from abet_syllabus.parse._common import (
    CATEGORY_KNOWLEDGE,
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
# Identity parsing
# ---------------------------------------------------------------------------

def _parse_identity_from_tables(tables: list[ExtractedTable]) -> dict:
    """Extract course identity from the identity table (table 0).

    Format B table 0 typically has single-cell rows like:
        ["Course Title: Calculus I"]
        ["Course Code: Math 101"]
        ["Program: BS Mathematics"]
        ["Department: Mathematics"]
        ["College: Computing and Mathematics"]

    Note: values may be empty if the instructor did not fill them in,
    or may be hidden inside SDTs (handled by the extractor).
    """
    info: dict = {}
    if not tables:
        return info

    # Search ALL tables (not just table 0) for identity fields
    for table in tables[:3]:
        for row in table.rows:
            if not row:
                continue
            cell = row[0].strip()

            # Course Title
            m = re.match(r"Course\s+Title\s*:\s*(.*)", cell, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if val and "course_title" not in info:
                    info["course_title"] = val
                continue

            # Course Code
            m = re.match(r"Course\s+Code\s*:\s*(.*)", cell, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if val and "course_code" not in info:
                    info["course_code"] = val
                continue

            # Program
            m = re.match(r"Program\s*:\s*(.*)", cell, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if val and "program" not in info:
                    info["program"] = val
                continue

            # Department
            m = re.match(r"Department\s*:\s*(.*)", cell, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if val and "department" not in info:
                    info["department"] = val
                continue

            # College
            m = re.match(r"College\s*:\s*(.*)", cell, re.IGNORECASE)
            if m:
                val = m.group(1).strip()
                if val and "college" not in info:
                    info["college"] = val
                continue

            # Also check multi-column rows where col0=label, col1=value
            if len(row) >= 2:
                key = row[0].strip().lower()
                val = row[1].strip()
                if not val:
                    continue
                if "course title" in key and "course_title" not in info:
                    info["course_title"] = val
                elif "course code" in key and "course_code" not in info:
                    info["course_code"] = val
                elif key == "program" and "program" not in info:
                    info["program"] = val
                elif "department" in key and "department" not in info:
                    info["department"] = val
                elif "college" in key and "college" not in info:
                    info["college"] = val

    return info


# ---------------------------------------------------------------------------
# Course identification fields (table 4)
# ---------------------------------------------------------------------------

def _parse_course_id_table(tables: list[ExtractedTable]) -> dict:
    """Parse course identification fields from the section A table.

    Table 4 contains single-cell rows like:
        "1.  Course Credit Hours: 4-0-4"
        "2.  Course Type: Required  Department"
        "4.  Pre-requisites for this course (if any): STAT 201 and ..."
    """
    info: dict = {}

    # Find the course identification table
    id_table = None
    for table in tables:
        for row in table.rows:
            if not row:
                continue
            cell = row[0].strip()
            if re.match(r"1\.\s+Course\s+Credit\s+Hours", cell, re.IGNORECASE):
                id_table = table
                break
            # Also handle field experience format
            if re.match(r"1\.\s+Credit\s+hours\s*:", cell, re.IGNORECASE):
                id_table = table
                break
        if id_table:
            break

    if not id_table:
        return info

    for row in id_table.rows:
        if not row:
            continue
        cell = row[0].strip()

        # Credit Hours (standard format)
        m = re.match(
            r"1\.\s+Course\s+Credit\s+Hours\s*:\s*(.*)",
            cell, re.IGNORECASE,
        )
        if m:
            val = m.group(1).strip()
            if val:
                info["credit_hours_raw"] = val
            continue

        # Credit Hours (field experience format: "1. Credit hours: (0-0-1).")
        m = re.match(
            r"1\.\s+Credit\s+hours\s*:\s*(.*)",
            cell, re.IGNORECASE,
        )
        if m:
            val = m.group(1).strip()
            if val:
                # Extract from parenthesized format: "(0-0-1)."
                m2 = re.search(r"\(?\s*(\d+)\s*[-–]\s*(\d+)\s*[-–]\s*(\d+)\s*\)?", val)
                if m2:
                    info["credit_hours_raw"] = f"{m2.group(1)}-{m2.group(2)}-{m2.group(3)}"
                else:
                    info["credit_hours_raw"] = val
            continue

        # Course Type
        m = re.match(r"2\.\s+Course\s+Type\s*:\s*(.*)", cell, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            if val:
                info["course_type"] = val
            continue

        # Level
        m = re.match(
            r"3\.\s+Level\s+at\s+which.*?:\s*(.*)",
            cell,
            re.IGNORECASE,
        )
        if m:
            val = m.group(1).strip()
            if val:
                info["level"] = val
            continue

        # Prerequisites
        m = re.match(
            r"4\.\s+Pre-?requisites?\s+for\s+this\s+course.*?:\s*(.*)",
            cell,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            val = clean_text(m.group(1))
            if val and val.lower() not in ("none", "n/a", ""):
                info["prerequisites"] = val
            continue

        # Corequisites
        m = re.match(
            r"5\.\s+Co-?requisites?\s+for\s+this\s+course.*?:\s*(.*)",
            cell,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            val = clean_text(m.group(1))
            if val and val.lower() not in ("none", "n/a", ""):
                info["corequisites"] = val
            continue

        # Also handle field experience corequisites
        m = re.match(
            r"4\.\s+Corequisite.*?:\s*(.*)",
            cell,
            re.IGNORECASE | re.DOTALL,
        )
        if m:
            val = clean_text(m.group(1))
            if val and val.lower() not in ("none", "n/a", ""):
                info.setdefault("corequisites", val)
            continue

    return info


# ---------------------------------------------------------------------------
# Catalog description
# ---------------------------------------------------------------------------

def _parse_catalog_description(tables: list[ExtractedTable]) -> str | None:
    """Extract catalog description from the description table.

    Format B table 6 typically has a single cell starting with
    "1. Catalog Course Description ..."
    """
    for table in tables:
        for row in table.rows:
            if not row:
                continue
            cell = row[0].strip()
            # Match with parenthetical: "(General description ...)"
            m = re.match(
                r"(?:1\.\s+)?Catalog\s+Course\s+Description.*?\)\s*\n?(.*)",
                cell,
                re.IGNORECASE | re.DOTALL,
            )
            if m:
                desc = clean_text(m.group(1))
                if desc:
                    return desc
            # Match without parenthetical
            m = re.match(
                r"(?:1\.\s+)?Catalog\s+Course\s+Description\s*\n(.*)",
                cell,
                re.IGNORECASE | re.DOTALL,
            )
            if m:
                desc = clean_text(m.group(1))
                if desc:
                    return desc
    return None


# ---------------------------------------------------------------------------
# CLO parsing
# ---------------------------------------------------------------------------

def _is_clo_table(table: ExtractedTable) -> bool:
    """Check if a table is the CLO mapping table.

    The CLO table must have:
    1. Multiple rows (at least 3: header, column labels, data)
    2. A header mentioning "Map" CLOs to PLOs, or column headers
       like "Code", "CLOs", "Aligned PLOs"

    Single-row tables (e.g., catalog description) are excluded even
    if their text mentions "learning outcomes".
    """
    if not table.rows or len(table.rows) < 3:
        return False
    for row in table.rows[:3]:
        joined = " ".join(row).lower()
        if "map" in joined and "learning outcomes" in joined and "plo" in joined:
            return True
        if "code" in joined and "clo" in joined:
            return True
    return False


def _parse_clos_from_table(table: ExtractedTable) -> list[ParsedCLO]:
    """Parse CLOs from the CLO mapping table.

    Format B CLO tables have merged cells, so columns are duplicated.
    Typical unique columns: Code | CLOs | Aligned PLOs | Teaching Strategies | Assessment Methods
    But actual column count varies (10-14) due to merging.

    Strategy: identify columns by header labels, then extract unique values per row.
    """
    if not table.rows or len(table.rows) < 3:
        return []

    # Find the header row with column labels.
    # Standard: "Code | CLOs | Aligned PLOs | Teaching Strategies | Assessment Methods"
    # Alternative (DATA 399): "Code | Learning Outcomes | Aligned PLO Code | Training Activities | Assessment Methods"
    header_row_idx = -1
    for i, row in enumerate(table.rows[:3]):
        lower_joined = " ".join(row).lower()
        if "code" in lower_joined and (
            "clo" in lower_joined
            or "learning" in lower_joined
            or "outcomes" in lower_joined
        ):
            header_row_idx = i
            break

    if header_row_idx < 0:
        return []

    header = table.rows[header_row_idx]
    num_cols = len(header)

    # Identify column indices by scanning header labels.
    # Due to merged cells, we look for first occurrence of each label.
    code_col = -1
    clo_col = -1
    plo_col = -1
    teach_col = -1
    assess_col = -1

    for j, cell in enumerate(header):
        cl = cell.strip().lower()
        if cl == "code" and code_col < 0:
            code_col = j
        elif ("clo" in cl or "learning outcomes" in cl) and clo_col < 0:
            clo_col = j
        elif "plo" in cl and plo_col < 0:
            plo_col = j
        elif ("teaching" in cl or "training" in cl) and teach_col < 0:
            teach_col = j
        elif "assessment" in cl and assess_col < 0:
            assess_col = j

    # Fallback: if we found "code" twice, the second one plus offset = clo
    if code_col >= 0 and clo_col < 0:
        # Typical pattern: [Code, Code, CLOs, CLOs, PLOs, Teach..., Assess...]
        clo_col = code_col + 2 if code_col + 2 < num_cols else code_col + 1

    if code_col < 0:
        code_col = 0
    if clo_col < 0:
        clo_col = min(2, num_cols - 1)

    # Process data rows
    clos: list[ParsedCLO] = []
    current_category = CATEGORY_KNOWLEDGE
    sequence = 0

    for row in table.rows[header_row_idx + 1:]:
        if not row or not any(c.strip() for c in row):
            continue

        # Get code from the first column (or code_col)
        code = row[code_col].strip() if code_col < len(row) else ""
        if not code:
            continue

        # Skip metadata/footer rows
        if code.startswith("*") or "mapping" in code.lower():
            continue

        # Category header row: code is "1", "2", "3" or "1.0", "2.0", "3.0"
        clean_code = re.sub(r"\.0$", "", code)  # "1.0" -> "1"
        if clean_code in ("1", "2", "3") and (
            code == clean_code or code.endswith(".0")
        ):
            # Get category text from the CLO column
            cat_text = row[clo_col].strip() if clo_col < len(row) else ""
            cat = normalize_category(cat_text)
            if cat in (CATEGORY_KNOWLEDGE, CATEGORY_SKILLS, CATEGORY_VALUES):
                current_category = cat
            elif clean_code == "1":
                current_category = CATEGORY_KNOWLEDGE
            elif clean_code == "2":
                current_category = CATEGORY_SKILLS
            elif clean_code == "3":
                current_category = CATEGORY_VALUES
            continue

        # CLO data row: code is "1.1", "2.3", etc.
        if not re.match(r"^\d+\.\d+$", code):
            continue

        sequence += 1
        clo_text = clean_text(row[clo_col]) if clo_col < len(row) else ""

        # PLO codes
        plo_raw = row[plo_col].strip() if plo_col >= 0 and plo_col < len(row) else ""
        aligned_plos = extract_plo_codes(plo_raw)

        # Teaching strategy — take unique value from merged cells
        teaching = ""
        if teach_col >= 0 and teach_col < len(row):
            teaching = clean_text(row[teach_col])

        # Assessment method — take unique value from merged cells
        assessment = ""
        if assess_col >= 0 and assess_col < len(row):
            assessment = clean_text(row[assess_col])

        clos.append(ParsedCLO(
            clo_code=code,
            clo_text=clo_text,
            clo_category=current_category,
            sequence=sequence,
            teaching_strategy=teaching if teaching else None,
            assessment_method=assessment if assessment else None,
            aligned_plos=aligned_plos,
        ))

    return clos


# ---------------------------------------------------------------------------
# Topics parsing
# ---------------------------------------------------------------------------

def _parse_topics_from_tables(tables: list[ExtractedTable]) -> list[ParsedTopic]:
    """Extract topics from the topics table.

    Format B topics tables come in several variants:

    Variant 1 (3 cols): ``["No", "List of Topics", "Contact hours"]``
    Variant 2 (2 cols): ``["List of Topics", "Contact hours"]`` (no numbering)
    Variant 3 (1 col):  All content in a single merged cell with embedded
                        newlines, e.g. "2. Topics to be Covered\\nList of
                        Topics\\nContact hours\\nTopic1\\n3\\nTopic2\\n4"
    """
    topics: list[ParsedTopic] = []

    for table in tables:
        if not table.rows:
            continue

        # First check: is the entire topics table in a single cell?
        # (Variant 3 — common in MATH dept files)
        first_cell = table.rows[0][0].strip() if table.rows[0] else ""
        if "topics to be covered" in first_cell.lower() and "\n" in first_cell:
            # Check if this is a single-cell table or if topic data is
            # entirely within the first cell (no structured columns)
            num_cols = len(table.rows[0])
            has_structured_data = False
            if num_cols >= 2 and len(table.rows) >= 3:
                # Check if rows below the header have actual data
                for row in table.rows[1:]:
                    if len(row) >= 2:
                        title_candidate = row[0].strip() if len(row) > 0 else ""
                        hours_candidate = row[-1].strip() if len(row) > 0 else ""
                        if title_candidate and parse_float(hours_candidate) is not None:
                            has_structured_data = True
                            break

            if not has_structured_data:
                embedded = _parse_embedded_topics(first_cell)
                if embedded:
                    topics.extend(embedded)
                    continue

        if len(table.rows) < 2:
            continue

        # Check if this is a topics table
        is_topics = False
        start_row = 0
        topic_type = "lecture"

        for i, row in enumerate(table.rows[:3]):
            joined = " ".join(row).lower()
            if "topics to be covered" in joined or "list of topics" in joined:
                is_topics = True
                start_row = i + 1
                if "lab" in joined:
                    topic_type = "lab"
                elif "lecture" in joined:
                    topic_type = "lecture"
                break

        if not is_topics:
            continue

        # Skip header row if present (e.g., "No | List of Topics | Contact hours")
        if start_row < len(table.rows):
            first_data = table.rows[start_row]
            if len(first_data) >= 2:
                joined_hdr = " ".join(first_data).lower()
                if "list of topics" in joined_hdr or first_data[0].strip().lower() == "no":
                    start_row += 1

        for row in table.rows[start_row:]:
            if not row:
                continue

            if len(row) >= 3:
                # Variant 1: [No, Topic, Hours]
                num_str = row[0].strip()
                title = clean_text(row[1])
                hours_str = row[-1].strip()
            elif len(row) == 2:
                # Variant 2: [Topic, Hours] -- no numbering column
                num_str = ""
                title = clean_text(row[0])
                hours_str = row[-1].strip()
            else:
                continue

            # Skip total/footer rows
            if num_str.lower() in ("total",):
                continue
            if title.lower() in ("total",):
                continue

            # Try to parse the topic number
            topic_num = None
            if num_str:
                try:
                    topic_num = int(num_str)
                except ValueError:
                    pass

            # Parse contact hours (allow 0 or missing for capstone courses)
            hours = parse_float(hours_str)

            if not title:
                continue

            # Skip header-like content
            if title.lower() in ("list of topics",):
                continue

            # Auto-number if no explicit number
            if topic_num is None:
                topic_num = len(topics) + 1

            topics.append(ParsedTopic(
                topic_number=topic_num,
                topic_title=title,
                contact_hours=hours if hours is not None else 0.0,
                topic_type=topic_type,
            ))

    return topics


def _parse_embedded_topics(cell_text: str) -> list[ParsedTopic]:
    """Parse topics from a single cell with embedded newlines.

    Some files store the entire topics table as a single cell:
        "2. Topics to be Covered
         List of Topics
         Contact hours
         Topic 1
         3
         Topic 2
         4"

    Strategy: after stripping the header lines, alternate between
    topic title and contact hours.
    """
    lines = [ln.strip() for ln in cell_text.split("\n") if ln.strip()]

    # Skip header lines
    start = 0
    for i, line in enumerate(lines):
        lower = line.lower()
        if (
            "topics to be covered" in lower
            or "list of topics" in lower
            or "contact hours" in lower
        ):
            start = i + 1
        else:
            break

    data_lines = lines[start:]
    if not data_lines:
        return []

    # Try to pair lines as (title, hours)
    topics: list[ParsedTopic] = []
    i = 0
    num = 0
    while i < len(data_lines):
        title = data_lines[i]
        hours = 0.0

        # Check if next line is a number (contact hours)
        if i + 1 < len(data_lines):
            h = parse_float(data_lines[i + 1])
            if h is not None:
                hours = h
                i += 2
            else:
                i += 1
        else:
            i += 1

        # Skip if title looks like a number only (stray hours value)
        if parse_float(title) is not None:
            continue

        # Skip total rows
        if title.lower() in ("total",):
            continue

        num += 1
        topics.append(ParsedTopic(
            topic_number=num,
            topic_title=title,
            contact_hours=hours,
            topic_type="lecture",
        ))

    return topics


# ---------------------------------------------------------------------------
# Assessment parsing
# ---------------------------------------------------------------------------

def _parse_assessments_from_tables(
    tables: list[ExtractedTable],
) -> list[ParsedAssessment]:
    """Extract assessment activities from the assessment table.

    Format B assessment table has rows like:
        ["", "Assessment Activities*", "Week Due", "Proportion of Total Assessment Score"]
        ["1", "Major Exam 1", "Week 5", "25%"]
    """
    assessments: list[ParsedAssessment] = []

    for table in tables:
        if not table.rows or len(table.rows) < 2:
            continue

        # Check if this is an assessment table
        is_assessment = False
        start_row = 0

        for i, row in enumerate(table.rows[:2]):
            joined = " ".join(row).lower()
            if "assessment" in joined and ("week" in joined or "proportion" in joined):
                is_assessment = True
                start_row = i + 1
                break

        if not is_assessment:
            continue

        for row in table.rows[start_row:]:
            if len(row) < 3:
                continue

            # Determine which column is which
            # Layout: [number_or_empty, task, week, proportion]
            if len(row) >= 4:
                task = clean_text(row[1])
                week = row[2].strip()
                prop_str = row[3].strip()
            else:
                task = clean_text(row[0])
                week = row[1].strip()
                prop_str = row[2].strip()

            if not task:
                continue

            # Skip footer/metadata rows
            task_lower = task.lower()
            if task_lower in ("total",) or "e.g.," in task_lower:
                continue

            prop = parse_percentage(prop_str)
            if week and week.lower() == "week due":
                week = None

            assessments.append(ParsedAssessment(
                assessment_task=task,
                week_due=week if week else None,
                proportion=prop,
                assessment_type="lecture",
            ))

    return assessments


# ---------------------------------------------------------------------------
# Textbook parsing
# ---------------------------------------------------------------------------

def _parse_textbooks_from_tables(tables: list[ExtractedTable]) -> list[ParsedTextbook]:
    """Extract textbooks from the learning resources table.

    Format B table 15 has single-cell rows like:
        "1. List Required Textbooks\\n  <textbook>"
        "2. List Essential References Materials ...\\n  <references>"
    """
    textbooks: list[ParsedTextbook] = []

    # Type mapping based on the numbered label
    type_map = {
        "1": "required",
        "2": "reference",
        "3": "recommended",
        "4": "electronic",
        "5": "electronic",  # "other learning material"
    }

    for table in tables:
        for row in table.rows:
            if not row:
                continue
            cell = row[0].strip()

            # Match patterns like "1. List Required Textbooks\n ..."
            m = re.match(
                r"(\d)\.\s+(?:List\s+)?(?:Required\s+Textbooks?|"
                r"Essential\s+References?\s+Materials?|"
                r"Recommended\s+Textbooks?\s+and\s+Reference\s+Material|"
                r"List\s+Recommended\s+Textbooks?|"
                r"Electronic\s+Materials?|"
                r"List\s+Electronic\s+Materials?|"
                r"Other\s+learning\s+material).*?"
                r"(?:\n\s*|\s{2,})(.*)",
                cell,
                re.IGNORECASE | re.DOTALL,
            )
            if m:
                num = m.group(1)
                content = m.group(2).strip()
                book_type = type_map.get(num, "required")

                if content and content.lower() not in ("none", "n/a", "na", ""):
                    # Split multiple entries by newlines or bullet points
                    entries = re.split(r"\n\s*", content)
                    for entry in entries:
                        entry = entry.strip().lstrip("\u2022-").strip()
                        if entry and entry.lower() not in ("none", "n/a", "na", ""):
                            textbooks.append(ParsedTextbook(
                                textbook_text=entry,
                                textbook_type=book_type,
                            ))

    return textbooks


# ---------------------------------------------------------------------------
# Credit categorization parsing from tables
# ---------------------------------------------------------------------------

# Mapping from Format B category labels to DB column names
_FORMAT_B_CAT_MAP: dict[str, str] = {
    "engineering": "engineering_cs",
    "computer science": "engineering_cs",
    "engineering/computer science": "engineering_cs",
    "mathematics": "math_science",
    "science": "math_science",
    "mathematics/ science": "math_science",
    "mathematics/science": "math_science",
    "business": "social_sciences_business",
    "general education": "general_education",
    "social sciences": "general_education",
    "humanities": "humanities",
    "general education/ social sciences/ humanities": "general_education",
    "other": "other",
}


def _parse_credit_categorization(tables: list[ExtractedTable]) -> dict[str, float]:
    """Extract credit categorization from Format B tables.

    Format B stores this in the CLO/content table (typically table 8)
    in rows like::

        Row N:   "1. Subject Area Credit Hours ..."  (header, merged across all cols)
        Row N+1: "Engineering/Computer Science" | "Mathematics/ Science" | "Business" |
                 "General Education/ Social Sciences/ Humanities" | "Other"
                 (with duplicated cells due to merged columns)
        Row N+2: "0" | "0" | "3" | "0" | ... (values, many empty = 0)

    Strategy: find the label row, deduplicate the category names,
    pair each unique category with the first non-empty value in the
    corresponding value cells, then map to the DB column names.
    """
    for table in tables:
        for i, row in enumerate(table.rows):
            joined = " ".join(row).lower()
            if "subject area credit" not in joined:
                continue

            # Found the header row. The next row should have category labels.
            if i + 2 >= len(table.rows):
                continue

            label_row = table.rows[i + 1]
            value_row = table.rows[i + 2]

            # Check that label_row actually has category labels
            label_joined = " ".join(label_row).lower()
            if "engineering" not in label_joined and "mathematics" not in label_joined:
                continue

            # Deduplicate: walk through label_row, grouping consecutive
            # identical labels together and summing their values.
            result: dict[str, float] = {
                "engineering_cs": 0.0,
                "math_science": 0.0,
                "humanities": 0.0,
                "social_sciences_business": 0.0,
                "general_education": 0.0,
                "other": 0.0,
            }

            # Group cells by category label
            prev_label = None
            group_values: list[str] = []
            groups: list[tuple[str, list[str]]] = []

            for j, label_cell in enumerate(label_row):
                label = label_cell.strip()
                val = value_row[j].strip() if j < len(value_row) else ""

                if label != prev_label and prev_label is not None:
                    groups.append((prev_label, group_values))
                    group_values = []

                group_values.append(val)
                prev_label = label

            if prev_label is not None:
                groups.append((prev_label, group_values))

            # Map each group to a DB column and sum its values
            for label, vals in groups:
                db_col = _FORMAT_B_CAT_MAP.get(label.lower())
                if db_col is None:
                    # Try partial match
                    label_lower = label.lower()
                    for key, col in _FORMAT_B_CAT_MAP.items():
                        if key in label_lower:
                            db_col = col
                            break
                if db_col is None:
                    continue

                total = 0.0
                for v in vals:
                    try:
                        total += float(v)
                    except (ValueError, TypeError):
                        pass
                result[db_col] += total

            # Only return if at least one non-zero value
            if any(v > 0 for v in result.values()):
                return result

    return {}


# ---------------------------------------------------------------------------
# Credit hours parsing from tables
# ---------------------------------------------------------------------------

def _parse_credit_hours(tables: list[ExtractedTable], id_info: dict) -> dict:
    """Parse credit hours from course ID table and credit hours sub-table.

    Format B credit hours can be:
    1. In the id_info dict as "credit_hours_raw" (text after label)
    2. In a sub-table within the CLO table showing credit distribution

    The CLO table (table 8) sometimes contains credit hour rows at the bottom:
        Engineering/Computer Science | Mathematics/Science | ...
        "" | "4" | "" | ...
    """
    result: dict = {}

    # Check if we already have raw credit hours text
    raw = id_info.get("credit_hours_raw", "")
    if raw:
        # Try to parse "L-Lab-Total" format
        m = re.search(r"(\d+)\s*[-\u2013]\s*(\d+)\s*[-\u2013]\s*(\d+)", raw)
        if m:
            result["credit_hours_raw"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            result["lecture_credits"] = int(m.group(1))
            result["lab_credits"] = int(m.group(2))
            result["total_credits"] = int(m.group(3))
            return result

    # Look in tables for credit distribution rows.
    # Format B embeds credit info in the CLO/content table as:
    #   Row N:   "1. Subject Area Credit Hours ..."  (header)
    #   Row N+1: "Engineering/Computer Science" | "Mathematics/ Science" | ... (labels)
    #   Row N+2: "" | "4" | "" | ...  (values)
    for table in tables:
        for i, row in enumerate(table.rows):
            joined = " ".join(row).lower()
            if "subject area credit" in joined or (
                "engineering" in joined and "mathematics" in joined
            ):
                # Try to find a row with numeric values in the next 1-2 rows
                for offset in range(1, 3):
                    if i + offset >= len(table.rows):
                        break
                    candidate = table.rows[i + offset]
                    # Skip if this is still a label row
                    cand_joined = " ".join(candidate).lower()
                    if "engineering" in cand_joined or "subject" in cand_joined:
                        continue
                    total = 0.0
                    for cell in candidate:
                        v = parse_float(cell)
                        if v is not None:
                            total += v
                    if total > 0:
                        result["total_credits"] = int(total)
                        return result
                break

    # Fallback: look for "9. Contact and Credit Hours" row
    # which sometimes has structured credit data
    for table in tables:
        for i, row in enumerate(table.rows):
            joined = " ".join(row).lower()
            if "contact and credit hours" in joined:
                # Try to find credit/lecture/lab in nearby rows
                for offset in range(1, 4):
                    if i + offset >= len(table.rows):
                        break
                    candidate = table.rows[i + offset]
                    cand_joined = " ".join(candidate).lower()
                    if "credit hours" in cand_joined:
                        nums = []
                        for cell in candidate:
                            v = parse_float(cell)
                            if v is not None:
                                nums.append(v)
                        if nums:
                            result["total_credits"] = int(nums[-1])
                            if len(nums) >= 3:
                                result["lecture_credits"] = int(nums[0])
                                result["lab_credits"] = int(nums[1])
                            return result

    return result


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_format_b(result: ExtractionResult) -> ParsedCourse:
    """Parse a Format B (DOCX CRF2) extraction result into a ParsedCourse.

    Args:
        result: ExtractionResult from a Format B DOCX.

    Returns:
        ParsedCourse with all extracted fields populated.
    """
    course = ParsedCourse(
        format_type="format_b_crf2",
        source_file=result.file_path,
    )

    tables = result.tables

    # --- Identity ---
    identity = _parse_identity_from_tables(tables)
    id_fields = _parse_course_id_table(tables)

    # Course code: try table identity first, then filename
    code_raw = identity.get("course_code", "")
    if code_raw:
        course.course_code = normalize_course_code(code_raw)
        course.confidence["course_code"] = 0.9
    else:
        filename = Path(result.file_path).name
        code_from_file = extract_course_code_from_filename(filename)
        if code_from_file:
            course.course_code = code_from_file
            course.confidence["course_code"] = 0.7
        else:
            course.warnings.append("Could not extract course code")

    course.course_title = identity.get("course_title", "")
    if course.course_title:
        course.confidence["course_title"] = 0.9
    else:
        course.warnings.append("Course title not found in identity table")

    course.department = identity.get("department")
    course.college = identity.get("college")

    # --- Credits ---
    credit_info = _parse_credit_hours(tables, id_fields)
    course.credit_hours_raw = credit_info.get(
        "credit_hours_raw", id_fields.get("credit_hours_raw")
    )
    course.lecture_credits = credit_info.get("lecture_credits")
    course.lab_credits = credit_info.get("lab_credits")
    course.total_credits = credit_info.get("total_credits")
    if course.total_credits or course.credit_hours_raw:
        course.confidence["credits"] = 0.8

    # --- Course type and level ---
    course.course_type = id_fields.get("course_type")
    course.level = id_fields.get("level")

    # --- Prerequisites / Corequisites ---
    course.prerequisites = id_fields.get("prerequisites")
    course.corequisites = id_fields.get("corequisites")

    # --- Catalog Description ---
    course.catalog_description = _parse_catalog_description(tables)
    if course.catalog_description:
        course.confidence["catalog_description"] = 0.9

    # --- CLOs ---
    for table in tables:
        if _is_clo_table(table):
            clos = _parse_clos_from_table(table)
            if clos:
                course.clos = clos
                break
    if not course.clos:
        # Fallback: try to find CLOs in any table with Code/Learning Outcomes columns
        for table in tables:
            if len(table.rows) >= 3:
                clos = _parse_clos_from_table(table)
                if clos:
                    course.clos = clos
                    course.confidence["clos"] = 0.7
                    break
    if course.clos:
        course.confidence.setdefault("clos", 0.9)
    else:
        course.warnings.append("No CLOs found in tables")

    # --- Topics ---
    course.topics = _parse_topics_from_tables(tables)
    if course.topics:
        course.confidence["topics"] = 0.9
    else:
        course.warnings.append("No topics found in tables")

    # --- Textbooks ---
    course.textbooks = _parse_textbooks_from_tables(tables)
    if course.textbooks:
        course.confidence["textbooks"] = 0.85

    # --- Assessment ---
    course.assessments = _parse_assessments_from_tables(tables)
    if course.assessments:
        course.confidence["assessments"] = 0.85

    # --- Credit Categorization ---
    course.credit_categorization = _parse_credit_categorization(tables)
    if course.credit_categorization:
        course.confidence["credit_categorization"] = 0.85

    return course
