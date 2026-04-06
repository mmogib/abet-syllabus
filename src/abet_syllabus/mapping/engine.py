"""CLO-PLO mapping engine.

Orchestrates the mapping workflow: loads data from the database, delegates
to an AI provider for unmapped CLOs, stores results, and provides review
and approval workflows.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from abet_syllabus.db import repository as repo
from abet_syllabus.db.models import CloPloMapping
from abet_syllabus.db.schema import init_db

from .provider import MappingProvider, MappingResult

logger = logging.getLogger(__name__)


def get_default_provider(
    provider_name: str | None = None,
    model: str | None = None,
) -> MappingProvider:
    """Get a mapping provider by name, or auto-detect from available API keys.

    Provider resolution order when *provider_name* is ``None``:
    1. If ``OPENROUTER_API_KEY`` is set -> OpenRouterProvider
    2. If ``ANTHROPIC_API_KEY`` is set -> AnthropicProvider
    3. Raise ValueError

    Args:
        provider_name: ``"anthropic"``, ``"openrouter"``, or ``None`` for auto.
        model: Optional model identifier override.  When ``None`` the
            provider's default model is used.

    Returns:
        An initialized MappingProvider.

    Raises:
        ValueError: If no API key is available for the requested provider.
    """
    import os

    def _kwargs() -> dict:
        """Build keyword arguments for provider constructors."""
        kw: dict = {}
        if model is not None:
            kw["model"] = model
        return kw

    if provider_name == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(**_kwargs())

    if provider_name == "openrouter":
        from .openrouter_provider import OpenRouterProvider
        return OpenRouterProvider(**_kwargs())

    # Auto-detect
    if os.environ.get("OPENROUTER_API_KEY"):
        from .openrouter_provider import OpenRouterProvider
        return OpenRouterProvider(**_kwargs())

    if os.environ.get("ANTHROPIC_API_KEY"):
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(**_kwargs())

    raise ValueError(
        "No API key found. Set OPENROUTER_API_KEY or ANTHROPIC_API_KEY "
        "environment variable."
    )


def _clos_to_dicts(clos: list) -> list[dict]:
    """Convert CourseClo objects to dicts for the provider."""
    return [
        {
            "code": clo.clo_code,
            "text": clo.clo_text,
            "category": clo.clo_category,
        }
        for clo in clos
    ]


def _plos_to_dicts(plos: list) -> list[dict]:
    """Convert PloDefinition objects to dicts for the provider."""
    return [
        {
            "code": plo.plo_code,
            "label": plo.plo_label,
            "description": plo.plo_description,
        }
        for plo in plos
    ]


def _get_mapped_clo_codes(conn, course_id: int, program_code: str) -> set[str]:
    """Return set of CLO codes that already have mappings for a course/program."""
    rows = conn.execute(
        """SELECT DISTINCT c.clo_code
           FROM clo_plo_mappings m
           JOIN course_clos c ON m.course_clo_id = c.id
           WHERE c.course_id = ? AND m.program_code = ?""",
        (course_id, program_code),
    ).fetchall()
    return {r["clo_code"] for r in rows}


def _resolve_plo_id(conn, plo_code: str, program_code: str) -> int | None:
    """Resolve a PLO code to its database ID for a program.

    Tries matching against both plo_code and plo_label fields.
    Handles AI responses like "MATH_PLO_1 (SO1)" by trying:
    1. Exact match on plo_code and plo_label
    2. Stripped version without parenthetical (e.g. "MATH_PLO_1")
    3. Content inside parentheses (e.g. "SO1")
    """
    import re

    candidates = [plo_code.strip()]

    # Extract parts if AI returned "CODE (LABEL)" format
    paren_match = re.match(r"^(.+?)\s*\((.+?)\)\s*$", plo_code)
    if paren_match:
        candidates.append(paren_match.group(1).strip())
        candidates.append(paren_match.group(2).strip())

    for candidate in candidates:
        # Try plo_code
        row = conn.execute(
            "SELECT id FROM plo_definitions WHERE plo_code = ? AND program_code = ?",
            (candidate, program_code),
        ).fetchone()
        if row:
            return row["id"]

        # Try plo_label
        row = conn.execute(
            "SELECT id FROM plo_definitions WHERE plo_label = ? AND program_code = ?",
            (candidate, program_code),
        ).fetchone()
        if row:
            return row["id"]

        # Try aliases
        row = conn.execute(
            "SELECT plo_id FROM plo_aliases WHERE alias = ? AND program_code = ?",
            (candidate, program_code),
        ).fetchone()
        if row:
            return row["plo_id"]

    return None


def _resolve_clo_id(conn, clo_code: str, course_id: int) -> int | None:
    """Resolve a CLO code to its database ID for a course.

    Handles AI responses with extra formatting (e.g. "CLO 1.1" → "1.1").
    """
    import re

    candidates = [clo_code.strip()]

    # Strip "CLO" prefix if AI added it
    stripped = re.sub(r"^CLO[- ]*", "", clo_code, flags=re.IGNORECASE).strip()
    if stripped and stripped != clo_code.strip():
        candidates.append(stripped)

    for candidate in candidates:
        row = conn.execute(
            "SELECT id FROM course_clos WHERE clo_code = ? AND course_id = ?",
            (candidate, course_id),
        ).fetchone()
        if row:
            return row["id"]
    return None


def map_course(
    db_path: str | Path,
    course_code: str,
    program_code: str,
    provider: MappingProvider | None = None,
    force: bool = False,
) -> list[MappingResult]:
    """Map CLOs to PLOs for a course in a program.

    Loads CLOs and PLOs from the database, calls the AI provider for
    unmapped CLOs, and stores the results with source="ai_suggested".

    Args:
        db_path: Path to the SQLite database.
        course_code: The course code (e.g., "MATH 101").
        program_code: The program code (e.g., "MATH").
        provider: A MappingProvider instance. Uses default if None.
        force: If True, re-map even if mappings already exist.

    Returns:
        List of MappingResult objects for the newly created mappings.

    Raises:
        ValueError: If the course or program is not found, or no CLOs/PLOs exist.
        RuntimeError: If the AI provider fails.
    """
    conn = init_db(db_path)
    try:
        # Load course
        course = repo.get_course(conn, course_code)
        if course is None:
            raise ValueError(f"Course not found: {course_code}")

        # Load CLOs
        clos = repo.get_course_clos(conn, course.id)
        if not clos:
            raise ValueError(f"No CLOs found for course {course_code}")

        # Load PLOs
        plos = repo.get_plos_for_program(conn, program_code)
        if not plos:
            raise ValueError(
                f"No PLO definitions found for program {program_code}. "
                "Load PLOs first with: abet-syllabus ingest-plos <csv>"
            )

        # Determine which CLOs need mapping
        already_mapped = _get_mapped_clo_codes(conn, course.id, program_code)

        if force:
            # Delete existing AI-suggested mappings (preserve extracted ones)
            conn.execute(
                """DELETE FROM clo_plo_mappings
                   WHERE course_clo_id IN (
                       SELECT id FROM course_clos WHERE course_id = ?
                   )
                   AND program_code = ?
                   AND mapping_source = 'ai_suggested'""",
                (course.id, program_code),
            )
            conn.commit()
            clos_to_map = clos
        else:
            clos_to_map = [c for c in clos if c.clo_code not in already_mapped]

        if not clos_to_map:
            logger.info("All CLOs already mapped for %s in %s", course_code, program_code)
            return []

        # Get provider
        if provider is None:
            provider = get_default_provider()

        # Call the AI provider
        clo_dicts = _clos_to_dicts(clos_to_map)
        plo_dicts = _plos_to_dicts(plos)

        results = provider.map_clos_to_plos(
            course_code=course_code,
            course_title=course.course_title,
            course_description=course.catalog_description or None,
            clos=clo_dicts,
            plos=plo_dicts,
        )

        # Store results in the database
        stored_count = 0
        for result in results:
            clo_id = _resolve_clo_id(conn, result.clo_code, course.id)
            if clo_id is None:
                logger.warning(
                    "CLO code '%s' from AI not found in DB for %s",
                    result.clo_code, course_code,
                )
                continue

            plo_id = _resolve_plo_id(conn, result.plo_code, program_code)
            if plo_id is None:
                logger.warning(
                    "PLO code '%s' from AI not found in DB for program %s",
                    result.plo_code, program_code,
                )
                continue

            repo.upsert_clo_plo_mapping(conn, CloPloMapping(
                course_clo_id=clo_id,
                plo_id=plo_id,
                program_code=program_code,
                mapping_source="ai_suggested",
                confidence=result.confidence,
                rationale=result.rationale,
                approved=False,
            ))
            stored_count += 1

        logger.info(
            "Stored %d/%d AI mappings for %s in %s",
            stored_count, len(results), course_code, program_code,
        )
        return results

    finally:
        conn.close()


def map_program(
    db_path: str | Path,
    program_code: str,
    provider: MappingProvider | None = None,
    force: bool = False,
) -> dict[str, list[MappingResult]]:
    """Map all courses in a program.

    Args:
        db_path: Path to the SQLite database.
        program_code: The program code (e.g., "MATH").
        provider: A MappingProvider instance. Uses default if None.
        force: If True, re-map even if mappings already exist.

    Returns:
        Dict mapping course_code to list of MappingResult for that course.
    """
    conn = init_db(db_path)
    try:
        courses = repo.get_all_courses(conn, program_code=program_code)
    finally:
        conn.close()

    if not courses:
        logger.info("No courses found for program %s", program_code)
        return {}

    # Resolve provider once to avoid repeated key lookups
    if provider is None:
        provider = get_default_provider()

    all_results: dict[str, list[MappingResult]] = {}
    for course in courses:
        try:
            results = map_course(
                db_path, course.course_code, program_code,
                provider=provider, force=force,
            )
            all_results[course.course_code] = results
        except ValueError as exc:
            logger.warning("Skipping %s: %s", course.course_code, exc)
            all_results[course.course_code] = []
        except RuntimeError as exc:
            logger.error("API error for %s: %s", course.course_code, exc)
            # Re-raise API errors so the caller can handle them
            raise

    return all_results


def review_mappings(
    db_path: str | Path,
    course_code: str,
    program_code: str,
) -> list[dict]:
    """Get current mappings for review.

    Returns a list of dicts with mapping details including CLO text,
    PLO label/description, confidence, rationale, source, and approval status.

    Args:
        db_path: Path to the SQLite database.
        course_code: The course code.
        program_code: The program code.

    Returns:
        List of mapping detail dicts.
    """
    conn = init_db(db_path)
    try:
        course = repo.get_course(conn, course_code)
        if course is None:
            return []

        return repo.get_mappings_for_course(conn, course.id, program_code)
    finally:
        conn.close()


def approve_mappings(
    db_path: str | Path,
    course_code: str,
    program_code: str,
) -> int:
    """Approve all ai_suggested mappings for a course/program.

    Sets approved=True and records the approval timestamp.

    Args:
        db_path: Path to the SQLite database.
        course_code: The course code.
        program_code: The program code.

    Returns:
        Number of mappings approved.
    """
    conn = init_db(db_path)
    try:
        course = repo.get_course(conn, course_code)
        if course is None:
            return 0

        now = datetime.now(timezone.utc).isoformat()
        cur = conn.execute(
            """UPDATE clo_plo_mappings
               SET approved = 1, approved_at = ?
               WHERE course_clo_id IN (
                   SELECT id FROM course_clos WHERE course_id = ?
               )
               AND program_code = ?
               AND mapping_source = 'ai_suggested'
               AND approved = 0""",
            (now, course.id, program_code),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def export_plo_matrix(
    db_path: str | Path,
    program_code: str,
) -> dict:
    """Export CLO-PLO mapping matrix for a program.

    Returns a nested dict: {course_code: {clo_code: [plo_codes]}}.

    Args:
        db_path: Path to the SQLite database.
        program_code: The program code.

    Returns:
        Dict with the mapping matrix structure.
    """
    conn = init_db(db_path)
    try:
        courses = repo.get_all_courses(conn, program_code=program_code)
        matrix: dict[str, dict[str, list[str]]] = {}

        for course in courses:
            mappings = repo.get_mappings_for_course(conn, course.id, program_code)
            if not mappings:
                continue

            course_map: dict[str, list[str]] = {}
            for m in mappings:
                clo_code = m["clo_code"]
                plo_label = m["plo_label"]
                if clo_code not in course_map:
                    course_map[clo_code] = []
                if plo_label not in course_map[clo_code]:
                    course_map[clo_code].append(plo_label)

            if course_map:
                matrix[course.course_code] = course_map

        return matrix
    finally:
        conn.close()
