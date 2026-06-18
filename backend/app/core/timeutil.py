"""Time helpers.

The app stores **naive** UTC datetimes everywhere (the ``DateTime`` columns are
tz-naive and code compares them against naive DB values). ``datetime.utcnow()`` is
deprecated in Python 3.12+, and its drop-in successor ``datetime.now(tz=utc)``
returns a tz-*aware* value that can't be compared with the naive ones. ``utcnow``
below is the non-deprecated, naive-UTC equivalent — use it instead of
``datetime.datetime.utcnow()``.
"""
import datetime


def utcnow() -> datetime.datetime:
    """Current UTC time as a naive ``datetime`` (no tzinfo)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
