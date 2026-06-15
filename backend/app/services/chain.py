from __future__ import annotations
import math
from collections import defaultdict
from dataclasses import dataclass, replace
from fractions import Fraction
from typing import Optional

from app.services.facility_bonus import EC_COST_ROLE, EC_MATERIAL_ROLE, RigBonus, effective_bonuses

MANUFACTURING = 1
REACTION = 11

# The core runs on exact rationals: every contract float is re-seeded as an exact
# *decimal* Fraction (Fraction(str(x))) so there is no rounding/accumulation error
# down a deep build tree, and results match the Haskell port (haskell/chain-engine)
# exactly — strict equality, not a float epsilon. Money fields below are therefore
# Fraction at runtime (the float annotations are kept for documentation).


# contract: request

@dataclass(frozen=True)
class RecipeLocation:
    """One place a recipe can run, with its effective bonuses and job-cost rates.

    ``me_mult``/``te_mult`` are *already-combined* fractions (blueprint ME × rig ×
    structure role), e.g. 0.958 means 4.2% materials saved. EIV is supplied per
    output unit; the job-cost rate mirrors run_calculation / the MMBANK pipeline:
    ``EIV · (sci·(1−discount) + tax + scc)``.
    """
    place_id: int
    place_name: str
    slot_kind: str = "manufacturing"
    me_mult: float = 1.0
    te_mult: float = 1.0
    sci: float = 0.0
    tax: float = 0.0
    scc: float = 0.04
    struct_discount: float = 0.0
    eiv_unit: float = 0.0
    bpc_unit: float = 0.0

    def install_per_unit(self) -> float:
        return self.eiv_unit * (self.sci * (1 - self.struct_discount) + self.tax + self.scc)


@dataclass(frozen=True)
class Recipe:
    """One way to produce a node's product (a blueprint or a reaction formula)."""
    activity: int
    blueprint_type_id: int
    qty_per_run: int
    base_time: int
    inputs: tuple[tuple[int, int], ...]
    locations: tuple[RecipeLocation, ...]
    max_runs: Optional[int] = None


@dataclass(frozen=True)
class Node:
    type_id: int
    name: str
    buy_price: Optional[float] = None
    recipes: tuple[Recipe, ...] = ()


@dataclass
class ChainRequest:
    target_type_id: int
    target_qty: int
    nodes: dict[int, Node]


# contract: response

@dataclass
class NodeDecision:
    type_id: int
    name: str
    decision: str
    unit_cost: Optional[float]
    unit_buy: Optional[float] = None
    unit_make: Optional[float] = None
    recipe_index: Optional[int] = None
    place_id: Optional[int] = None
    saved_per_unit: float = 0.0


@dataclass
class JobInput:
    type_id: int
    qty: int
    unit_cost: float
    is_make: bool


@dataclass
class PlannedJob:
    type_id: int
    name: str
    activity: int
    place_id: int
    place_name: str
    slot_kind: str
    runs: int
    qty_out: int
    time_s: int
    install_cost: float
    bpc_cost: float
    leaf_material_cost: float
    inputs: list[JobInput]
    buy_fallback_unit: Optional[float]
    bounceable: bool

    @property
    def make_cost(self):
        """Marginal cost of running this job in-house (install + bpc + its leaf inputs)."""
        return self.install_cost + self.bpc_cost + self.leaf_material_cost

    @property
    def buy_fallback_total(self):
        if self.buy_fallback_unit is None:
            return None
        return self.buy_fallback_unit * self.qty_out


@dataclass
class ShoppingLine:
    type_id: int
    name: str
    qty: int
    unit: float
    total: float


@dataclass
class ChainPlan:
    target_type_id: int
    target_qty: int
    unit_cost: Optional[float]
    total_cost: float
    decisions: dict[int, NodeDecision]
    jobs: list[PlannedJob]
    shopping_list: list[ShoppingLine]


# solver

def solve_chain(req: ChainRequest) -> ChainPlan:
    req = _normalize(req)
    decisions = _decide(req)
    jobs, shopping, total = _plan(req, decisions)
    root = decisions.get(req.target_type_id)
    unit = root.unit_cost if root else None
    return ChainPlan(
        target_type_id=req.target_type_id,
        target_qty=req.target_qty,
        unit_cost=unit,
        total_cost=total,
        decisions=decisions,
        jobs=jobs,
        shopping_list=shopping,
    )


