"""Course code normalization utilities.

Converts various raw course code formats into a canonical form:
``"DEPT NNN"`` — uppercase department code, space, numeric course number.

Examples:
    >>> normalize_course_code("BUS200")
    'BUS 200'
    >>> normalize_course_code("Math 101")
    'MATH 101'
    >>> normalize_course_code("MATH208")
    'MATH 208'
    >>> normalize_course_code("ICS 104")
    'ICS 104'
    >>> normalize_course_code("  math  101  ")
    'MATH 101'
"""

from __future__ import annotations

import re

# Matches: optional whitespace, alpha dept code, optional separator, digits,
# optional trailing alpha suffix (e.g. "101L").
_CODE_RE = re.compile(
    r"^\s*([A-Za-z]+)\s*[-–—]?\s*(\d{2,4}[A-Za-z]?)\s*$"
)


def normalize_course_code(raw: str) -> str:
    """Normalize a raw course code string to canonical form.

    Rules:
        - Strip leading/trailing whitespace.
        - Uppercase the department prefix.
        - Ensure exactly one space between prefix and number.
        - Handle codes with no space (``MATH208``), extra spaces,
          hyphens/dashes as separators, and mixed case.

    Args:
        raw: The raw course code string.

    Returns:
        Normalized code like ``"MATH 101"``, or the original string
        (stripped and uppercased) if it doesn't match the expected pattern.
    """
    raw = raw.strip()
    if not raw:
        return raw

    m = _CODE_RE.match(raw)
    if m:
        dept = m.group(1).upper()
        number = m.group(2).upper()
        return f"{dept} {number}"

    # Fallback: just clean up whitespace and uppercase
    return re.sub(r"\s+", " ", raw).upper().strip()


def extract_course_code_from_filename(filename: str) -> str | None:
    """Attempt to extract a course code from a filename.

    Handles patterns like:
        - ``"BUS 200 Course Specifications.pdf"``
        - ``"CS -Math-101-2024.docx"``
        - ``"CS-MATH325-2024.docx"``
        - ``"CRF2. COURSE SPECIFICATIONS AS 201 T251 1.docx"``
        - ``"DATA 201 Course Specifications.docx"``

    Returns:
        Normalized course code if found, ``None`` otherwise.
    """
    # Strip extension
    name = re.sub(r"\.(pdf|docx)$", "", filename, flags=re.IGNORECASE)

    # Pattern 1: "CS -Math-101-2024" or "CS-MATH325-2024"
    # The "CS" prefix is an artifact; the real code follows it
    m = re.match(
        r"^CS\s*[-–]?\s*([A-Za-z]+)\s*[-–]?\s*(\d{2,4})\s*[-–]",
        name,
        re.IGNORECASE,
    )
    if m:
        return normalize_course_code(f"{m.group(1)} {m.group(2)}")

    # Pattern 2: "CRF2. COURSE SPECIFICATIONS AS 201 T251"
    m = re.search(
        r"SPECIFICATIONS?\s+([A-Za-z]+)\s+(\d{2,4})",
        name,
        re.IGNORECASE,
    )
    if m:
        return normalize_course_code(f"{m.group(1)} {m.group(2)}")

    # Pattern 3: "DEPT NNN Course Specifications" or "DEPT NNN ..."
    m = re.match(
        r"^([A-Za-z]+)\s+(\d{2,4})\b",
        name,
    )
    if m:
        return normalize_course_code(f"{m.group(1)} {m.group(2)}")

    return None
