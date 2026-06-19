"""
Pure evaluation for Agenda price/volume alerts — no I/O.

The worker loads the current (and, for percentage conditions, the window-ago)
value of an alert's metric and feeds plain numbers in here; this module decides
whether the condition is met and labels the direction. Side-effect free so it
stays unit-testable. See [[indyops-service-layering]].
"""
from __future__ import annotations

CONDITIONS = ("above", "below", "pct_up", "pct_down")
METRICS = ("price", "volume")


def pct_change(past, current):
    """Percent change from ``past`` to ``current`` (None if not computable)."""
    if past is None or current is None or past == 0:
        return None
    return (current - past) / abs(past) * 100.0


def is_triggered(condition: str, current, past, threshold) -> bool:
    """Does the alert fire? ``above``/``below`` are absolute crossings of
    ``threshold``; ``pct_up``/``pct_down`` need a move of at least ``threshold``
    percent vs the window-ago value. Missing data never fires."""
    if current is None:
        return False
    if condition == "above":
        return current >= threshold
    if condition == "below":
        return current <= threshold
    chg = pct_change(past, current)
    if chg is None:
        return False
    if condition == "pct_up":
        return chg >= abs(threshold)
    if condition == "pct_down":
        return chg <= -abs(threshold)
    return False


def severity(condition: str) -> str:
    """Feed colour: up (green) / down (red) / info."""
    if condition in ("above", "pct_up"):
        return "up"
    if condition in ("below", "pct_down"):
        return "down"
    return "info"
