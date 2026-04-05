"""Anthropic (Claude) provider for CLO-PLO mapping.

Uses the Anthropic Python SDK to call the Claude API for mapping
Course Learning Outcomes to Program Learning Outcomes.  The API key
is read exclusively from the ANTHROPIC_API_KEY environment variable.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from .provider import MappingProvider, MappingResult

logger = logging.getLogger(__name__)

# Model to use for structured mapping (cost-effective, fast)
DEFAULT_MODEL = "claude-sonnet-4-20250514"

SYSTEM_PROMPT = """\
You are an expert in ABET accreditation and university curriculum design.
Your task is to map Course Learning Outcomes (CLOs) to Program Learning Outcomes (PLOs).

Guidelines:
- Each CLO should map to 1-3 PLOs that are the best semantic match.
- Only map a CLO to a PLO when there is genuine alignment between what the CLO teaches
  and what the PLO expects graduates to demonstrate.
- Provide a confidence score from 0.0 to 1.0 for each mapping:
  - 0.9-1.0: Very strong, obvious alignment
  - 0.7-0.89: Strong alignment
  - 0.5-0.69: Moderate alignment, plausible but not certain
  - Below 0.5: Weak alignment, only include if no better option exists
- Provide a brief rationale (1-2 sentences) for each mapping explaining the alignment.
- Do NOT force mappings. If a CLO does not clearly align with any PLO, map it to the
  single best candidate with an appropriately low confidence score.

Respond ONLY with a JSON array. Each element must have exactly these keys:
  "clo_code", "plo_code", "confidence", "rationale"

Example:
[
  {"clo_code": "1.1", "plo_code": "K1", "confidence": 0.92, "rationale": "CLO focuses on applying mathematical knowledge, directly aligned with PLO K1."},
  {"clo_code": "1.1", "plo_code": "S1", "confidence": 0.65, "rationale": "CLO involves problem-solving skills, partially aligned with PLO S1."}
]
"""


def _build_user_prompt(
    course_code: str,
    course_title: str,
    course_description: str | None,
    clos: list[dict],
    plos: list[dict],
) -> str:
    """Build the user prompt with course info, CLOs, and PLOs."""
    parts: list[str] = []

    parts.append(f"Course: {course_code} - {course_title}")
    if course_description:
        # Truncate very long descriptions
        desc = course_description[:500]
        if len(course_description) > 500:
            desc += "..."
        parts.append(f"Description: {desc}")
    parts.append("")

    parts.append("=== Course Learning Outcomes (CLOs) ===")
    for clo in clos:
        code = clo.get("code", "?")
        text = clo.get("text", "")
        category = clo.get("category", "")
        cat_label = f" [{category}]" if category else ""
        parts.append(f"  {code}{cat_label}: {text}")
    parts.append("")

    parts.append("=== Program Learning Outcomes (PLOs) ===")
    for plo in plos:
        code = plo.get("code", "?")
        label = plo.get("label", "")
        description = plo.get("description", "")
        label_str = f" ({label})" if label else ""
        parts.append(f"  {code}{label_str}: {description}")
    parts.append("")

    parts.append(
        "Map each CLO to the most relevant PLOs. "
        "Return ONLY a JSON array with no other text."
    )

    return "\n".join(parts)


def _parse_response(response_text: str) -> list[MappingResult]:
    """Parse the AI response JSON into MappingResult objects.

    Handles cases where the model wraps JSON in markdown code fences.
    """
    text = response_text.strip()

    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()

    # Find the JSON array
    bracket_start = text.find("[")
    bracket_end = text.rfind("]")
    if bracket_start == -1 or bracket_end == -1:
        logger.error("No JSON array found in AI response: %s", text[:200])
        return []

    json_str = text[bracket_start : bracket_end + 1]

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.error("Failed to parse AI response JSON: %s", exc)
        return []

    if not isinstance(data, list):
        logger.error("Expected JSON array, got %s", type(data).__name__)
        return []

    results: list[MappingResult] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        clo_code = str(item.get("clo_code", "")).strip()
        plo_code = str(item.get("plo_code", "")).strip()
        if not clo_code or not plo_code:
            continue

        try:
            confidence = float(item.get("confidence", 0.5))
        except (TypeError, ValueError):
            confidence = 0.5

        rationale = str(item.get("rationale", "")).strip()

        results.append(MappingResult(
            clo_code=clo_code,
            plo_code=plo_code,
            confidence=confidence,
            rationale=rationale,
        ))

    return results


class AnthropicProvider(MappingProvider):
    """CLO-PLO mapping provider using the Anthropic Claude API.

    The API key must be set in the ``ANTHROPIC_API_KEY`` environment variable.
    Keys are never logged, stored in the database, or written to disk.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = DEFAULT_MODEL,
        max_tokens: int = 4096,
    ) -> None:
        """Initialize the Anthropic provider.

        Args:
            api_key: API key. If None, reads from ANTHROPIC_API_KEY env var.
            model: Model identifier to use.
            max_tokens: Maximum tokens in the response.

        Raises:
            ValueError: If no API key is available.
        """
        resolved_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "Anthropic API key required. Set the ANTHROPIC_API_KEY "
                "environment variable or pass api_key to the constructor."
            )

        # Import here to avoid import errors when anthropic is not installed
        try:
            import anthropic
        except ImportError as exc:
            raise ImportError(
                "The 'anthropic' package is required for the Anthropic provider. "
                "Install it with: pip install anthropic"
            ) from exc

        self._client = anthropic.Anthropic(api_key=resolved_key)
        self._model = model
        self._max_tokens = max_tokens

    def map_clos_to_plos(
        self,
        course_code: str,
        course_title: str,
        course_description: str | None,
        clos: list[dict],
        plos: list[dict],
    ) -> list[MappingResult]:
        """Map CLOs to PLOs using the Claude API.

        Args:
            course_code: The course code (e.g., "MATH 101").
            course_title: The course title.
            course_description: Optional catalog description.
            clos: List of CLO dicts with keys: code, text, category.
            plos: List of PLO dicts with keys: code, label, description.

        Returns:
            List of MappingResult objects.

        Raises:
            RuntimeError: If the API call fails.
        """
        import anthropic

        if not clos:
            return []
        if not plos:
            return []

        user_prompt = _build_user_prompt(
            course_code, course_title, course_description, clos, plos
        )

        try:
            message = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.AuthenticationError:
            raise RuntimeError(
                "Anthropic API authentication failed. "
                "Check your ANTHROPIC_API_KEY environment variable."
            )
        except anthropic.RateLimitError:
            raise RuntimeError(
                "Anthropic API rate limit exceeded. Please try again later."
            )
        except anthropic.APIConnectionError:
            raise RuntimeError(
                "Could not connect to the Anthropic API. "
                "Check your network connection."
            )
        except anthropic.APIStatusError as exc:
            raise RuntimeError(
                f"Anthropic API error (status {exc.status_code}): {exc.message}"
            )

        # Extract text from the response
        response_text = ""
        for block in message.content:
            if hasattr(block, "text"):
                response_text += block.text

        if not response_text:
            logger.warning("Empty response from Anthropic API for %s", course_code)
            return []

        results = _parse_response(response_text)
        logger.info(
            "Mapped %d CLOs for %s: %d mapping suggestions",
            len(clos), course_code, len(results),
        )
        return results
