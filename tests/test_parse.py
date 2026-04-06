"""Tests for the parsing module."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from abet_syllabus.parse import (
    ParsedAssessment,
    ParsedCLO,
    ParsedCourse,
    ParsedTextbook,
    ParsedTopic,
    parse_extraction,
    parse_file,
    parse_folder,
)
from abet_syllabus.parse._common import (
    clean_text,
    extract_plo_codes,
    normalize_category,
    parse_float,
    parse_percentage,
)
from abet_syllabus.parse.normalize import (
    extract_course_code_from_filename,
    normalize_course_code,
)

# ---------------------------------------------------------------------------
# Resource path setup
# ---------------------------------------------------------------------------

_RESOURCES = Path(os.environ.get(
    "ABET_RESOURCES",
    "C:/Users/mmogi/Projects/published_apps/abet-syllabus/resources",
))
_DATA_DIR = _RESOURCES / "course-descriptions" / "data"
_MATH_DIR = _RESOURCES / "course-descriptions" / "math"
_AS_DIR = _RESOURCES / "course-descriptions" / "as"

_PDF_FILE = _DATA_DIR / "BUS 200 Course Specifications.pdf"
_DOCX_FILE = _MATH_DIR / "CS -Math-101-2024.docx"
_AS_FILE = _AS_DIR / "CRF2. COURSE SPECIFICATIONS AS 201 T251 1.docx"

_HAS_RESOURCES = _PDF_FILE.exists() and _DOCX_FILE.exists()
requires_resources = pytest.mark.skipif(
    not _HAS_RESOURCES,
    reason="Test resource files not found (resources/ is gitignored)",
)


# ===================================================================
# Shared utility tests (_common.py)
# ===================================================================


class TestCommonUtilities:
    """Tests for shared utility functions in _common.py."""

    def test_normalize_category_knowledge(self):
        assert normalize_category("Knowledge and Understanding") == "Knowledge and Understanding"

    def test_normalize_category_lowercase(self):
        assert normalize_category("skills") == "Skills"

    def test_normalize_category_with_dots(self):
        assert normalize_category("values.") == "Values"

    def test_normalize_category_unknown(self):
        assert normalize_category("Something Else") == "Something Else"

    def test_clean_text_newlines(self):
        assert clean_text("hello\n  world") == "hello world"

    def test_clean_text_strips(self):
        assert clean_text("  hello  ") == "hello"

    def test_parse_percentage_basic(self):
        assert parse_percentage("25%") == 25.0

    def test_parse_percentage_with_space(self):
        assert parse_percentage("25 %") == 25.0

    def test_parse_percentage_float(self):
        assert parse_percentage("25.5%") == 25.5

    def test_parse_percentage_none(self):
        assert parse_percentage("no percent") is None

    def test_parse_float_basic(self):
        assert parse_float("3.5") == 3.5

    def test_parse_float_int(self):
        assert parse_float("3") == 3.0

    def test_parse_float_empty(self):
        assert parse_float("") is None

    def test_parse_float_invalid(self):
        assert parse_float("abc") is None

    def test_extract_plo_codes_single(self):
        assert extract_plo_codes("K1") == ["K1"]

    def test_extract_plo_codes_multiple(self):
        assert extract_plo_codes("K1, S2") == ["K1", "S2"]

    def test_extract_plo_codes_with_dots(self):
        assert extract_plo_codes("K.1") == ["K1"]

    def test_extract_plo_codes_empty(self):
        assert extract_plo_codes("") == []

    def test_extract_plo_codes_none_string(self):
        assert extract_plo_codes("None") == []


# ===================================================================
# Course code normalization tests
# ===================================================================


class TestNormalizeCourseCode:
    """Tests for normalize_course_code()."""

    def test_already_normalized(self):
        assert normalize_course_code("MATH 101") == "MATH 101"

    def test_no_space(self):
        assert normalize_course_code("BUS200") == "BUS 200"

    def test_no_space_uppercase(self):
        assert normalize_course_code("MATH208") == "MATH 208"

    def test_mixed_case(self):
        assert normalize_course_code("Math 101") == "MATH 101"

    def test_mixed_case_no_space(self):
        assert normalize_course_code("Math208") == "MATH 208"

    def test_extra_spaces(self):
        assert normalize_course_code("  math  101  ") == "MATH 101"

    def test_hyphen_separator(self):
        assert normalize_course_code("MATH-101") == "MATH 101"

    def test_lowercase(self):
        assert normalize_course_code("ics 104") == "ICS 104"

    def test_three_letter_dept(self):
        assert normalize_course_code("SWE363") == "SWE 363"

    def test_four_letter_dept(self):
        assert normalize_course_code("ENGL101") == "ENGL 101"

    def test_two_letter_dept(self):
        assert normalize_course_code("PE101") == "PE 101"

    def test_four_digit_number(self):
        assert normalize_course_code("DATA 1001") == "DATA 1001"

    def test_empty_string(self):
        assert normalize_course_code("") == ""

    def test_whitespace_only(self):
        assert normalize_course_code("   ") == ""

    def test_as_code(self):
        assert normalize_course_code("AS201") == "AS 201"

    def test_stat_code(self):
        assert normalize_course_code("STAT460") == "STAT 460"

    def test_coe_code(self):
        assert normalize_course_code("COE 292") == "COE 292"


class TestExtractCourseCodeFromFilename:
    """Tests for extract_course_code_from_filename()."""

    def test_standard_pdf(self):
        result = extract_course_code_from_filename("BUS 200 Course Specifications.pdf")
        assert result == "BUS 200"

    def test_cs_prefix_with_spaces(self):
        result = extract_course_code_from_filename("CS -Math-101-2024.docx")
        assert result == "MATH 101"

    def test_cs_prefix_no_spaces(self):
        result = extract_course_code_from_filename("CS-MATH325-2024.docx")
        assert result == "MATH 325"

    def test_cs_prefix_mixed_case(self):
        result = extract_course_code_from_filename("CS-Math208-2024.docx")
        assert result == "MATH 208"

    def test_crf2_prefix(self):
        result = extract_course_code_from_filename(
            "CRF2. COURSE SPECIFICATIONS AS 201 T251 1.docx"
        )
        assert result == "AS 201"

    def test_data_docx(self):
        result = extract_course_code_from_filename("DATA 201 Course Specifications.docx")
        assert result == "DATA 201"

    def test_double_space(self):
        result = extract_course_code_from_filename("DATA 311  Course Specifications.docx")
        assert result == "DATA 311"

    def test_ics_pdf(self):
        result = extract_course_code_from_filename("ICS 104 Course Specifications.pdf")
        assert result == "ICS 104"

    def test_no_match(self):
        result = extract_course_code_from_filename("random_file.txt")
        assert result is None


# ===================================================================
# Model tests
# ===================================================================


class TestParsedModels:
    """Tests for parsed data model dataclasses."""

    def test_parsed_course_defaults(self):
        c = ParsedCourse()
        assert c.course_code == ""
        assert c.clos == []
        assert c.topics == []
        assert c.textbooks == []
        assert c.assessments == []
        assert c.confidence == {}
        assert c.warnings == []

    def test_parsed_clo_defaults(self):
        clo = ParsedCLO(
            clo_code="1.1",
            clo_text="Test CLO",
            clo_category="Knowledge and Understanding",
            sequence=1,
        )
        assert clo.clo_code == "1.1"
        assert clo.aligned_plos == []
        assert clo.teaching_strategy is None

    def test_parsed_topic_defaults(self):
        topic = ParsedTopic(topic_number=1, topic_title="Test", contact_hours=3.0)
        assert topic.topic_type == "lecture"

    def test_parsed_textbook_defaults(self):
        tb = ParsedTextbook(textbook_text="Some book")
        assert tb.textbook_type == "required"

    def test_parsed_assessment_defaults(self):
        a = ParsedAssessment(assessment_task="Exam")
        assert a.assessment_type == "lecture"
        assert a.proportion is None


# ===================================================================
# Parser dispatch tests
# ===================================================================


class TestParserDispatch:
    """Tests for parse_file() dispatching."""

    @requires_resources
    def test_pdf_dispatches_to_format_a(self):
        course = parse_file(_PDF_FILE)
        assert course.format_type == "format_a_pdf"

    @requires_resources
    def test_docx_dispatches_to_format_b(self):
        course = parse_file(_DOCX_FILE)
        assert course.format_type == "format_b_crf2"

    def test_nonexistent_file_raises(self):
        with pytest.raises(FileNotFoundError):
            parse_file("/nonexistent/file.pdf")

    def test_unsupported_format_raises(self, tmp_path):
        txt = tmp_path / "test.txt"
        txt.write_text("hello")
        with pytest.raises(ValueError):
            parse_file(txt)

    @requires_resources
    def test_parse_extraction_with_unknown_format(self):
        from abet_syllabus.extract.models import ExtractionResult

        result = ExtractionResult(format_type="unknown_format")
        with pytest.raises(ValueError, match="Unknown format type"):
            parse_extraction(result)


# ===================================================================
# Format A (PDF) parsing tests
# ===================================================================


class TestFormatAParsing:
    """Tests for Format A (PDF) parser against real files."""

    @requires_resources
    def test_bus200_course_code(self):
        c = parse_file(_PDF_FILE)
        assert c.course_code == "BUS 200"

    @requires_resources
    def test_bus200_course_title(self):
        c = parse_file(_PDF_FILE)
        assert c.course_title == "Business & Entrepreneurship"

    @requires_resources
    def test_bus200_credits(self):
        c = parse_file(_PDF_FILE)
        assert c.credit_hours_raw == "3-0-3"
        assert c.lecture_credits == 3
        assert c.lab_credits == 0
        assert c.total_credits == 3

    @requires_resources
    def test_bus200_department(self):
        c = parse_file(_PDF_FILE)
        assert c.department is not None
        assert "Marketing" in c.department

    @requires_resources
    def test_bus200_college(self):
        c = parse_file(_PDF_FILE)
        assert c.college is not None
        assert "Business" in c.college

    @requires_resources
    def test_bus200_catalog_description(self):
        c = parse_file(_PDF_FILE)
        assert c.catalog_description is not None
        assert "industrial revolution" in c.catalog_description.lower()

    @requires_resources
    def test_bus200_clos_count(self):
        c = parse_file(_PDF_FILE)
        assert len(c.clos) == 7

    @requires_resources
    def test_bus200_clo_categories(self):
        c = parse_file(_PDF_FILE)
        categories = {clo.clo_category for clo in c.clos}
        assert "Knowledge and Understanding" in categories
        assert "Skills" in categories
        assert "Values" in categories

    @requires_resources
    def test_bus200_clo_teaching_strategy(self):
        c = parse_file(_PDF_FILE)
        # All CLOs should have teaching strategies
        for clo in c.clos:
            assert clo.teaching_strategy is not None, (
                f"CLO {clo.clo_code} missing teaching strategy"
            )

    @requires_resources
    def test_bus200_topics(self):
        c = parse_file(_PDF_FILE)
        assert len(c.topics) >= 10
        # First topic
        assert c.topics[0].topic_number == 1
        assert c.topics[0].contact_hours > 0

    @requires_resources
    def test_bus200_assessments(self):
        c = parse_file(_PDF_FILE)
        assert len(c.assessments) >= 3
        # At least one should have proportion
        props = [a.proportion for a in c.assessments if a.proportion is not None]
        assert len(props) >= 3

    @requires_resources
    def test_bus200_textbooks(self):
        c = parse_file(_PDF_FILE)
        assert len(c.textbooks) >= 1
        # Should have at least one required textbook
        required = [t for t in c.textbooks if t.textbook_type == "required"]
        assert len(required) >= 1

    @requires_resources
    def test_bus200_confidence(self):
        c = parse_file(_PDF_FILE)
        assert c.confidence.get("course_code", 0) >= 0.8
        assert c.confidence.get("clos", 0) >= 0.8

    @requires_resources
    def test_bus200_no_warnings(self):
        c = parse_file(_PDF_FILE)
        assert len(c.warnings) == 0

    @requires_resources
    def test_ics104_lab_credits(self):
        """ICS 104 has lab credits: 2-3-3."""
        f = _DATA_DIR / "ICS 104 Course Specifications.pdf"
        if not f.exists():
            pytest.skip("ICS 104 file not found")
        c = parse_file(f)
        assert c.credit_hours_raw == "2-3-3"
        assert c.lecture_credits == 2
        assert c.lab_credits == 3
        assert c.total_credits == 3

    @requires_resources
    def test_swe206_lab_topics(self):
        """SWE 206 has both lecture and lab topics."""
        f = _DATA_DIR / "SWE 206 Course Specifications.pdf"
        if not f.exists():
            pytest.skip("SWE 206 file not found")
        c = parse_file(f)
        types = {t.topic_type for t in c.topics}
        assert "lecture" in types
        assert "lab" in types

    @requires_resources
    def test_math101_pdf_title(self):
        """MATH 101 PDF should have title."""
        f = _DATA_DIR / "MATH 101 Course Specifications.pdf"
        if not f.exists():
            pytest.skip("MATH 101 PDF not found")
        c = parse_file(f)
        assert c.course_code == "MATH 101"
        assert "Calculus" in c.course_title

    @requires_resources
    def test_coe292_credit_categorization(self):
        """COE 292 should have engineering_cs=3.0."""
        f = _DATA_DIR / "COE 292 Course Specifications.pdf"
        if not f.exists():
            pytest.skip("COE 292 file not found")
        c = parse_file(f)
        assert c.credit_categorization
        assert c.credit_categorization["engineering_cs"] == 3.0
        assert c.credit_categorization["math_science"] == 0.0

    @requires_resources
    def test_bus200_credit_categorization(self):
        """BUS 200 should have social_sciences_business=45.0."""
        c = parse_file(_PDF_FILE)
        assert c.credit_categorization
        assert c.credit_categorization["social_sciences_business"] == 45.0

    @requires_resources
    def test_engl101_credit_categorization(self):
        """ENGL 101 should have general_education=3.0."""
        f = _DATA_DIR / "ENGL 101 Course Specifications.pdf"
        if not f.exists():
            pytest.skip("ENGL 101 file not found")
        c = parse_file(f)
        assert c.credit_categorization
        assert c.credit_categorization["general_education"] == 3.0

    @requires_resources
    def test_math101_pdf_credit_categorization(self):
        """MATH 101 PDF should have math_science=4.0."""
        f = _DATA_DIR / "MATH 101 Course Specifications.pdf"
        if not f.exists():
            pytest.skip("MATH 101 PDF not found")
        c = parse_file(f)
        assert c.credit_categorization
        assert c.credit_categorization["math_science"] == 4.0


# ===================================================================
# Format B (DOCX CRF2) parsing tests
# ===================================================================


class TestFormatBParsing:
    """Tests for Format B (DOCX CRF2) parser against real files."""

    @requires_resources
    def test_math101_course_code(self):
        c = parse_file(_DOCX_FILE)
        assert c.course_code == "MATH 101"

    @requires_resources
    def test_math101_course_title(self):
        """Format B DOCX should extract title from SDT content controls."""
        c = parse_file(_DOCX_FILE)
        assert c.course_title == "Calculus I"

    @requires_resources
    def test_math101_credits(self):
        """Format B DOCX should extract credits from SDT content controls."""
        c = parse_file(_DOCX_FILE)
        assert c.credit_hours_raw == "4-0-4"
        assert c.lecture_credits == 4
        assert c.lab_credits == 0
        assert c.total_credits == 4

    @requires_resources
    def test_math101_department(self):
        """Format B DOCX should extract department from SDT content."""
        c = parse_file(_DOCX_FILE)
        assert c.department is not None
        assert "Mathematics" in c.department

    @requires_resources
    def test_math101_college(self):
        """Format B DOCX should extract college from SDT content."""
        c = parse_file(_DOCX_FILE)
        assert c.college is not None
        assert "Computing" in c.college

    @requires_resources
    def test_math101_prerequisites(self):
        c = parse_file(_DOCX_FILE)
        assert c.prerequisites is not None
        assert "prep" in c.prerequisites.lower() or "math" in c.prerequisites.lower()

    @requires_resources
    def test_math101_catalog_description(self):
        c = parse_file(_DOCX_FILE)
        assert c.catalog_description is not None
        assert "limit" in c.catalog_description.lower()

    @requires_resources
    def test_math101_clos(self):
        c = parse_file(_DOCX_FILE)
        assert len(c.clos) >= 5

    @requires_resources
    def test_math101_clo_plos(self):
        """Format B CLOs should have aligned PLOs."""
        c = parse_file(_DOCX_FILE)
        clos_with_plos = [clo for clo in c.clos if clo.aligned_plos]
        assert len(clos_with_plos) >= 1

    @requires_resources
    def test_math101_clo_categories(self):
        c = parse_file(_DOCX_FILE)
        categories = {clo.clo_category for clo in c.clos}
        assert "Knowledge and Understanding" in categories
        assert "Skills" in categories

    @requires_resources
    def test_math101_clo_teaching_strategy(self):
        c = parse_file(_DOCX_FILE)
        strategies = [clo.teaching_strategy for clo in c.clos if clo.teaching_strategy]
        assert len(strategies) >= 1

    @requires_resources
    def test_math101_topics_embedded(self):
        """MATH 101 has topics in a single-cell embedded format."""
        c = parse_file(_DOCX_FILE)
        assert len(c.topics) >= 5
        assert c.topics[0].topic_number == 1
        assert c.topics[0].contact_hours > 0
        # Verify topic titles
        titles = [t.topic_title for t in c.topics]
        assert any("limit" in t.lower() or "continuity" in t.lower() for t in titles)

    @requires_resources
    def test_math101_assessments(self):
        c = parse_file(_DOCX_FILE)
        assert len(c.assessments) >= 3
        # Should include major exams and final
        tasks = [a.assessment_task.lower() for a in c.assessments]
        assert any("exam" in t for t in tasks)

    @requires_resources
    def test_math101_textbooks(self):
        c = parse_file(_DOCX_FILE)
        assert len(c.textbooks) >= 1
        # Should have required textbook about Calculus
        required = [t for t in c.textbooks if t.textbook_type == "required"]
        assert len(required) >= 1

    @requires_resources
    def test_math101_total_credits(self):
        """Total credits extracted from SDT content (was subject area credit hours)."""
        c = parse_file(_DOCX_FILE)
        assert c.total_credits is not None
        assert c.total_credits > 0

    @requires_resources
    def test_as201_course_code(self):
        if not _AS_FILE.exists():
            pytest.skip("AS 201 file not found")
        c = parse_file(_AS_FILE)
        assert c.course_code == "AS 201"

    @requires_resources
    def test_as201_topics(self):
        """AS 201 has a proper topics table."""
        if not _AS_FILE.exists():
            pytest.skip("AS 201 file not found")
        c = parse_file(_AS_FILE)
        assert len(c.topics) >= 5
        assert c.topics[0].topic_number == 1
        assert c.topics[0].contact_hours > 0

    @requires_resources
    def test_as201_assessments(self):
        if not _AS_FILE.exists():
            pytest.skip("AS 201 file not found")
        c = parse_file(_AS_FILE)
        assert len(c.assessments) >= 3

    @requires_resources
    def test_data201_parsing(self):
        """DATA 201 is a standard Format B file."""
        f = _DATA_DIR / "DATA 201 Course Specifications.docx"
        if not f.exists():
            pytest.skip("DATA 201 file not found")
        c = parse_file(f)
        assert c.course_code == "DATA 201"
        assert len(c.clos) >= 3
        assert len(c.topics) >= 5

    @requires_resources
    def test_data322_full_identity(self):
        """DATA 322 has all identity fields filled in (inline, not SDT)."""
        f = _DATA_DIR / "DATA 322 Course Specifications.docx"
        if not f.exists():
            pytest.skip("DATA 322 file not found")
        c = parse_file(f)
        assert c.course_code == "DATA 322"
        assert "Mathematical Modeling" in c.course_title
        assert c.credit_hours_raw == "3-0-3"
        assert c.total_credits == 3

    @requires_resources
    def test_data441_title_from_table(self):
        """DATA 441 has title in identity table (inline, not SDT)."""
        f = _DATA_DIR / "DATA 441 Course Specifications.docx"
        if not f.exists():
            pytest.skip("DATA 441 file not found")
        c = parse_file(f)
        assert "Large Language Models" in c.course_title

    @requires_resources
    def test_math102_title_from_sdt(self):
        """MATH 102 has title in SDT (content control)."""
        f = _MATH_DIR / "CS -Math-102-2024.docx"
        if not f.exists():
            pytest.skip("MATH 102 file not found")
        c = parse_file(f)
        assert c.course_code == "MATH 102"
        assert c.course_title, "Title should be extracted from SDT content"

    @requires_resources
    def test_math102_credits_from_sdt(self):
        """MATH 102 has credits in SDT (content control)."""
        f = _MATH_DIR / "CS -Math-102-2024.docx"
        if not f.exists():
            pytest.skip("MATH 102 file not found")
        c = parse_file(f)
        assert c.credit_hours_raw is not None
        assert c.total_credits is not None
        assert c.total_credits > 0

    @requires_resources
    def test_math102_topics_2col(self):
        """MATH 102 has 2-column topics table (no 'No' column)."""
        f = _MATH_DIR / "CS -Math-102-2024.docx"
        if not f.exists():
            pytest.skip("MATH 102 file not found")
        c = parse_file(f)
        assert len(c.topics) >= 5

    @requires_resources
    def test_data411_topics_without_hours(self):
        """DATA 411 (capstone) has topics with no contact hours."""
        f = _DATA_DIR / "DATA 411 Course Specifications NT.docx"
        if not f.exists():
            pytest.skip("DATA 411 file not found")
        c = parse_file(f)
        assert len(c.topics) >= 3
        # Topics should have 0.0 contact hours (not None)
        for t in c.topics:
            assert t.contact_hours == 0.0

    @requires_resources
    def test_data399_field_experience_credits(self):
        """DATA 399 (field experience) should extract credits from different format."""
        f = _DATA_DIR / "DATA 399 Course Specifications.docx"
        if not f.exists():
            pytest.skip("DATA 399 file not found")
        c = parse_file(f)
        assert c.course_code == "DATA 399"
        assert c.course_title == "Summer Training"
        assert c.total_credits is not None or c.credit_hours_raw is not None

    @requires_resources
    def test_math101_docx_credit_categorization(self):
        """MATH 101 DOCX should have math_science=4.0."""
        c = parse_file(_DOCX_FILE)
        assert c.credit_categorization
        assert c.credit_categorization["math_science"] == 4.0
        assert c.credit_categorization["engineering_cs"] == 0.0

    @requires_resources
    def test_data201_credit_categorization(self):
        """DATA 201 should have math_science=3.0."""
        f = _DATA_DIR / "DATA 201 Course Specifications.docx"
        if not f.exists():
            pytest.skip("DATA 201 file not found")
        c = parse_file(f)
        assert c.credit_categorization
        assert c.credit_categorization["math_science"] == 3.0

    @requires_resources
    def test_format_b_code_from_filename(self):
        """CS-Math filenames extract code correctly."""
        c = parse_file(_DOCX_FILE)
        # Even though table identity may be empty, code comes from filename
        assert c.course_code == "MATH 101"

    @requires_resources
    def test_format_b_title_coverage(self):
        """At least 95% of Format B files should have a title extracted."""
        parent = _RESOURCES / "course-descriptions"
        courses = parse_folder(parent, recursive=True)
        fmt_b = [c for c in courses if c.format_type == "format_b_crf2"]
        has_title = sum(1 for c in fmt_b if c.course_title)
        pct = has_title / len(fmt_b) * 100 if fmt_b else 0
        assert pct >= 95, (
            f"Format B title coverage {has_title}/{len(fmt_b)} ({pct:.1f}%) < 95%"
        )

    @requires_resources
    def test_format_b_credits_coverage(self):
        """At least 95% of Format B files should have credits extracted."""
        parent = _RESOURCES / "course-descriptions"
        courses = parse_folder(parent, recursive=True)
        fmt_b = [c for c in courses if c.format_type == "format_b_crf2"]
        has_credits = sum(
            1 for c in fmt_b if c.credit_hours_raw or c.total_credits is not None
        )
        pct = has_credits / len(fmt_b) * 100 if fmt_b else 0
        assert pct >= 95, (
            f"Format B credits coverage {has_credits}/{len(fmt_b)} ({pct:.1f}%) < 95%"
        )


# ===================================================================
# Folder parsing tests
# ===================================================================


class TestParseFolder:
    """Tests for parse_folder()."""

    @requires_resources
    def test_parse_data_folder(self):
        courses = parse_folder(_DATA_DIR)
        assert len(courses) > 10

    @requires_resources
    def test_parse_recursive(self):
        parent = _RESOURCES / "course-descriptions"
        courses = parse_folder(parent, recursive=True)
        assert len(courses) > 50  # We know there are 72 files

    @requires_resources
    def test_all_have_course_code(self):
        parent = _RESOURCES / "course-descriptions"
        courses = parse_folder(parent, recursive=True)
        for c in courses:
            assert c.course_code, (
                f"Missing course code for {Path(c.source_file).name}"
            )

    @requires_resources
    def test_all_have_clos(self):
        """All files should have at least some CLOs."""
        parent = _RESOURCES / "course-descriptions"
        courses = parse_folder(parent, recursive=True)
        for c in courses:
            assert len(c.clos) > 0, (
                f"No CLOs for {c.course_code} ({Path(c.source_file).name})"
            )

    def test_empty_folder(self, tmp_path):
        courses = parse_folder(tmp_path)
        assert courses == []

    def test_nonexistent_folder(self):
        with pytest.raises(FileNotFoundError):
            parse_folder("/nonexistent/folder")


# ===================================================================
# Coverage report (not a test, just informational)
# ===================================================================


class TestCoverageReport:
    """Run parser against all files and report field coverage."""

    @requires_resources
    def test_coverage_report(self, capsys):
        """Parse all files and print a coverage summary.

        This test always passes -- it just prints the report.
        """
        parent = _RESOURCES / "course-descriptions"
        courses = parse_folder(parent, recursive=True)

        fields = {
            "course_code": lambda c: bool(c.course_code),
            "course_title": lambda c: bool(c.course_title),
            "credit_hours_raw": lambda c: bool(c.credit_hours_raw),
            "total_credits": lambda c: c.total_credits is not None and c.total_credits > 0,
            "catalog_description": lambda c: bool(c.catalog_description),
            "clos": lambda c: len(c.clos) > 0,
            "topics": lambda c: len(c.topics) > 0,
            "assessments": lambda c: len(c.assessments) > 0,
            "textbooks": lambda c: len(c.textbooks) > 0,
        }

        print(f"\n=== FIELD COVERAGE ({len(courses)} files) ===")
        for name, check in fields.items():
            count = sum(1 for c in courses if check(c))
            pct = count / len(courses) * 100 if courses else 0
            print(f"  {name:<25} {count:>3}/{len(courses)} ({pct:.1f}%)")