def _F(x):
    """float → exact *decimal* Fraction (matches the Haskell decimal-JSON parse)."""
    return Fraction(str(x)) if x is not None else None


def _normalize(req: ChainRequest) -> ChainRequest:
    """Re-seed every contract float as an exact decimal Fraction. Returns a new
    request; the original (float) is left untouched for ``to_request_dict``."""
    nodes: dict[int, Node] = {}
    for tid, n in req.nodes.items():
        recipes = tuple(
            replace(r, locations=tuple(
                replace(l, me_mult=_F(l.me_mult), te_mult=_F(l.te_mult),
                        sci=_F(l.sci), tax=_F(l.tax), scc=_F(l.scc),
                        struct_discount=_F(l.struct_discount),
                        eiv_unit=_F(l.eiv_unit), bpc_unit=_F(l.bpc_unit))
                for l in r.locations))
            for r in n.recipes
        )
        nodes[tid] = replace(n, buy_price=_F(n.buy_price), recipes=recipes)
    return ChainRequest(req.target_type_id, req.target_qty, nodes)


def _adj_qty(base: int, runs: int, me_mult: Fraction) -> int:
    """Material qty after ME — exact per-job ceil, always ≥ runs."""
    return max(runs, math.ceil(base * runs * me_mult))


def _adj_time(base: int, runs: int, te_mult: Fraction) -> int:
    return math.ceil(base * runs * te_mult)


# contract assembly: SDE tree + prices → request

@dataclass(frozen=True)
class LocationParams:
    """One production location (facility) the chain may build at.

    ``me_mult``/``te_mult`` are the *manual* multipliers (blueprint ME/TE the user
    types in, plus implants/skills) — facility **rig** ME/TE/cost is layered on top
    per node via ``rigs``/``is_ec`` (rigs only apply to the products they cover, so
    each node sees a different effective bonus). ``struct_discount`` is the manual
    structure cost discount fraction. With several LocationParams the core picks the
    cheapest per node and carries its ``place_id`` into the plan.

    ``can_man``/``can_react`` gate which activities run here; they default True so
    the single-location/default path is unchanged. ``man_lines``/``react_lines``
    are kept for slot display.
    """
    place_id: int
    place_name: str = ""
    me_mult: float = 1.0
    te_mult: float = 1.0
    sci: float = 0.0
    tax: float = 0.0
    scc: float = 0.04
    struct_discount: float = 0.0
    man_lines: int = 0
    react_lines: int = 0
    rigs: tuple[RigBonus, ...] = ()
    band: str = "null"
    is_ec: bool = False
    can_man: bool = True
    can_react: bool = True


def _node_location(
        loc: LocationParams, is_reaction: bool,
        cat_id: Optional[int], group_name: Optional[str],
        eiv_unit: float, bpc_unit: float,
) -> RecipeLocation:
    """Resolve one facility's effective ME/TE/cost for one node.

    Rigs + EC role combine with the manual multipliers exactly like the single-job
    ``run_calculation``: ME/TE multiply ``(1−rig)(1−role)``; cost is a single
    percentage (max(manual, EC role) + rig cost) subtracted from the SCI portion.
    Reactions ignore ME. A facility with no rig context (default path) reduces to
    the old flat behaviour.
    """
    if loc.rigs or loc.is_ec:
        eff = effective_bonuses(list(loc.rigs), loc.band, cat_id, group_name)
        if is_reaction:
            me_mult = 1.0
        else:
            role = EC_MATERIAL_ROLE if loc.is_ec else 0.0
            me_mult = loc.me_mult * (1 - eff.me_pct / 100) * (1 - role / 100)
        te_mult = loc.te_mult * (1 - eff.te_pct / 100)
        base_cost_pct = max(loc.struct_discount * 100, EC_COST_ROLE if loc.is_ec else 0.0)
        struct_discount = min(0.9, (base_cost_pct + eff.cost_pct) / 100)
    else:
        me_mult = 1.0 if is_reaction else loc.me_mult
        te_mult = loc.te_mult
        struct_discount = loc.struct_discount
    return RecipeLocation(
        place_id=loc.place_id, place_name=loc.place_name,
        slot_kind="reaction" if is_reaction else "manufacturing",
        me_mult=me_mult, te_mult=te_mult, sci=loc.sci, tax=loc.tax, scc=loc.scc,
        struct_discount=struct_discount, eiv_unit=eiv_unit, bpc_unit=bpc_unit,
    )


