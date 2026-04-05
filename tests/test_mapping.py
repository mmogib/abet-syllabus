"""Tests for the CLO-PLO mapping engine (Stage 6).

Tests are organized into:
- Unit tests: no API calls, test data structures and DB logic
- Integration tests: mock the Anthropic API, test full flow
- Real API tests: gated behind ABET_TEST_API=1 env var
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from abet_syllabus.db.models import (
    CloPloMapping,
    Course,
    CourseClo,
    PloDefinition,
    Program,
)
from abet_syllabus.db.schema import init_db
from abet_syllabus.db import repository as repo
from abet_syllabus.mapping.provider import MappingProvider, MappingResult
from abet_syllabus.mapping.anthropic_provider import (
    AnthropicProvider,
    _build_user_prompt,
    _parse_response,
)
from abet_syllabus.mapping.engine import (
    approve_mappings,
    export_plo_matrix,
    get_default_provider,
    map_course,
    map_program,
    review_mappings,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database with test data."""
    path = tmp_path / "test.db"
    conn = init_db(str(path))

    # Create program
    repo.upsert_program(conn, Program(program_code="MATH", program_name="Mathematics"))

    # Create PLOs
    plos = [
        PloDefinition(program_code="MATH", plo_code="MATH_PLO_K1", plo_label="K1",
                       plo_description="Apply mathematical knowledge", sequence=1),
        PloDefinition(program_code="MATH", plo_code="MATH_PLO_K2", plo_label="K2",
                       plo_description="Understand key mathematical concepts", sequence=2),
        PloDefinition(program_code="MATH", plo_code="MATH_PLO_S1", plo_label="S1",
                       plo_description="Solve mathematical problems systematically", sequence=3),
        PloDefinition(program_code="MATH", plo_code="MATH_PLO_S2", plo_label="S2",
                       plo_description="Use mathematical tools and technology", sequence=4),
    ]
    for plo in plos:
        repo.upsert_plo(conn, plo)

    # Create course
    course_id = repo.upsert_course(conn, Course(
        course_code="MATH 101",
        course_title="Calculus I",
        department="MATH",
        catalog_description="Limits, continuity, differentiation, and integration.",
    ))

    # Link course to program
    repo.link_course_program(conn, course_id, "MATH")

    # Create CLOs
    clos = [
        CourseClo(course_id=course_id, clo_code="1.1", clo_category="Knowledge",
                   clo_text="Understand limits and continuity of functions", sequence=1),
        CourseClo(course_id=course_id, clo_code="1.2", clo_category="Knowledge",
                   clo_text="Apply differentiation rules to compute derivatives", sequence=2),
        CourseClo(course_id=course_id, clo_code="2.1", clo_category="Skills",
                   clo_text="Solve optimization problems using calculus", sequence=3),
    ]
    repo.replace_course_clos(conn, course_id, clos)

    # Create a second course for program-wide tests
    course2_id = repo.upsert_course(conn, Course(
        course_code="MATH 201",
        course_title="Calculus II",
        department="MATH",
        catalog_description="Integration techniques, series, and sequences.",
    ))
    repo.link_course_program(conn, course2_id, "MATH")
    clos2 = [
        CourseClo(course_id=course2_id, clo_code="1.1", clo_category="Knowledge",
                   clo_text="Evaluate definite and indefinite integrals", sequence=1),
    ]
    repo.replace_course_clos(conn, course2_id, clos2)

    conn.close()
    return str(path)


class MockProvider(MappingProvider):
    """A mock provider that returns predetermined results."""

    def __init__(self, results: list[MappingResult] | None = None):
        self._results = results or []

    def map_clos_to_plos(self, course_code, course_title, course_description, clos, plos):
        if self._results:
            return self._results
        # Default: map each CLO to the first PLO
        results = []
        for clo in clos:
            if plos:
                results.append(MappingResult(
                    clo_code=clo["code"],
                    plo_code=plos[0]["label"],
                    confidence=0.85,
                    rationale=f"Default mock mapping for {clo['code']}",
                ))
        return results


# ===========================================================================
# Unit Tests: MappingResult
# ===========================================================================

