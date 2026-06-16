import pytest
from app.adapters import chain_engine
from app.services.chain import ChainRequest, Node, Recipe, RecipeLocation, solve_chain

pytestmark = pytest.mark.skipif(not chain_engine.available(),
                                reason="chain-engine binary not built on this host")


def _loc(place_id=10, **kw):
    base = dict(slot_kind="manufacturing", me_mult=1.0, te_mult=1.0, sci=0.0, tax=0.0,
                scc=0.0, struct_discount=0.0, eiv_unit=0.0, bpc_unit=0.0)
    base.update(kw)
    return RecipeLocation(place_id, f"P{place_id}", **base)


def _recipe(inputs, qpr=1, base_time=600, max_runs=10, activity=1, loc=None):
    return Recipe(activity, 9000, qpr, base_time, tuple(inputs), (loc or _loc(),), max_runs)


def _req_two_tier():
    return ChainRequest(1, 3, {
        1: Node(1, "WIDGET", 100000.0, (_recipe([(2, 10), (3, 5)]),)),
        2: Node(2, "A", 1000.0, (_recipe([(3, 20)]),)),
        3: Node(3, "RAW", 10.0),
    })


def _req_install_me_scc():
    loc = _loc(me_mult=0.9, sci=0.05, tax=0.01, scc=0.04, struct_discount=0.0, eiv_unit=1000.0)
    return ChainRequest(1, 1, {
        1: Node(1, "GADGET", 5000.0, (_recipe([(3, 1000)], loc=loc),)),
        3: Node(3, "RAW", 1.0),
    })


def _req_reaction():
    react = _recipe([(30, 2)], qpr=10, base_time=3600, max_runs=100, activity=11,
                    loc=_loc(slot_kind="reaction"))
    return ChainRequest(20, 5, {
        20: Node(20, "T2", 9_000_000.0, (_recipe([(21, 4)]),)),
        21: Node(21, "COMP", 5000.0, (react,)),
        30: Node(30, "MOON", 100.0),
    })


def _req_shared_dag():
    return ChainRequest(1, 7, {
        1: Node(1, "ROOT", 1e12, (_recipe([(2, 1), (3, 1)]),)),
        2: Node(2, "A", 1e9, (_recipe([(4, 3)]),)),
        3: Node(3, "B", 1e9, (_recipe([(4, 7)]),)),
        4: Node(4, "RAW", 1.0),
    })


def _req_shared_made_dag():
    # Shared *made* intermediate S feeding two made parents — exercises the topo
    # make-order (reverse post-order). Both engines must sum S's demand identically.
    return ChainRequest(1, 3, {
        1: Node(1, "ROOT", 1e12, (_recipe([(2, 1), (3, 1)]),)),
        2: Node(2, "A", 1e9, (_recipe([(4, 1)]),)),
        3: Node(3, "B", 1e9, (_recipe([(4, 1)]),)),
        4: Node(4, "S", 1e9, (_recipe([(5, 5)]),)),
        5: Node(5, "RAW", 100.0),
    })


def _req_buy_beats_make():
    return ChainRequest(1, 4, {
        1: Node(1, "WIDGET", 100000.0, (_recipe([(2, 10)]),)),
        2: Node(2, "A", 1000.0, (_recipe([(3, 20)]),)),
        3: Node(3, "RAW", 500.0),
    })


def _req_messy_rationals():
    # qty_per_run 2 and 3 → non-terminating unit costs; decimal ME / prices / rates.
    # Any intermediate rounding would diverge here, so exact parity is a real proof.
    hull = _loc(me_mult=0.997, sci=0.0593, tax=0.0125, scc=0.04, struct_discount=0.021, eiv_unit=1234.56)
    react = _recipe([(30, 7)], qpr=3, base_time=1234, max_runs=50, activity=11,
                    loc=_loc(slot_kind="reaction", eiv_unit=987.65, sci=0.04, tax=0.011))
    return ChainRequest(40, 13, {
        40: Node(40, "T2 Thing", 8_888_888.88, (_recipe([(41, 5), (34, 333)], qpr=2, loc=hull),)),
        41: Node(41, "Interm", 4321.99, (react,)),
        30: Node(30, "Goo", 12.34),
        34: Node(34, "Trit", 5.67),
    })


