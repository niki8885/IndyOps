"""
Parse a pasted blueprint collection (the Blueprint Collection Analyzer's input) into a
grouped list. Players paste their blueprint list — one name per line, usually with
repeats (EVE has no "x20" in the inventory copy, it just lists the stack), occasionally
tab-separated with a quantity column or an explicit "xN" suffix.

Pure (stdlib only) so it is unit-testable without the SDE; name → blueprint → product
resolution and costing happen in the router. See [[indyops-service-layering]].
"""
from __future__ import annotations

import re

_QTY_SUFFIX = re.compile(r"\s*[xX]\s*(\d+)\s*$")    # "Miner II Blueprint x20"


def parse_blueprint_list(text: str) -> list[dict]:
    """Group a pasted blueprint list into ``[{name, count}]`` (first-seen order).

    Each non-blank line contributes one blueprint name and a count: a trailing ``xN`` or
    a tab-separated integer quantity column sets the count, else the line counts as 1, and
    identical names are summed (so 20 repeated lines → ``count`` 20)."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t")
        name = parts[0].strip()
        qty = 1
        m = _QTY_SUFFIX.search(name)
        if m:
            qty = int(m.group(1))
            name = name[:m.start()].strip()
        elif len(parts) > 1 and parts[1].strip().replace(",", "").isdigit():
            qty = int(parts[1].strip().replace(",", ""))
        if not name:
            continue
        if name not in counts:
            counts[name] = 0
            order.append(name)
        counts[name] += qty
    return [{"name": n, "count": counts[n]} for n in order]