class TestMappingResult:

    def test_basic_creation(self):
        r = MappingResult(clo_code="1.1", plo_code="K1", confidence=0.9, rationale="Test")
        assert r.clo_code == "1.1"
        assert r.plo_code == "K1"
        assert r.confidence == 0.9
        assert r.rationale == "Test"

    def test_confidence_clamped_high(self):
        r = MappingResult(clo_code="1.1", plo_code="K1", confidence=1.5, rationale="")
        assert r.confidence == 1.0

    def test_confidence_clamped_low(self):
        r = MappingResult(clo_code="1.1", plo_code="K1", confidence=-0.5, rationale="")
        assert r.confidence == 0.0

    def test_confidence_converted_to_float(self):
        r = MappingResult(clo_code="1.1", plo_code="K1", confidence="0.75", rationale="")
        assert r.confidence == 0.75
        assert isinstance(r.confidence, float)


# ===========================================================================
# Unit Tests: Prompt building and response parsing
# ===========================================================================

class TestPromptBuilding:

    def test_build_user_prompt_basic(self):
        prompt = _build_user_prompt(
            "MATH 101", "Calculus I", "Limits and derivatives",
            [{"code": "1.1", "text": "Understand limits", "category": "Knowledge"}],
            [{"code": "K1", "label": "K1", "description": "Apply math knowledge"}],
        )
        assert "MATH 101" in prompt
        assert "Calculus I" in prompt
        assert "Understand limits" in prompt
        assert "Apply math knowledge" in prompt

    def test_build_user_prompt_no_description(self):
        prompt = _build_user_prompt(
            "MATH 101", "Calculus I", None,
            [{"code": "1.1", "text": "Test", "category": ""}],
            [{"code": "K1", "label": "", "description": "Test PLO"}],
        )
        assert "Description:" not in prompt

    def test_build_user_prompt_long_description_truncated(self):
        long_desc = "x" * 600
        prompt = _build_user_prompt(
            "MATH 101", "Calculus I", long_desc,
            [{"code": "1.1", "text": "Test", "category": ""}],
            [],
        )
        assert "..." in prompt


class TestResponseParsing:

    def test_parse_valid_json(self):
        response = json.dumps([
            {"clo_code": "1.1", "plo_code": "K1", "confidence": 0.9, "rationale": "Good match"},
            {"clo_code": "1.2", "plo_code": "S1", "confidence": 0.7, "rationale": "OK match"},
        ])
        results = _parse_response(response)
        assert len(results) == 2
        assert results[0].clo_code == "1.1"
        assert results[0].plo_code == "K1"
        assert results[0].confidence == 0.9

    def test_parse_json_with_markdown_fences(self):
        response = '```json\n[{"clo_code": "1.1", "plo_code": "K1", "confidence": 0.8, "rationale": "test"}]\n```'
        results = _parse_response(response)
        assert len(results) == 1
        assert results[0].clo_code == "1.1"

    def test_parse_json_with_surrounding_text(self):
        response = 'Here are the mappings:\n[{"clo_code": "1.1", "plo_code": "K1", "confidence": 0.8, "rationale": "test"}]\nDone.'
        results = _parse_response(response)
        assert len(results) == 1

    def test_parse_invalid_json(self):
        results = _parse_response("This is not JSON at all")
        assert results == []

    def test_parse_empty_array(self):
        results = _parse_response("[]")
        assert results == []

    def test_parse_missing_fields_skipped(self):
        response = json.dumps([
            {"clo_code": "1.1"},  # missing plo_code
            {"plo_code": "K1"},  # missing clo_code
            {"clo_code": "1.2", "plo_code": "K2", "confidence": 0.8, "rationale": "ok"},
        ])
        results = _parse_response(response)
        assert len(results) == 1
        assert results[0].clo_code == "1.2"

    def test_parse_invalid_confidence_defaults(self):
        response = json.dumps([
            {"clo_code": "1.1", "plo_code": "K1", "confidence": "invalid", "rationale": "test"},
        ])
        results = _parse_response(response)
        assert len(results) == 1
        assert results[0].confidence == 0.5  # default


# ===========================================================================
# Unit Tests: Engine functions with mock provider
# ===========================================================================