def _req_multi_location():
    # One recipe offered at two structures; the cheaper (place 20, 3% discount) must
    # win in BOTH engines — proves multi-location place_id selection stays in parity.
    loc1 = _loc(10, sci=0.05, tax=0.01, scc=0.04, eiv_unit=1000.0)
    loc2 = _loc(20, sci=0.05, tax=0.01, scc=0.04, struct_discount=0.03, eiv_unit=1000.0)
    rec = Recipe(1, 9000, 1, 600, ((3, 100),), (loc1, loc2), 100)
    return ChainRequest(1, 4, {
        1: Node(1, "W", 1e9, (rec,)),
        3: Node(3, "RAW", 5.0),
    })


def _req_reaction_refinery():
    # Reaction at a refinery with a reactor-rig TE cut (ME stays 1.0) — both engines
    # must agree on the reaction job's qty/time/cost (IO-15 path).
    rloc = _loc(20, slot_kind="reaction", te_mult=0.8, sci=0.05, tax=0.01, scc=0.04, eiv_unit=500.0)
    rec = Recipe(11, 9001, 10, 3600, ((30, 100),), (rloc,), 100)
    return ChainRequest(40, 30, {
        40: Node(40, "Reacted", 5000.0, (rec,)),
        30: Node(30, "Goo", 12.0),
    })


REQUESTS = {
    "two_tier": _req_two_tier,
    "install_me_scc": _req_install_me_scc,
    "reaction": _req_reaction,
    "shared_dag": _req_shared_dag,
    "shared_made_dag": _req_shared_made_dag,
    "buy_beats_make": _req_buy_beats_make,
    "messy_rationals": _req_messy_rationals,
    "multi_location": _req_multi_location,
    "reaction_refinery": _req_reaction_refinery,
}


def _approx(a, b):
    return a == b   # exact: both cores are exact-rational


@pytest.mark.parametrize("name", list(REQUESTS))
def test_haskell_matches_python(name):
    req = REQUESTS[name]()
    py = solve_chain(req)
    hs = chain_engine.solve_native(req)

    assert py.target_type_id == hs.target_type_id
    assert py.target_qty == hs.target_qty
    assert _approx(py.unit_cost, hs.unit_cost)
    assert _approx(py.total_cost, hs.total_cost)

    assert set(py.decisions) == set(hs.decisions)
    for t in py.decisions:
        a, b = py.decisions[t], hs.decisions[t]
        assert ((a.decision, a.recipe_index, a.place_id, a.activity)
                == (b.decision, b.recipe_index, b.place_id, b.activity))
        assert _approx(a.unit_cost, b.unit_cost)
        assert _approx(a.unit_make, b.unit_make)
        assert _approx(a.unit_buy, b.unit_buy)
        assert _approx(a.saved_per_unit, b.saved_per_unit)

    key = lambda j: (j.type_id, j.runs, j.time_s)
    pj, hj = sorted(py.jobs, key=key), sorted(hs.jobs, key=key)
    assert len(pj) == len(hj)
    for a, b in zip(pj, hj):
        assert ((a.type_id, a.activity, a.place_id, a.slot_kind, a.runs, a.qty_out, a.time_s, a.bounceable)
                == (b.type_id, b.activity, b.place_id, b.slot_kind, b.runs, b.qty_out, b.time_s, b.bounceable))
        assert _approx(a.install_cost, b.install_cost)
        assert _approx(a.bpc_cost, b.bpc_cost)
        assert _approx(a.leaf_material_cost, b.leaf_material_cost)
        assert _approx(a.make_cost, b.make_cost)
        assert _approx(a.buy_fallback_total, b.buy_fallback_total)
        ai = sorted(a.inputs, key=lambda i: i.type_id)
        bi = sorted(b.inputs, key=lambda i: i.type_id)
        assert ([(i.type_id, i.qty, i.is_make) for i in ai]
                == [(i.type_id, i.qty, i.is_make) for i in bi])
        for x, y in zip(ai, bi):
            assert _approx(x.unit_cost, y.unit_cost)

    ps = {s.type_id: s for s in py.shopping_list}
    qs = {s.type_id: s for s in hs.shopping_list}
    assert set(ps) == set(qs)
    for t in ps:
        assert ps[t].qty == qs[t].qty
        assert _approx(ps[t].unit, qs[t].unit)
        assert _approx(ps[t].total, qs[t].total)