def from_bom(
        target_type_id: int,
        target_qty: int,
        tree: dict[int, dict],
        buy_prices: dict[int, Optional[float]],
        adj_prices: dict[int, float],
        facilities,
        bpc_unit: Optional[dict[int, float]] = None,
) -> ChainRequest:
    """Turn a repositories.eve.bom_tree + market prices into a ``ChainRequest``.

    ``facilities`` is a list of :class:`LocationParams` (a single instance is also
    accepted). Each makeable node gets one ``RecipeLocation`` per *eligible* facility
    — manufacturing recipes only at places with ``can_man``, reactions only at places
    with ``can_react`` — each carrying that facility's per-node ME/TE/cost. The core
    then assigns every node to its cheapest facility.

    ``buy_prices`` is the market acquire cost per type (None = can't buy);
    ``adj_prices`` are ESI adjusted prices used for EIV (Σ base_qty·adj / qty_per_run).
    Pure — no I/O — so it is unit-testable on its own.
    """
    bpc_unit = bpc_unit or {}
    if isinstance(facilities, LocationParams):
        facilities = [facilities]
    nodes: dict[int, Node] = {}
    for tid, nd in tree.items():
        cat_id = nd.get("category_id")
        group_name = nd.get("group_name")
        recipes = []
        for rc in nd["recipes"]:
            activity = rc["activity"]
            is_reaction = activity == REACTION
            qpr = rc["qty_per_run"] or 1
            eiv_unit = sum(
                inp["qty"] * adj_prices.get(inp["type_id"], 0.0) for inp in rc["inputs"]
            ) / qpr
            locs = [
                _node_location(fac, is_reaction, cat_id, group_name, eiv_unit, bpc_unit.get(tid, 0.0))
                for fac in facilities
                if (fac.can_react if is_reaction else fac.can_man)
            ]
            if not locs:
                continue  # no eligible facility for this activity → not makeable here
            recipes.append(Recipe(
                activity=activity, blueprint_type_id=rc["blueprint_type_id"],
                qty_per_run=qpr, base_time=rc["base_time"],
                inputs=tuple((inp["type_id"], inp["qty"]) for inp in rc["inputs"]),
                locations=tuple(locs), max_runs=rc["max_runs"],
            ))
        nodes[tid] = Node(tid, nd["name"], buy_price=buy_prices.get(tid), recipes=tuple(recipes))
    return ChainRequest(target_type_id, target_qty, nodes)


def _decide(req: ChainRequest) -> dict[int, NodeDecision]:
    """Phase 1 — memoised min(buy, make) per node, with recipe + location choice."""
    nodes = req.nodes
    memo: dict[int, NodeDecision] = {}

    def cost(tid: int, stack: frozenset[int]) -> NodeDecision:
        if tid in memo:
            return memo[tid]
        node = nodes.get(tid)
        if node is None:
            dec = NodeDecision(tid, str(tid), "unobtainable", None)
            memo[tid] = dec
            return dec

        unit_buy = node.buy_price
        best = None

        if tid not in stack:
            inner = stack | {tid}
            for ri, recipe in enumerate(node.recipes):
                child_units: list[Optional[float]] = [
                    cost(mtid, inner).unit_cost for mtid, _ in recipe.inputs
                ]
                if any(u is None for u in child_units):
                    continue
                for loc in recipe.locations:
                    mat = sum(
                        u * mqty * loc.me_mult
                        for (_, mqty), u in zip(recipe.inputs, child_units)
                    ) / recipe.qty_per_run
                    make_unit = mat + loc.install_per_unit() + loc.bpc_unit
                    if best is None or make_unit < best[0]:
                        best = (make_unit, ri, loc.place_id)

        unit_make = best[0] if best else None
        choices = []
        if unit_buy is not None:
            choices.append(("buy", unit_buy))
        if unit_make is not None:
            choices.append(("make", unit_make))

        if not choices:
            dec = NodeDecision(tid, node.name, "unobtainable", None,
                               unit_buy=unit_buy, unit_make=unit_make)
        else:
            kind, unit = min(choices, key=lambda c: c[1])
            saved = (unit_buy - unit_make) if (unit_buy is not None and unit_make is not None) else Fraction(0)
            dec = NodeDecision(
                type_id=tid, name=node.name, decision=kind,
                unit_cost=unit,
                unit_buy=unit_buy,
                unit_make=unit_make,
                recipe_index=best[1] if (kind == "make" and best) else None,
                place_id=best[2] if (kind == "make" and best) else None,
                saved_per_unit=saved,
            )
        memo[tid] = dec
        return dec

    cost(req.target_type_id, frozenset())
    return memo


