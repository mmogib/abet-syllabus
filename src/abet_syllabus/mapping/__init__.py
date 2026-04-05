"""AI-powered CLO-PLO mapping engine.

Public API
----------
- ``MappingProvider`` — abstract base class for AI providers
- ``MappingResult`` — dataclass for a single mapping suggestion
- ``AnthropicProvider`` — Anthropic/Claude implementation
- ``map_course`` — map CLOs to PLOs for a single course
- ``map_program`` — map all courses in a program
- ``review_mappings`` — retrieve current mappings for review
- ``approve_mappings`` — approve AI-suggested mappings
- ``export_plo_matrix`` — export a full CLO-PLO matrix for a program
- ``get_default_provider`` — get the default (Anthropic) provider
"""

from .provider import MappingProvider, MappingResult
from .anthropic_provider import AnthropicProvider
from .engine import (
    approve_mappings,
    export_plo_matrix,
    get_default_provider,
    map_course,
    map_program,
    review_mappings,
)

__all__ = [
    "AnthropicProvider",
    "MappingProvider",
    "MappingResult",
    "approve_mappings",
    "export_plo_matrix",
    "get_default_provider",
    "map_course",
    "map_program",
    "review_mappings",
]