class TestMapCourse:

    def test_map_course_basic(self, db_path):
        """Test basic mapping of CLOs to PLOs."""
        mock_results = [
            MappingResult(clo_code="1.1", plo_code="K1", confidence=0.9,
                          rationale="Limits align with mathematical knowledge"),
            MappingResult(clo_code="1.2", plo_code="K1", confidence=0.85,
                          rationale="Derivatives align with mathematical knowledge"),
            MappingResult(clo_code="2.1", plo_code="S1", confidence=0.8,
                          rationale="Optimization involves problem solving"),
        ]
        provider = MockProvider(mock_results)
        results = map_course(db_path, "MATH 101", "MATH", provider=provider)
        assert len(results) == 3
        assert results[0].clo_code == "1.1"
        assert results[0].plo_code == "K1"

    def test_map_course_stores_in_db(self, db_path):
        """Test that mappings are stored in the database."""
        mock_results = [
            MappingResult(clo_code="1.1", plo_code="K1", confidence=0.9,
                          rationale="Test rationale"),
        ]
        provider = MockProvider(mock_results)
        map_course(db_path, "MATH 101", "MATH", provider=provider)

        # Verify in DB
        mappings = review_mappings(db_path, "MATH 101", "MATH")
        assert len(mappings) >= 1
        found = [m for m in mappings if m["clo_code"] == "1.1" and m["plo_label"] == "K1"]
        assert len(found) == 1
        assert found[0]["mapping_source"] == "ai_suggested"
        assert found[0]["confidence"] == 0.9

    def test_map_course_skips_already_mapped(self, db_path):
        """Test that already-mapped CLOs are skipped."""
        # First mapping
        mock_results = [
            MappingResult(clo_code="1.1", plo_code="K1", confidence=0.9, rationale="First"),
            MappingResult(clo_code="1.2", plo_code="K2", confidence=0.85, rationale="Second"),
            MappingResult(clo_code="2.1", plo_code="S1", confidence=0.8, rationale="Third"),
        ]
        provider = MockProvider(mock_results)
        results1 = map_course(db_path, "MATH 101", "MATH", provider=provider)
        assert len(results1) == 3

        # Second mapping — should skip all (already mapped)
        results2 = map_course(db_path, "MATH 101", "MATH", provider=provider)
        assert len(results2) == 0

    def test_map_course_force_remaps(self, db_path):
        """Test that force=True re-maps already-mapped CLOs."""
        mock_results = [
            MappingResult(clo_code="1.1", plo_code="K1", confidence=0.9, rationale="First"),
        ]
        provider = MockProvider(mock_results)

        # First mapping
        map_course(db_path, "MATH 101", "MATH", provider=provider)

        # Force re-map
        new_results = [
            MappingResult(clo_code="1.1", plo_code="K2", confidence=0.95, rationale="Updated"),
            MappingResult(clo_code="1.2", plo_code="K1", confidence=0.8, rationale="New"),
            MappingResult(clo_code="2.1", plo_code="S1", confidence=0.7, rationale="New too"),
        ]
        provider2 = MockProvider(new_results)
        results = map_course(db_path, "MATH 101", "MATH", provider=provider2, force=True)
        assert len(results) == 3

    def test_map_course_unknown_course(self, db_path):
        """Test error when course not found."""
        provider = MockProvider()
        with pytest.raises(ValueError, match="Course not found"):
            map_course(db_path, "PHYS 999", "MATH", provider=provider)

    def test_map_course_no_clos(self, db_path):
        """Test error when course has no CLOs."""
        # Create a course with no CLOs
        conn = init_db(db_path)
        repo.upsert_course(conn, Course(course_code="MATH 999", course_title="Empty Course"))
        conn.close()

        provider = MockProvider()
        with pytest.raises(ValueError, match="No CLOs found"):
            map_course(db_path, "MATH 999", "MATH", provider=provider)

    def test_map_course_no_plos(self, db_path):
        """Test error when program has no PLO definitions."""
        # Create a program with no PLOs
        conn = init_db(db_path)
        repo.upsert_program(conn, Program(program_code="EMPTY"))
        conn.close()

        provider = MockProvider()
        with pytest.raises(ValueError, match="No PLO definitions found"):
            map_course(db_path, "MATH 101", "EMPTY", provider=provider)

    def test_map_course_unresolvable_codes_skipped(self, db_path):
        """Test that AI results with unknown codes are skipped gracefully."""
        mock_results = [
            MappingResult(clo_code="UNKNOWN", plo_code="K1", confidence=0.9, rationale="Bad CLO"),
            MappingResult(clo_code="1.1", plo_code="UNKNOWN_PLO", confidence=0.9, rationale="Bad PLO"),
            MappingResult(clo_code="1.1", plo_code="K1", confidence=0.9, rationale="Good"),
        ]
        provider = MockProvider(mock_results)
        results = map_course(db_path, "MATH 101", "MATH", provider=provider)
        # All 3 returned by provider, but only 1 stored successfully
        assert len(results) == 3  # returned by provider

        mappings = review_mappings(db_path, "MATH 101", "MATH")
        # Only the valid one should be stored
        assert len(mappings) == 1
        assert mappings[0]["clo_code"] == "1.1"


