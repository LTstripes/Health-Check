"""Shared Overview comparison and presentation coverage policy."""

from fractions import Fraction

OVERVIEW_COVERAGE_THRESHOLD = Fraction(2, 3)


def overview_low_coverage(count: int | None, days: int) -> bool:
    """UI dimming and delta eligibility use the same exact inclusive boundary."""
    return count is None or days <= 0 or Fraction(count, days) < OVERVIEW_COVERAGE_THRESHOLD
