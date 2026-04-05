"""Abstract base class for AI mapping providers.

Defines the interface that all CLO-PLO mapping providers must implement.
This allows swapping between different AI backends (Anthropic, OpenAI,
OpenRouter, etc.) without changing the mapping engine logic.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class MappingResult:
    """A single CLO-to-PLO mapping suggestion from an AI provider.

    Attributes:
        clo_code: The CLO identifier (e.g., "1.1", "K1").
        plo_code: The PLO identifier (e.g., "K1", "MATH_PLO_K1").
        confidence: Confidence score from 0.0 to 1.0.
        rationale: AI-generated explanation for why this mapping was suggested.
    """

    clo_code: str
    plo_code: str
    confidence: float
    rationale: str

    def __post_init__(self) -> None:
        """Validate confidence is within range."""
        self.confidence = max(0.0, min(1.0, float(self.confidence)))


class MappingProvider(ABC):
    """Abstract base class for AI mapping providers.

    Subclasses must implement ``map_clos_to_plos`` which takes course
    information and returns suggested CLO-PLO mappings.
    """

    @abstractmethod
    def map_clos_to_plos(
        self,
        course_code: str,
        course_title: str,
        course_description: str | None,
        clos: list[dict],
        plos: list[dict],
    ) -> list[MappingResult]:
        """Map CLOs to PLOs using AI.

        Args:
            course_code: The course code (e.g., "MATH 101").
            course_title: The course title.
            course_description: Optional catalog description.
            clos: List of CLO dicts with keys: code, text, category.
            plos: List of PLO dicts with keys: code, label, description.

        Returns:
            List of MappingResult objects, one per suggested CLO-PLO pair.
        """
        ...
