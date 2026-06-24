"""Tiny in-process per-(user, action) cooldown.

Gates the manually-triggered, ESI-hitting endpoints (order resync, competitive
price-check) so a user can't spam them. The API runs as a single process here, so a
module-level dict is sufficient; it is intentionally not shared across replicas.

Pure-ish: holds in-memory state but no ORM / web / I/O.
"""
import time

_last: dict = {}


class CooldownError(Exception):
    """Raised when an action is invoked again before its cooldown elapsed."""

    def __init__(self, retry_after: int):
        self.retry_after = retry_after
        super().__init__(f"rate limited; retry in {retry_after}s")


def check(user_id: int, action: str, cooldown_s: int) -> None:
    """Allow ``action`` for ``user_id`` at most once per ``cooldown_s`` seconds.

    Records the call time on success; raises :class:`CooldownError` (with the whole
    seconds left) if called again too soon."""
    key = (user_id, action)
    now = time.monotonic()
    prev = _last.get(key)
    if prev is not None:
        elapsed = now - prev
        if elapsed < cooldown_s:
            raise CooldownError(int(cooldown_s - elapsed) + 1)
    _last[key] = now
