"""Statistics over unique proved completed calendar days; no acquisition or I/O."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from healthcheck.garmin.completed_steps_read import CompletedStepsHistory, CompletedStepsWindow


@dataclass(frozen=True)
class StepsStatistics:
    calendar_day_count: int
    eligible_day_count: int
    unobserved_day_count: int
    state_counts: dict[str, int]
    first_eligible_date: date | None
    last_eligible_date: date | None
    total: int | None
    mean: Decimal | None
    over_10000_day_count: int | None
    over_20000_day_count: int | None
    record_value: int | None
    record_dates: tuple[date, ...]
    longest_10000_streak: int | None
    longest_streak_ranges: tuple[tuple[date, date], ...]


def summarize_completed_days(
    history: CompletedStepsHistory | CompletedStepsWindow,
) -> StepsStatistics:
    """Never turn an unknown day into zero or count acquisitions as days."""
    if not history.search_complete or history.start_date is None:
        raise ValueError("complete bounded daily evidence required")
    cells = sorted(history.cells, key=lambda cell: cell.calendar_date)
    if len({cell.calendar_date for cell in cells}) != len(cells):
        raise ValueError("duplicate calendar days")
    for cell in cells:
        if (
            cell.source_id != history.source_id
            or not cell.search_complete
            or not history.start_date <= cell.calendar_date <= history.end_date
        ):
            raise ValueError("daily grain or identity unproven")
        if cell.state == "value" and (type(cell.value) is not int or cell.value < 0):
            raise ValueError("invalid eligible count")
    eligible = [cell for cell in cells if cell.state == "value"]
    count = len(eligible)
    total = sum(cell.value for cell in eligible) if count else None
    record = max((cell.value for cell in eligible), default=None)
    mean = None
    if count:
        # Preserve accepted arbitrary nonnegative integers; never overflow float.
        # The exact ratio is also retained by total / eligible_day_count.
        with localcontext() as context:
            context.prec = max(28, total.bit_length() * 30103 // 100000 + 16)
            context.rounding = ROUND_HALF_EVEN
            mean = Decimal(total) / count
    longest = current = 0
    previous = run_start = None
    ranges = []
    for cell in cells:
        if cell.state != "value" or cell.value < 10000:
            previous = run_start = None
            current = 0
            continue
        if previous is None or (cell.calendar_date - previous).days != 1:
            run_start, current = cell.calendar_date, 1
        else:
            current += 1
        previous = cell.calendar_date
        if current > longest:
            longest, ranges = current, [(run_start, previous)]
        elif current == longest:
            ranges.append((run_start, previous))
    span = (history.end_date - history.start_date).days + 1
    return StepsStatistics(
        calendar_day_count=span,
        eligible_day_count=count,
        unobserved_day_count=span - len(cells),
        state_counts=dict(Counter(cell.state for cell in cells)),
        first_eligible_date=eligible[0].calendar_date if count else None,
        last_eligible_date=eligible[-1].calendar_date if count else None,
        total=total,
        mean=mean,
        over_10000_day_count=sum(cell.value > 10000 for cell in eligible) if count else None,
        over_20000_day_count=sum(cell.value > 20000 for cell in eligible) if count else None,
        record_value=record,
        record_dates=tuple(cell.calendar_date for cell in eligible if cell.value == record),
        longest_10000_streak=longest if count else None,
        longest_streak_ranges=tuple(ranges),
    )
