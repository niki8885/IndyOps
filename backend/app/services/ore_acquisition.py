"""
Pure ore-acquisition comparison maths
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── inputs ────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Need:
    """A mineral the user wants delivered to the target system."""
    type_id: int
    name: str
    qty: float = 0.0


@dataclass(frozen=True)
class Source:
    """A buy location."""
    key: str
    label: str
    cost_per_m3: float = 0.0


@dataclass(frozen=True)
class OreInfo:
    """An ore candidate and its perfect"""
    type_id: int
    name: str
    compressed: bool
    portion_size: int
    materials: tuple[dict, ...]


# outputs

@dataclass
class Cell:
    source: str
    price: Optional[float]
    delivered: Optional[float]  # price + volume · isk_per_m³
    flag: Optional[dict] = None


@dataclass
class ItemRow:
    """One row of the big comparison table (a mineral or an ore), priced per source."""
    type_id: int
    name: str
    kind: str
    compressed: bool
    volume: Optional[float]
    cells: list[Cell]
    best: Optional[Cell] = None


@dataclass
class OreEval:
    type_id: int
    name: str
    compressed: bool
    source: str
    cost_per_unit: Optional[float]
    refined_value_per_unit: float
    ratio: Optional[float]
    margin_pct: Optional[float]
    profitable: Optional[bool]
    outputs: list[dict] = field(default_factory=list)


@dataclass
class PathOption:
    kind: str
    source: str
    effective_cost: Optional[float]
    via_type_id: Optional[int] = None
    via_name: Optional[str] = None
    detail: Optional[str] = None


@dataclass
class MineralPlan:
    type_id: int
    name: str
    qty: float
    direct_best: Optional[PathOption] = None
    ore_best: Optional[PathOption] = None
    recommended: Optional[PathOption] = None
    options: list[PathOption] = field(default_factory=list)


@dataclass
class StrategyTotal:
    strategy: str
    label: str
    total_cost: Optional[float]
    covered: int
    missing: list[str] = field(default_factory=list)


@dataclass
class ComparisonResult:
    target: str
    basis: str
    effective_yield: float
    items: list[ItemRow]
    ore_evals: list[OreEval]
    minerals: list[MineralPlan]
    strategies: list[StrategyTotal]
    recommendation: dict


# gas inputs/outputs (compressed vs regular, no refining)

@dataclass(frozen=True)
class GasInfo:
    """A harvestable gas and its compressed variant."""
    reg_type_id: int
    reg_name: str
    reg_volume: Optional[float] = None
    comp_type_id: Optional[int] = None
    comp_name: Optional[str] = None
    comp_volume: Optional[float] = None
    units_per_compressed: Optional[float] = None


@dataclass
class GasPlan:
    reg_type_id: int
    name: str
    qty: float
    reg_volume: Optional[float]
    comp_volume: Optional[float]
    units_per_compressed: Optional[float]
    reg_best: Optional[PathOption] = None
    comp_best: Optional[PathOption] = None
    recommended: Optional[PathOption] = None
    cells: list[dict] = field(default_factory=list)


@dataclass
class GasComparisonResult:
    target: str
    basis: str
    decompression_loss: float
    gases: list[GasPlan]
    strategies: list[StrategyTotal]
    recommendation: dict


def _delivered(price: Optional[float], volume: Optional[float], cost_per_m3: float) -> Optional[float]:
    if price is None:
        return None
    return price + (volume or 0.0) * (cost_per_m3 or 0.0)


def _round(v: Optional[float], n: int = 2) -> Optional[float]:
    return None if v is None else round(v, n)


def compare(
        *,
        target: str,
        basis: str,
        needs: list[Need],
        sources: list[Source],
        item_prices: dict[str, dict[int, Optional[float]]],
        volumes: dict[int, Optional[float]],
        ores: list[OreInfo],
        effective_yield: float,
        mineral_ref_price: dict[int, Optional[float]],
        flags: Optional[dict] = None,
        allow_direct: bool = True,
) -> ComparisonResult:
    """Build the full ore/compressed/mineral comparison + per-mineral recommendation.

    ``allow_direct=False`` excludes buying the mineral directly (the "Minerals"
    checkbox is off) — only ore/compressed refining paths are considered.
    """
    flags = flags or {}
    need_ids = [n.type_id for n in needs]
    need_by_id = {n.type_id: n for n in needs}

    # ----- big price table: minerals first, then ores -------------------------
    def build_row(tid: int, name: str, kind: str, compressed: bool) -> ItemRow:
        vol = volumes.get(tid)
        cells: list[Cell] = []
        for s in sources:
            price = (item_prices.get(s.key) or {}).get(tid)
            cells.append(Cell(
                source=s.label,
                price=_round(price),
                delivered=_round(_delivered(price, vol, s.cost_per_m3)),
                flag=flags.get((s.key, tid)),
            ))
        priced = [c for c in cells if c.delivered is not None]
        best = min(priced, key=lambda c: c.delivered) if priced else None
        return ItemRow(type_id=tid, name=name, kind=kind, compressed=compressed,
                       volume=vol, cells=cells, best=best)

    items: list[ItemRow] = [build_row(n.type_id, n.name, "mineral", False) for n in needs]
    for o in ores:
        items.append(build_row(o.type_id, o.name, "ore", o.compressed))

    # ----- per-(ore, source) refine evaluation --------------------------------
    ore_evals: list[OreEval] = []
    # ore_best_cost[(mineral_id)] tracks the cheapest effective cost via any ore.
    ore_paths: dict[int, list[PathOption]] = {tid: [] for tid in need_ids}

    for o in ores:
        vol = volumes.get(o.type_id)
        ps = max(1, o.portion_size or 1)
        # output per single unit of ore, after effective yield
        out_per_unit: dict[int, float] = {}
        out_meta: dict[int, str] = {}
        for m in o.materials:
            q = (m.get("quantity") or 0) / ps * effective_yield
            if q > 0:
                out_per_unit[m["type_id"]] = q
                out_meta[m["type_id"]] = m.get("name", str(m["type_id"]))
        for s in sources:
            price = (item_prices.get(s.key) or {}).get(o.type_id)
            cost = _delivered(price, vol, s.cost_per_m3)
            refined_value = sum(
                q * (mineral_ref_price.get(mid) or 0.0) for mid, q in out_per_unit.items()
            )
            ratio = (refined_value / cost) if (cost and cost > 0) else None
            ore_evals.append(OreEval(
                type_id=o.type_id, name=o.name, compressed=o.compressed, source=s.label,
                cost_per_unit=_round(cost),
                refined_value_per_unit=_round(refined_value) or 0.0,
                ratio=_round(ratio, 4),
                margin_pct=_round((ratio - 1) * 100, 2) if ratio is not None else None,
                profitable=(ratio is not None and ratio > 1),
                outputs=[{"type_id": mid, "name": out_meta[mid], "qty_per_unit": round(q, 4)}
                         for mid, q in out_per_unit.items()],
            ))
            # effective cost of each *needed* mineral obtained via this ore/source
            if ratio and ratio > 0:
                for mid in out_per_unit:
                    if mid not in need_by_id:
                        continue
                    ref = mineral_ref_price.get(mid)
                    if not ref or ref <= 0:
                        continue
                    eff = ref / ratio
                    ore_paths[mid].append(PathOption(
                        kind="ore", source=s.label, effective_cost=_round(eff, 4),
                        via_type_id=o.type_id, via_name=o.name,
                        detail=f"{'compressed' if o.compressed else 'raw'} · refine margin "
                               f"{round((ratio - 1) * 100, 1)}%",
                    ))

    # ----- per-mineral plans --------------------------------------------------
    minerals: list[MineralPlan] = []
    for n in needs:
        direct: list[PathOption] = []
        vol = volumes.get(n.type_id)
        if allow_direct:
            for s in sources:
                price = (item_prices.get(s.key) or {}).get(n.type_id)
                d = _delivered(price, vol, s.cost_per_m3)
                if d is not None:
                    direct.append(PathOption(kind="mineral", source=s.label,
                                             effective_cost=_round(d, 4)))
        ore_opts = sorted(ore_paths.get(n.type_id, []),
                          key=lambda p: p.effective_cost)
        direct_best = min(direct, key=lambda p: p.effective_cost) if direct else None
        ore_best = ore_opts[0] if ore_opts else None
        cands = [p for p in (direct_best, ore_best) if p]
        recommended = min(cands, key=lambda p: p.effective_cost) if cands else None
        options = sorted(direct + ore_opts, key=lambda p: p.effective_cost)
        minerals.append(MineralPlan(
            type_id=n.type_id, name=n.name, qty=n.qty,
            direct_best=direct_best, ore_best=ore_best,
            recommended=recommended, options=options,
        ))

    # ----- strategy totals + recommendation -----------------------------------
    has_qty = any(n.qty and n.qty > 0 for n in needs)

    def strat(strategy: str, label: str, pick) -> StrategyTotal:
        total = 0.0
        covered = 0
        missing: list[str] = []
        for mp in minerals:
            opt = pick(mp)
            if opt and opt.effective_cost is not None:
                covered += 1
                if has_qty:
                    total += (mp.qty or 0.0) * opt.effective_cost
            else:
                missing.append(mp.name)
        return StrategyTotal(
            strategy=strategy, label=label,
            total_cost=_round(total) if has_qty else None,
            covered=covered, missing=missing,
        )

    strategies = [
        strat("buy_minerals", "Buy minerals", lambda mp: mp.direct_best),
        strat("buy_ore_refine", "Buy ore & refine", lambda mp: mp.ore_best),
        strat("optimal_mix", "Optimal mix", lambda mp: mp.recommended),
    ]

    # Recommend the cheapest fully-covered strategy; fall back to widest coverage.
    full = [s for s in strategies if s.covered == len(minerals) and minerals]
    if has_qty and full:
        best = min(full, key=lambda s: s.total_cost if s.total_cost is not None else float("inf"))
        reason = (f"{best.label} is cheapest for the full basket"
                  f" ({best.total_cost:,.2f} ISK delivered to {target}).")
    elif full:
        # per-unit mode: pick the strategy that wins the most minerals
        wins = {s.strategy: 0 for s in strategies}
        for mp in minerals:
            if mp.recommended:
                wins["optimal_mix"] += 1
                if mp.direct_best and mp.recommended is mp.direct_best:
                    wins["buy_minerals"] += 1
                if mp.ore_best and mp.recommended is mp.ore_best:
                    wins["buy_ore_refine"] += 1
        best = next(s for s in strategies if s.strategy == "optimal_mix")
        reason = "Per-mineral comparison — see the recommended path for each mineral."
    else:
        best = max(strategies, key=lambda s: s.covered) if strategies else None
        reason = "Incomplete price coverage — recommendation is partial."

    recommendation = {
        "strategy": best.strategy if best else None,
        "label": best.label if best else None,
        "total_cost": best.total_cost if best else None,
        "reason": reason,
    }

    return ComparisonResult(
        target=target, basis=basis, effective_yield=round(effective_yield, 6),
        items=items, ore_evals=ore_evals, minerals=minerals,
        strategies=strategies, recommendation=recommendation,
    )


def compare_gas(
        *,
        target: str,
        basis: str,
        needs: list[Need],  # type_id = the *regular* gas
        sources: list[Source],
        item_prices: dict[str, dict[int, Optional[float]]],  # regular + compressed type ids
        volumes: dict[int, Optional[float]],
        gas_infos: list[GasInfo],
        decompression_loss: float = 0.05,
        flags: Optional[dict] = None,
) -> GasComparisonResult:
    """Compare buying each gas **compressed vs regular**, transport + decompression
    loss included, and recommend the cheaper form per gas.

    Compressed gas ships compactly but must be decompressed, losing ``decompression_loss``
    (a fraction) of the ``units_per_compressed`` it would otherwise yield. The effective
    cost per usable (regular) unit is therefore::

        regular     : reg_price + reg_volume · isk_per_m³
        compressed  : (comp_price + comp_volume · isk_per_m³) / (units_per_compressed · (1 − loss))
    """
    flags = flags or {}
    loss = max(0.0, min(0.99, decompression_loss))
    info_by_reg = {g.reg_type_id: g for g in gas_infos}

    gases: list[GasPlan] = []
    for n in needs:
        g = info_by_reg.get(n.type_id)
        if not g:
            continue
        reg_vol = volumes.get(g.reg_type_id)
        comp_vol = volumes.get(g.comp_type_id) if g.comp_type_id else None
        usable = (g.units_per_compressed or 0.0) * (1 - loss)

        opts: list[PathOption] = []
        cells: list[dict] = []
        for s in sources:
            reg_price = (item_prices.get(s.key) or {}).get(g.reg_type_id)
            reg_eff = _delivered(reg_price, reg_vol, s.cost_per_m3)
            comp_price = (item_prices.get(s.key) or {}).get(g.comp_type_id) if g.comp_type_id else None
            comp_cost = _delivered(comp_price, comp_vol, s.cost_per_m3)
            comp_eff = (comp_cost / usable) if (comp_cost is not None and usable > 0) else None
            cells.append({
                "source": s.label,
                "reg_price": _round(reg_price), "reg_effective": _round(reg_eff, 4),
                "comp_price": _round(comp_price), "comp_effective": _round(comp_eff, 4),
                "flag": flags.get((s.key, g.reg_type_id)),
            })
            if reg_eff is not None:
                opts.append(PathOption(kind="regular", source=s.label,
                                       effective_cost=_round(reg_eff, 4)))
            if comp_eff is not None:
                opts.append(PathOption(
                    kind="compressed", source=s.label, effective_cost=_round(comp_eff, 4),
                    via_type_id=g.comp_type_id, via_name=g.comp_name,
                    detail=f"{round(g.units_per_compressed or 0, 2)}/unit − {loss * 100:.0f}% loss"))

        reg_opts = [o for o in opts if o.kind == "regular"]
        comp_opts = [o for o in opts if o.kind == "compressed"]
        reg_best = min(reg_opts, key=lambda o: o.effective_cost) if reg_opts else None
        comp_best = min(comp_opts, key=lambda o: o.effective_cost) if comp_opts else None
        cands = [o for o in (reg_best, comp_best) if o]
        recommended = min(cands, key=lambda o: o.effective_cost) if cands else None
        gases.append(GasPlan(
            reg_type_id=g.reg_type_id, name=g.reg_name, qty=n.qty,
            reg_volume=reg_vol, comp_volume=comp_vol,
            units_per_compressed=g.units_per_compressed,
            reg_best=reg_best, comp_best=comp_best, recommended=recommended, cells=cells,
        ))

    has_qty = any(g.qty and g.qty > 0 for g in gases)

    def strat(strategy: str, label: str, pick) -> StrategyTotal:
        total, covered, missing = 0.0, 0, []
        for gp in gases:
            opt = pick(gp)
            if opt and opt.effective_cost is not None:
                covered += 1
                if has_qty:
                    total += (gp.qty or 0.0) * opt.effective_cost
            else:
                missing.append(gp.name)
        return StrategyTotal(strategy=strategy, label=label,
                             total_cost=_round(total) if has_qty else None,
                             covered=covered, missing=missing)

    strategies = [
        strat("buy_regular", "Buy regular gas", lambda gp: gp.reg_best),
        strat("buy_compressed", "Buy compressed gas", lambda gp: gp.comp_best),
        strat("optimal_mix", "Optimal mix", lambda gp: gp.recommended),
    ]

    full = [s for s in strategies if s.covered == len(gases) and gases]
    if has_qty and full:
        best = min(full, key=lambda s: s.total_cost if s.total_cost is not None else float("inf"))
        reason = f"{best.label} is cheapest for the full list ({best.total_cost:,.2f} ISK to {target})."
    elif gases:
        best = next(s for s in strategies if s.strategy == "optimal_mix")
        reason = "Per-gas comparison — see the recommended form for each gas."
    else:
        best = None
        reason = "No gases with usable prices."

    recommendation = {
        "strategy": best.strategy if best else None,
        "label": best.label if best else None,
        "total_cost": best.total_cost if best else None,
        "reason": reason,
    }

    return GasComparisonResult(
        target=target, basis=basis, decompression_loss=loss,
        gases=gases, strategies=strategies, recommendation=recommendation,
    )
