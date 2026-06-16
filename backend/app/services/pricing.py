"""
Guard against scam / unrealistic market prices.

A buy (or sell) order can be placed far below an item's real value to bait
appraisals — using it makes materials look almost free and wrecks make-vs-buy and
profitability. We compare each acquire price against CCP's ESI **adjusted price** (a
stable rolling fair-value that can't be order-book manipulated) and drop anything
implausibly below it.

Pure (stdlib only) so it is shared by the basic calculator and the recursive chain.
See [[indyops-service-layering]].
"""
from __future__ import annotations
from typing import Optional

DEFAULT_RATIO = 0.3   # flag a price below 30% of the adjusted price


def _too_low(price: Optional[float], adjusted: Optional[float], ratio: float) -> bool:
    """A price is unrealistic when it's below ``ratio`` of the ESI adjusted price."""
    return (price is not None and adjusted is not None
            and adjusted > 0 and ratio > 0 and price < ratio * adjusted)


def resolve_price(
        buy_candidates: list[tuple[Optional[float], object]],
        sell_candidates: list[tuple[Optional[float], object]],
        adjusted: Optional[float],
        ratio: float = DEFAULT_RATIO,
        basis: str = "buy",
) -> tuple[Optional[float], object, Optional[dict]]:
    """Pick a realistic acquire price for one item, with graceful fallback.

    Candidates are ``(price, label)`` pairs from each market (the ``label`` — a
    region id or market name — is opaque here and just travels back as the source).
    Priority, honouring the user's rule "another region, else sell, else adjusted":

      1. cheapest **realistic** price on the chosen ``basis`` side across all regions,
      2. else cheapest realistic price on the **other** side (buy→sell / sell→buy),
      3. else the ESI ``adjusted`` price, 4. else ``None``.

    A ``flag`` is returned only when an *unrealistic* primary value was actually
    dropped, so the UI can show what was ignored.

    Returns ``(price, label, flag | None)`` where ``flag = {original, used, reason}``.
    """
    primary = buy_candidates if basis == "buy" else sell_candidates
    other = sell_candidates if basis == "buy" else buy_candidates
    other_name = "sell" if basis == "buy" else "buy"

    def realistic(cands):
        return [(p, lbl) for p, lbl in cands if p is not None and not _too_low(p, adjusted, ratio)]

    rp = realistic(primary)
    if rp:
        price, lbl = min(rp, key=lambda x: x[0])
        return price, lbl, None

    # Nothing realistic on the primary side — was there an (unrealistic) value to drop?
    present = [p for p, _ in primary if p is not None]
    dropped = min(present) if present else None

    def flag_for(used: float, via: str) -> Optional[dict]:
        if dropped is None:        # primary was just missing, not scammy → no flag
            return None
        return {"original": round(dropped, 2), "used": round(used, 2),
                "reason": f"{basis} {dropped:,.2f} below {ratio:.0%} of adjusted "
                          f"{(adjusted or 0):,.2f} — using {via} {used:,.2f}"}

    ro = realistic(other)
    if ro:
        price, lbl = min(ro, key=lambda x: x[0])
        return price, lbl, flag_for(price, other_name)
    if adjusted and adjusted > 0:
        return adjusted, "adjusted", flag_for(adjusted, "adjusted")
    return None, None, None


def flag_unrealistic(
        prices: dict[int, Optional[float]],
        adjusted: dict[int, float],
        ratio: float = DEFAULT_RATIO,
        skip: Optional[set[int]] = None,
) -> tuple[dict[int, Optional[float]], dict[int, dict]]:
    """Replace implausibly-low prices with the ESI adjusted price.

    A price is flagged when ``adjusted[tid] > 0 and price < ratio·adjusted[tid]``.
    Flagged entries fall back to the adjusted price (``None`` if there is no adjusted
    value). ``skip`` type_ids (manual overrides) are never touched. ``ratio <= 0``
    disables the check.

    Returns ``(clean_prices, flags)`` where ``flags[tid] = {original, used, reason}``
    (all JSON-safe) so callers can show the user exactly what was ignored.
    """
    skip = skip or set()
    clean = dict(prices)
    flags: dict[int, dict] = {}
    if ratio <= 0:
        return clean, flags
    for tid, price in prices.items():
        if tid in skip or price is None:
            continue
        ref = adjusted.get(tid) or 0.0
        if ref > 0 and price < ratio * ref:
            clean[tid] = ref
            flags[tid] = {
                "original": round(price, 2),
                "used": round(ref, 2),
                "reason": f"buy {price:,.2f} is below {ratio:.0%} of adjusted {ref:,.2f}",
            }
    return clean, flags
