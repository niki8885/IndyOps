"""Pure blueprint-availability logic for the production chain.

No ORM / web / SDE imports — the router assembles ``OwnedBP`` / ``MakeNode`` from the
manual ``blueprints`` table and ESI-synced ``esi_blueprints`` (merged, per-user) and
feeds them here. We decide which owned print to apply per node, how many runs are
covered, and what's still missing + how to acquire it.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OwnedBP:
    """A blueprint the user owns, normalised across the manual table and ESI sync."""
    key: str                    # "esi:<item_id>" | "man:<id>" — stable selection handle
    product_type_id: int
    blueprint_type_id: int
    name: str
    is_bpo: bool
    me: int
    te: int
    runs: Optional[int]         # per-copy runs for a BPC; None/ignored for a BPO
    quantity: int               # stack count (manual); ESI prints are individual rows
    cost: Optional[float]       # per-blueprint acquisition cost (manual only)
    source: str                 # "esi" | "manual"
    owner: str                  # character name, or "Manual"
    location: Optional[str] = None


@dataclass(frozen=True)
class MakeNode:
    """A node the plan decided to *make* — needs a blueprint."""
    product_type_id: int
    product_name: str
    blueprint_type_id: int
    blueprint_name: str
    activity: int               # 1 manufacturing / 11 reaction
    runs_needed: int
    me: int                     # ME applied in the calc
    te: int                     # TE applied in the calc


def is_bpo(runs, quantity) -> bool:
    """ESI marks an original with ``runs == -1`` (and ``quantity == -1``)."""
    return (runs is not None and runs < 0) or quantity == -1


def owned_runs(bp: OwnedBP) -> Optional[int]:
    """Total runs this entry provides; ``None`` = unlimited (BPO)."""
    if bp.is_bpo:
        return None
    return (bp.runs or 0) * max(bp.quantity or 1, 1)


def _rank(bp: OwnedBP):
    # prefer BPO, then higher ME, then higher TE, then more runs
    return (1 if bp.is_bpo else 0, bp.me or 0, bp.te or 0, owned_runs(bp) or 0)


def pick_best(cands: list[OwnedBP]) -> Optional[OwnedBP]:
    """The best print to apply for a node: BPO > best ME > best TE > most runs."""
    return max(cands, key=_rank) if cands else None


def total_owned_runs(cands: list[OwnedBP]) -> Optional[int]:
    """Runs available across all owned prints for a product; ``None`` if any BPO."""
    if any(c.is_bpo for c in cands):
        return None
    return sum((owned_runs(c) or 0) for c in cands)


def _acquisition(available: str, node: MakeNode, best: Optional[OwnedBP],
                 runs_owned: Optional[int], shortfall: int) -> str:
    if available == "bpo":
        return f"Use owned BPO ({best.owner})"
    if available == "bpc_ok":
        return f"Use owned BPC — {runs_owned} run(s) ({best.owner})"
    if available == "bpc_short":
        return f"Owned BPC short by {shortfall} run(s) — copy/buy more, or build a BPO"
    # missing
    if node.activity == 11:
        return "Acquire the reaction formula (BPO/BPC)"
    return "Acquire a BPO (or buy a BPC) for this item"


def build_report(nodes: list[MakeNode], owned_by_product: dict[int, list[OwnedBP]]) -> list[dict]:
    """Per made node: required runs / ME-TE, what's owned, what's missing, how to get it.

    ``available`` ∈ {bpo, bpc_ok, bpc_short, missing}. Legacy keys (``me``/``te``/
    ``runs_needed``/``runs_owned``/``shortfall``) are kept for the existing UI.
    """
    report: list[dict] = []
    for n in nodes:
        cands = owned_by_product.get(n.product_type_id, [])
        best = pick_best(cands)
        has_bpo = any(c.is_bpo for c in cands)
        runs_owned = total_owned_runs(cands)        # None = unlimited (BPO present)

        if has_bpo:
            available, shortfall = "bpo", 0
        elif cands:                                 # only BPCs
            shortfall = max(0, n.runs_needed - (runs_owned or 0))
            available = "bpc_ok" if shortfall == 0 else "bpc_short"
        else:
            available, shortfall = "missing", n.runs_needed

        report.append({
            # legacy fields (current UI):
            "type_id": n.product_type_id,
            "me": (best.me if best else n.me),
            "te": (best.te if best else n.te),
            "runs_needed": n.runs_needed,
            "runs_owned": runs_owned,
            "shortfall": shortfall,
            # new fields:
            "product_name": n.product_name,
            "blueprint_type_id": n.blueprint_type_id,
            "blueprint_name": n.blueprint_name,
            "activity": n.activity,
            "available": available,
            "is_owned": bool(cands),
            "owned_is_bpo": has_bpo,
            "owner": best.owner if best else None,
            "location": best.location if best else None,
            "acquisition": _acquisition(available, n, best, runs_owned, shortfall),
        })

    order = {"missing": 0, "bpc_short": 1, "bpc_ok": 2, "bpo": 3}
    report.sort(key=lambda r: (order.get(r["available"], 9), -r["runs_needed"]))
    return report


def summarize(report: list[dict]) -> dict:
    """Headline counts for the chain Blueprints section."""
    return {
        "nodes": len(report),
        "required_runs": sum(r["runs_needed"] for r in report),
        "owned_bpo": sum(1 for r in report if r["available"] == "bpo"),
        "owned_bpc": sum(1 for r in report if r["available"] in ("bpc_ok", "bpc_short")),
        "short": sum(1 for r in report if r["available"] == "bpc_short"),
        "missing": sum(1 for r in report if r["available"] == "missing"),
    }