def _topo_make_order(req: ChainRequest, decisions: dict[int, NodeDecision]) -> list[int]:
    """Make-nodes, every node after all its make-parents (root first)."""
    make = {t for t, d in decisions.items() if d.decision == "make"}
    order: list[int] = []
    seen: set[int] = set()

    def visit(tid: int):
        if tid in seen or tid not in make:
            return
        seen.add(tid)
        order.append(tid)
        d = decisions[tid]
        recipe = req.nodes[tid].recipes[d.recipe_index]
        for mtid, _ in recipe.inputs:
            visit(mtid)

    visit(req.target_type_id)
    for t in make:
        visit(t)
    return order


def _plan(req: ChainRequest, decisions: dict[int, NodeDecision]):
    """Phase 2 — integer quantity propagation → jobs + shopping list + total."""
    order = _topo_make_order(req, decisions)
    demand: dict[int, int] = defaultdict(int)
    demand[req.target_type_id] = req.target_qty

    jobs: list[PlannedJob] = []
    shop_qty: dict[int, int] = defaultdict(int)

    for tid in order:
        node = req.nodes[tid]
        d = decisions[tid]
        recipe = node.recipes[d.recipe_index]
        loc = _location(recipe, d.place_id)
        need = demand[tid]
        if need <= 0:
            continue

        total_runs = -(-need // recipe.qty_per_run)  # exact integer ceil-div
        cap = recipe.max_runs or total_runs
        consumed: dict[int, int] = defaultdict(int)

        rem = total_runs
        while rem > 0:
            r = min(cap, rem)
            rem -= r
            qty_out = r * recipe.qty_per_run
            eiv_job = loc.eiv_unit * qty_out
            install = eiv_job * (loc.sci * (1 - loc.struct_discount) + loc.tax + loc.scc)
            bpc = loc.bpc_unit * qty_out
            time_s = _adj_time(recipe.base_time, r, loc.te_mult)

            job_inputs: list[JobInput] = []
            leaf_mat = Fraction(0)
            for mtid, mbase in recipe.inputs:
                cq = _adj_qty(mbase, r, loc.me_mult)
                consumed[mtid] += cq
                child = decisions[mtid]
                is_make = child.decision == "make"
                unit = child.unit_cost if child.unit_cost is not None else Fraction(0)
                if not is_make:
                    leaf_mat += cq * unit
                job_inputs.append(JobInput(mtid, cq, unit, is_make))

            bounceable = node.buy_price is not None and all(not ji.is_make for ji in job_inputs)
            jobs.append(PlannedJob(
                type_id=tid, name=node.name, activity=recipe.activity,
                place_id=loc.place_id, place_name=loc.place_name, slot_kind=loc.slot_kind,
                runs=r, qty_out=qty_out, time_s=time_s,
                install_cost=install, bpc_cost=bpc,
                leaf_material_cost=leaf_mat, inputs=job_inputs,
                buy_fallback_unit=node.buy_price, bounceable=bounceable,
            ))

        for mtid, cq in consumed.items():
            if decisions[mtid].decision == "make":
                demand[mtid] += cq
            else:
                shop_qty[mtid] += cq

    if decisions[req.target_type_id].decision != "make":
        shop_qty[req.target_type_id] += req.target_qty

    shopping: list[ShoppingLine] = []
    shop_total = Fraction(0)
    for mtid, qty in shop_qty.items():
        bp = req.nodes[mtid].buy_price
        unit = bp if bp is not None else Fraction(0)
        line_total = qty * unit
        shop_total += line_total
        shopping.append(ShoppingLine(mtid, req.nodes[mtid].name, qty, unit, line_total))

    jobs_conv = sum((j.install_cost + j.bpc_cost for j in jobs), Fraction(0))
    total = shop_total + jobs_conv
    shopping.sort(key=lambda s: s.total, reverse=True)
    return jobs, shopping, total


def _location(recipe: Recipe, place_id: Optional[int]) -> RecipeLocation:
    for loc in recipe.locations:
        if loc.place_id == place_id:
            return loc
    return recipe.locations[0]


# JSON seam

def to_request_dict(req: ChainRequest) -> dict:
    def loc_d(l: RecipeLocation) -> dict:
        return {
            "place_id": l.place_id, "place_name": l.place_name, "slot_kind": l.slot_kind,
            "me_mult": l.me_mult, "te_mult": l.te_mult, "sci": l.sci, "tax": l.tax,
            "scc": l.scc, "struct_discount": l.struct_discount,
            "eiv_unit": l.eiv_unit, "bpc_unit": l.bpc_unit,
        }

    def rec_d(r: Recipe) -> dict:
        return {
            "activity": r.activity, "blueprint_type_id": r.blueprint_type_id,
            "qty_per_run": r.qty_per_run, "base_time": r.base_time, "max_runs": r.max_runs,
            "inputs": [[t, q] for t, q in r.inputs],
            "locations": [loc_d(l) for l in r.locations],
        }

    def node_d(n: Node) -> dict:
        return {"type_id": n.type_id, "name": n.name, "buy_price": n.buy_price,
                "recipes": [rec_d(r) for r in n.recipes]}

    return {
        "target_type_id": req.target_type_id,
        "target_qty": req.target_qty,
        "nodes": {str(tid): node_d(n) for tid, n in req.nodes.items()},
    }


def _rat(x):
    """Parse an exact rational carried as ``[numerator, denominator]`` (or null)."""
    if x is None:
        return None
    if isinstance(x, (list, tuple)):
        return Fraction(int(x[0]), int(x[1]))
    return Fraction(x)


def plan_from_dict(d: dict) -> ChainPlan:
    decisions = {
        int(k): NodeDecision(
            type_id=v["type_id"], name=v["name"], decision=v["decision"],
            unit_cost=_rat(v["unit_cost"]), unit_buy=_rat(v["unit_buy"]), unit_make=_rat(v["unit_make"]),
            recipe_index=v["recipe_index"], place_id=v["place_id"],
            saved_per_unit=_rat(v["saved_per_unit"]),
        )
        for k, v in d["decisions"].items()
    }
    jobs = [
        PlannedJob(
            type_id=j["type_id"], name=j["name"], activity=j["activity"],
            place_id=j["place_id"], place_name=j["place_name"], slot_kind=j["slot_kind"],
            runs=j["runs"], qty_out=j["qty_out"], time_s=j["time_s"],
            install_cost=_rat(j["install_cost"]), bpc_cost=_rat(j["bpc_cost"]),
            leaf_material_cost=_rat(j["leaf_material_cost"]),
            inputs=[JobInput(i["type_id"], i["qty"], _rat(i["unit_cost"]), i["is_make"]) for i in j["inputs"]],
            buy_fallback_unit=_rat(j["buy_fallback_unit"]), bounceable=j["bounceable"],
        )
        for j in d["jobs"]
    ]
    shopping = [
        ShoppingLine(s["type_id"], s["name"], s["qty"], _rat(s["unit"]), _rat(s["total"]))
        for s in d["shopping_list"]
    ]
    return ChainPlan(
        target_type_id=d["target_type_id"], target_qty=d["target_qty"],
        unit_cost=_rat(d["unit_cost"]), total_cost=_rat(d["total_cost"]),
        decisions=decisions, jobs=jobs, shopping_list=shopping,
    )