class TestMapProgram:

    def test_map_program_multiple_courses(self, db_path):
        """Test mapping all courses in a program."""
        provider = MockProvider()  # uses default logic (map to first PLO)
        all_results = map_program(db_path, "MATH", provider=provider)
        assert "MATH 101" in all_results
        assert "MATH 201" in all_results
        assert len(all_results["MATH 101"]) > 0
        assert len(all_results["MATH 201"]) > 0

    def test_map_program_empty(self, db_path):
        """Test mapping a program with no courses."""
        conn = init_db(db_path)
        repo.upsert_program(conn, Program(program_code="EMPTY"))
        conn.close()

        provider = MockProvider()
        all_results = map_program(db_path, "EMPTY", provider=provider)
        assert all_results == {}


class TestReviewMappings:

    def test_review_no_mappings(self, db_path):
        """Test review when no mappings exist."""
        mappings = review_mappings(db_path, "MATH 101", "MATH")
        assert mappings == []

    def test_review_with_mappings(self, db_path):
        """Test review returns mapping details."""
        # Create a mapping
        provider = MockProvider([
            MappingResult(clo_code="1.1", plo_code="K1", confidence=0.9, rationale="Test"),
        ])
        map_course(db_path, "MATH 101", "MATH", provider=provider)

        mappings = review_mappings(db_path, "MATH 101", "MATH")
        assert len(mappings) == 1
        m = mappings[0]
        assert m["clo_code"] == "1.1"
        assert m["plo_label"] == "K1"
        assert m["mapping_source"] == "ai_suggested"
        assert m["confidence"] == 0.9
        assert m["rationale"] == "Test"
        assert not m["approved"]

    def test_review_unknown_course(self, db_path):
        """Test review for non-existent course."""
        mappings = review_mappings(db_path, "PHYS 999", "MATH")
        assert mappings == []


class TestApproveMappings:

    def test_approve_updates_db(self, db_path):
        """Test that approve sets approved flag and timestamp."""
        # Create mappings
        provider = MockProvider([
            MappingResult(clo_code="1.1", plo_code="K1", confidence=0.9, rationale="Test"),
            MappingResult(clo_code="1.2", plo_code="K2", confidence=0.85, rationale="Test2"),
        ])
        map_course(db_path, "MATH 101", "MATH", provider=provider)

        # Approve
        count = approve_mappings(db_path, "MATH 101", "MATH")
        assert count == 2

        # Verify
        mappings = review_mappings(db_path, "MATH 101", "MATH")
        for m in mappings:
            assert m["approved"]
            assert m["approved_at"] is not None

    def test_approve_no_pending(self, db_path):
        """Test approve when no pending mappings exist."""
        count = approve_mappings(db_path, "MATH 101", "MATH")
        assert count == 0

    def test_approve_idempotent(self, db_path):
        """Test that approving twice doesn't change count."""
        provider = MockProvider([
            MappingResult(clo_code="1.1", plo_code="K1", confidence=0.9, rationale="Test"),
        ])
        map_course(db_path, "MATH 101", "MATH", provider=provider)

        count1 = approve_mappings(db_path, "MATH 101", "MATH")
        assert count1 == 1

        count2 = approve_mappings(db_path, "MATH 101", "MATH")
        assert count2 == 0  # already approved

    def test_approve_unknown_course(self, db_path):
        """Test approve for non-existent course."""
        count = approve_mappings(db_path, "PHYS 999", "MATH")
        assert count == 0


class TestExportPloMatrix:

    def test_export_empty(self, db_path):
        """Test export when no mappings exist."""
        matrix = export_plo_matrix(db_path, "MATH")
        assert matrix == {}

    def test_export_with_mappings(self, db_path):
        """Test export returns correct matrix structure."""
        provider = MockProvider([
            MappingResult(clo_code="1.1", plo_code="K1", confidence=0.9, rationale="Test"),
            MappingResult(clo_code="1.2", plo_code="K2", confidence=0.85, rationale="Test"),
            MappingResult(clo_code="2.1", plo_code="S1", confidence=0.8, rationale="Test"),
        ])
        map_course(db_path, "MATH 101", "MATH", provider=provider)

        matrix = export_plo_matrix(db_path, "MATH")
        assert "MATH 101" in matrix
        assert "1.1" in matrix["MATH 101"]
        assert "K1" in matrix["MATH 101"]["1.1"]
        assert "1.2" in matrix["MATH 101"]
        assert "K2" in matrix["MATH 101"]["1.2"]

    def test_export_no_duplicates(self, db_path):
        """Test that PLO codes are not duplicated in the matrix."""
        provider = MockProvider([
            MappingResult(clo_code="1.1", plo_code="K1", confidence=0.9, rationale="Test"),
        ])
        map_course(db_path, "MATH 101", "MATH", provider=provider)

        matrix = export_plo_matrix(db_path, "MATH")
        plo_list = matrix["MATH 101"]["1.1"]
        assert len(plo_list) == len(set(plo_list))


