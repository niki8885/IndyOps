"""
Pure helpers for the mining journal / profit report.

Date-range math for the day / month / quarter / year period selector, the period
label keys used to anchor persisted tax write-offs, and the tax deduction. No I/O
— the router loads the ledger + prices and feeds plain values in, so this stays
unit-testable. See [[indyops-service-layering]].
"""
from __future__ import annotations

import datetime

PERIODS = ("day", "month", "quarter", "year")


def _add_months(d: datetime.date, months: int) -> datetime.date:
    """First-of-month ``d`` shifted by ``months`` (keeps day=1)."""
    m = d.month - 1 + months
    return datetime.date(d.year + m // 12, m % 12 + 1, 1)


def period_bounds(period_type: str, anchor: datetime.date, offset: int = 0) -> tuple[datetime.date, datetime.date]:
    """
    Inclusive [start, end] dates for the period containing ``anchor``, shifted by
    ``offset`` whole periods (0 = current, -1 = previous, …).

    - day:     a single date
    - month:   1st … last of the month
    - quarter: 1st of the quarter … last of its 3rd month
    - year:    Jan 1 … Dec 31
    """
    if period_type == "day":
        d = anchor + datetime.timedelta(days=offset)
        return d, d
    if period_type == "month":
        first = _add_months(anchor.replace(day=1), offset)
        return first, _add_months(first, 1) - datetime.timedelta(days=1)
    if period_type == "quarter":
        q_first_month = ((anchor.month - 1) // 3) * 3 + 1
        first = _add_months(datetime.date(anchor.year, q_first_month, 1), offset * 3)
        return first, _add_months(first, 3) - datetime.timedelta(days=1)
    if period_type == "year":
        first = datetime.date(anchor.year + offset, 1, 1)
        return first, datetime.date(first.year, 12, 31)
    raise ValueError(f"unknown period_type: {period_type}")


def period_key(period_type: str, start: datetime.date) -> str:
    """Stable label for a period's start date — anchors write-off records + the UI title.

    day → ``2026-06-18``, month → ``2026-06``, quarter → ``2026-Q2``, year → ``2026``."""
    if period_type == "day":
        return start.isoformat()
    if period_type == "month":
        return f"{start.year}-{start.month:02d}"
    if period_type == "quarter":
        return f"{start.year}-Q{(start.month - 1) // 3 + 1}"
    if period_type == "year":
        return str(start.year)
    raise ValueError(f"unknown period_type: {period_type}")


def apply_tax(gross: float, tax_pct: float) -> tuple[float, float]:
    """Return ``(tax_amount, net)`` for a gross value and a tax percentage."""
    tax = max(0.0, gross) * max(0.0, tax_pct) / 100.0
    return round(tax, 2), round(gross - tax, 2)
