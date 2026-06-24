"""Bank currency — ISK ↔ Aureus / Penny conversion and ledger balances.

The in-app currency mirrors EVE ISK with two denominations:

* **Aureus** (gold)  = 1 ISK
* **Penny**  (copper) = 0.01 ISK   →   100 Penny = 1 Aureus

EVE ISK carries exactly two decimals, so an integer-Penny representation is exact:
``1,000.11 ISK`` = ``100,011 Penny`` = ``1000 Aureus + 11 Penny``. Balances are
stored and summed in whole Penny to avoid float drift; coins are derived on read.

Pure module — no ORM / web / I/O.
"""
from typing import Iterable

PENNY_PER_AUREUS = 100


def isk_to_penny(isk: float) -> int:
    """Whole Penny in an ISK amount (rounded to the cent EVE uses)."""
    return int(round((isk or 0.0) * PENNY_PER_AUREUS))


def penny_to_coins(total_penny: int) -> dict:
    """Split an integer Penny total into ``{total_penny, aureus, penny}``.

    The sign is carried on both coin parts so a negative balance reads naturally
    (``-1 Aureus 50 Penny`` rather than ``-1 Aureus +50 Penny``)."""
    total_penny = int(total_penny or 0)
    sign = -1 if total_penny < 0 else 1
    mag = abs(total_penny)
    return {
        "total_penny": total_penny,
        "aureus": sign * (mag // PENNY_PER_AUREUS),
        "penny": sign * (mag % PENNY_PER_AUREUS),
    }


def isk_to_coins(isk: float) -> dict:
    """Convert an ISK amount straight to ``{total_penny, aureus, penny}``."""
    return penny_to_coins(isk_to_penny(isk))


def balance(amount_pennies: Iterable[int]) -> dict:
    """Aggregate an iterable of integer-Penny credits into a coin balance."""
    return penny_to_coins(sum(int(p or 0) for p in amount_pennies))