class TestGetDefaultProvider:

    def test_raises_without_api_key(self):
        """Test that get_default_provider raises if no API key."""
        with patch.dict(os.environ, {}, clear=True):
            # Ensure ANTHROPIC_API_KEY is not set
            env = os.environ.copy()
            env.pop("ANTHROPIC_API_KEY", None)
            env.pop("OPENROUTER_API_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(ValueError, match="No API key found"):
                    get_default_provider()

    def test_returns_anthropic_provider(self):
        """Test that get_default_provider returns AnthropicProvider when key is set."""
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "test-key-not-real"}):
            provider = get_default_provider()
            assert isinstance(provider, AnthropicProvider)


# ===========================================================================
# Integration tests: mock the Anthropic API, not the DB
# ===========================================================================

class TestAnthropicProviderIntegration:

    def test_full_flow_mock_api(self, db_path):
        """Test full flow: map_course -> store -> review -> approve with mocked API."""
        # Create a mock Anthropic response
        mock_response_data = [
            {"clo_code": "1.1", "plo_code": "K1", "confidence": 0.92,
             "rationale": "Limits align with mathematical knowledge application"},
            {"clo_code": "1.2", "plo_code": "K1", "confidence": 0.88,
             "rationale": "Differentiation is core mathematical knowledge"},
            {"clo_code": "2.1", "plo_code": "S1", "confidence": 0.85,
             "rationale": "Optimization problems require systematic problem-solving"},
        ]
        mock_response_text = json.dumps(mock_response_data)

        # Create a mock Message object
        mock_block = MagicMock()
        mock_block.text = mock_response_text
        mock_message = MagicMock()
        mock_message.content = [mock_block]

        # Patch the Anthropic client
        with patch("anthropic.Anthropic") as MockAnthropicClass:
            mock_client = MagicMock()
            mock_client.messages.create.return_value = mock_message
            MockAnthropicClass.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key-not-real")
            # Override internal client
            provider._client = mock_client

            # Step 1: Map
            results = map_course(db_path, "MATH 101", "MATH", provider=provider)
            assert len(results) == 3

            # Step 2: Review
            mappings = review_mappings(db_path, "MATH 101", "MATH")
            assert len(mappings) == 3
            for m in mappings:
                assert m["mapping_source"] == "ai_suggested"
                assert not m["approved"]

            # Step 3: Approve
            count = approve_mappings(db_path, "MATH 101", "MATH")
            assert count == 3

            # Step 4: Verify approved
            mappings_after = review_mappings(db_path, "MATH 101", "MATH")
            for m in mappings_after:
                assert m["approved"]

    def test_anthropic_provider_empty_clos(self):
        """Test that provider returns empty list for empty CLOs."""
        with patch("anthropic.Anthropic"):
            provider = AnthropicProvider(api_key="test-key-not-real")
            results = provider.map_clos_to_plos(
                "MATH 101", "Calculus I", None, [], [{"code": "K1", "label": "K1", "description": "test"}]
            )
            assert results == []

    def test_anthropic_provider_empty_plos(self):
        """Test that provider returns empty list for empty PLOs."""
        with patch("anthropic.Anthropic"):
            provider = AnthropicProvider(api_key="test-key-not-real")
            results = provider.map_clos_to_plos(
                "MATH 101", "Calculus I", None,
                [{"code": "1.1", "text": "test", "category": "K"}], []
            )
            assert results == []

    def test_anthropic_provider_no_api_key(self):
        """Test that constructor raises without API key."""
        with patch.dict(os.environ, {}, clear=True):
            env = os.environ.copy()
            env.pop("ANTHROPIC_API_KEY", None)
            with patch.dict(os.environ, env, clear=True):
                with pytest.raises(ValueError, match="API key required"):
                    AnthropicProvider()

    def test_anthropic_provider_auth_error(self, db_path):
        """Test handling of authentication errors."""
        import anthropic

        with patch("anthropic.Anthropic") as MockAnthropicClass:
            mock_client = MagicMock()
            # Create a proper auth error
            mock_response = MagicMock()
            mock_response.status_code = 401
            mock_response.headers = {}
            mock_client.messages.create.side_effect = anthropic.AuthenticationError(
                message="Invalid API key",
                response=mock_response,
                body=None,
            )
            MockAnthropicClass.return_value = mock_client

            provider = AnthropicProvider(api_key="bad-key")
            provider._client = mock_client

            with pytest.raises(RuntimeError, match="authentication failed"):
                provider.map_clos_to_plos(
                    "MATH 101", "Calculus I", None,
                    [{"code": "1.1", "text": "test", "category": "K"}],
                    [{"code": "K1", "label": "K1", "description": "test"}],
                )

    def test_anthropic_provider_rate_limit(self, db_path):
        """Test handling of rate limit errors."""
        import anthropic

        with patch("anthropic.Anthropic") as MockAnthropicClass:
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.status_code = 429
            mock_response.headers = {}
            mock_client.messages.create.side_effect = anthropic.RateLimitError(
                message="Rate limited",
                response=mock_response,
                body=None,
            )
            MockAnthropicClass.return_value = mock_client

            provider = AnthropicProvider(api_key="test-key")
            provider._client = mock_client

            with pytest.raises(RuntimeError, match="rate limit"):
                provider.map_clos_to_plos(
                    "MATH 101", "Calculus I", None,
                    [{"code": "1.1", "text": "test", "category": "K"}],
                    [{"code": "K1", "label": "K1", "description": "test"}],
                )


