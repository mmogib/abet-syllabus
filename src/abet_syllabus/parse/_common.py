"""Shared utilities for Format A and Format B parsers.

Provides common helpers for text cleaning, percentage/float parsing,
category normalization, and PLO code extraction.
"""

from __future__ import annotations

import re


# --- CLO category names (canonical) ---
CATEGORY_KNOWLEDGE = "Knowledge and Understanding"
CATEGORY_SKILLS = "Skills"
CATEGORY_VALUES = "Values"

CATEGORY_MAP: dict[str, str] = {
    "knowledge and understanding": CATEGORY_KNOWLEDGE,
    "knowledge": CATEGORY_KNOWLEDGE,
    "skills": CATEGORY_SKILLS,
    "skill": CATEGORY_SKILLS,
    "values": CATEGORY_VALUES,
    "value": CATEGORY_VALUES,
    "values, autonomy, and responsibility": CATEGORY_VALUES,
    "values and responsibility": CATEGORY_VALUES,
}


def normalize_category(raw: str) -> str:
    """Map a raw category string to its canonical form."""
    key = raw.strip().lower().rstrip(".")
    return CATEGORY_MAP.get(key, raw.strip())


def clean_text(text: str) -> str:
    """Clean extracted text: collapse internal newlines, strip."""
    text = re.sub(r"\s*\n\s*", " ", text)
    return text.strip()


def parse_percentage(raw: str) -> float | None:
    """Extract a numeric percentage from a string like '25%' or '25.0%'."""
    m = re.search(r"([\d.]+)\s*%+", raw)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


def parse_float(raw: str) -> float | None:
    """Try to parse a float from a string."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def extract_plo_codes(raw: str) -> list[str]:
    """Extract PLO codes from a raw string.

    Handles formats like: ``"K1"``, ``"K1, S2"``, ``"K.1"``, ``"a, b"``.
    """
    if not raw or raw.strip().lower() in ("none", "n/a", ""):
        return []
    # Split on commas, semicolons, or whitespace clusters
    parts = re.split(r"[,;\s]+", raw.strip())
    plos: list[str] = []
    for p in parts:
        p = p.strip().strip(".")
        if p and re.match(r"^[A-Za-z]\.?\d*$", p):
            # Normalize: remove dots between letter and number
            p = re.sub(r"\.(?=\d)", "", p).upper()
            plos.append(p)
    return plos
