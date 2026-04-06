"""KFUPM academic term calculation.

Determines the current KFUPM term code based on the date.

Term code format: 3 digits = last 2 digits of academic start year + semester number
Semesters: 1=Fall (Aug 15+), 2=Spring (Jan 15+), 3=Summer (Jun 15+)

Academic year starts in Fall. So Fall 2025 -> startYear=2025, code=251
Spring 2026 (of the 2025-2026 year) -> startYear=2025, code=252
Summer 2026 (of the 2025-2026 year) -> startYear=2025, code=253
"""

from __future__ import annotations

from datetime import date


# Month constants (1-indexed, matching Python's date.month)
_FALL_START_MONTH = 8       # August
_SUMMER_START_MONTH = 6     # June
_SPRING_START_MONTH = 1     # January
_TERM_START_DAY = 15


def get_current_term(today: date | None = None) -> str:
    """Calculate the current KFUPM term code.

    Args:
        today: Date to compute the term for.  Defaults to today's date.

    Returns:
        Term code string like ``"T262"`` (prefixed with 'T').
    """
    if today is None:
        today = date.today()

    year = today.year
    month = today.month
    day = today.day

    if month > _FALL_START_MONTH or (month == _FALL_START_MONTH and day >= _TERM_START_DAY):
        # Fall semester of current year
        start_year = year
        semester = 1
    elif month > _SUMMER_START_MONTH or (month == _SUMMER_START_MONTH and day >= _TERM_START_DAY):
        # Summer semester -- academic year started previous fall
        start_year = year - 1
        semester = 3
    elif month > _SPRING_START_MONTH or (month == _SPRING_START_MONTH and day >= _TERM_START_DAY):
        # Spring semester -- academic year started previous fall
        start_year = year - 1
        semester = 2
    else:
        # Before Jan 15 -- still in Fall of previous year
        start_year = year - 1
        semester = 1

    code = f"{start_year % 100}{semester}"
    return f"T{code}"