class TestForceRemapPreservesExtracted:

    def test_force_preserves_extracted_mappings(self, db_path):
        """Test that force=True only deletes ai_suggested, not extracted mappings."""
        # Manually insert an extracted mapping
        conn = init_db(db_path)
        course = repo.get_course(conn, "MATH 101")
        clos = repo.get_course_clos(conn, course.id)
        plos = repo.get_plos_for_program(conn, "MATH")

        repo.upsert_clo_plo_mapping(conn, CloPloMapping(
            course_clo_id=clos[0].id,
            plo_id=plos[0].id,
            program_code="MATH",
            mapping_source="extracted",
            confidence=1.0,
            rationale="From source document",
        ))
        conn.close()

        # Map with AI
        provider = MockProvider([
            MappingResult(clo_code="1.2", plo_code="K2", confidence=0.8, rationale="AI suggestion"),
        ])
        map_course(db_path, "MATH 101", "MATH", provider=provider)

        # Force re-map
        provider2 = MockProvider([
            MappingResult(clo_code="1.2", plo_code="K1", confidence=0.9, rationale="Updated AI"),
        ])
        map_course(db_path, "MATH 101", "MATH", provider=provider2, force=True)

        # Check that extracted mapping is preserved
        mappings = review_mappings(db_path, "MATH 101", "MATH")
        extracted = [m for m in mappings if m["mapping_source"] == "extracted"]
        ai_suggested = [m for m in mappings if m["mapping_source"] == "ai_suggested"]

        assert len(extracted) == 1
        assert extracted[0]["clo_code"] == "1.1"
        assert len(ai_suggested) >= 1


# ===========================================================================
# Real API tests (gated)
# ===========================================================================

@pytest.mark.skipif(
    not os.environ.get("ABET_TEST_API"),
    reason="Set ABET_TEST_API=1 to run real API tests",
)
class TestRealAPI:

    def test_real_anthropic_mapping(self, db_path):
        """Test actual API call to Anthropic (requires API key)."""
        provider = AnthropicProvider()
        results = provider.map_clos_to_plos(
            course_code="MATH 101",
            course_title="Calculus I",
            course_description="Limits, continuity, differentiation, and integration.",
            clos=[
                {"code": "1.1", "text": "Understand limits and continuity of functions", "category": "Knowledge"},
                {"code": "2.1", "text": "Solve optimization problems using calculus", "category": "Skills"},
            ],
            plos=[
                {"code": "K1", "label": "K1", "description": "Apply mathematical knowledge"},
                {"code": "S1", "label": "S1", "description": "Solve mathematical problems systematically"},
            ],
        )
        assert len(results) > 0
        for r in results:
            assert r.clo_code in ("1.1", "2.1")
            assert r.plo_code in ("K1", "S1")
            assert 0.0 <= r.confidence <= 1.0
            assert r.rationale
