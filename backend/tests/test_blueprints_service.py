"""Pure blueprint-availability logic (services/blueprints.py). No DB/SDE — golden,
hand-checked expectations for pick_best / run accounting / the requirements report."""
from app.services import blueprints as bp


def _bp(key, ptid, *, is_bpo=False, me=0, te=0, runs=None, quantity=1, cost=None,
        source="esi", owner="Alice", bptype=9000):
    return bp.OwnedBP(key=key, product_type_id=ptid, blueprint_type_id=bptype, name="X BP",
                      is_bpo=is_bpo, me=me, te=te, runs=runs, quantity=quantity,
                      cost=cost, source=source, owner=owner)


def _node(ptid, *, runs_needed, activity=1, me=0, te=0):
    return bp.MakeNode(product_type_id=ptid, product_name=f"P{ptid}", blueprint_type_id=9000,
                       blueprint_name="X BP", activity=activity, runs_needed=runs_needed, me=me, te=te)


def test_is_bpo_detection():
    assert bp.is_bpo(-1, -1) is True          # ESI original
    assert bp.is_bpo(None, -1) is True         # quantity flag alone
    assert bp.is_bpo(10, -2) is False          # a copy with 10 runs
    assert bp.is_bpo(5, 1) is False


def test_owned_runs():
    assert bp.owned_runs(_bp("esi:1", 100, is_bpo=True)) is None       # unlimited
    assert bp.owned_runs(_bp("esi:2", 100, runs=10, quantity=1)) == 10
    assert bp.owned_runs(_bp("man:3", 100, runs=10, quantity=3)) == 30  # manual stack


def test_pick_best_prefers_bpo_then_me_te_runs():
    cands = [
        _bp("esi:1", 100, runs=5, me=10, te=20),
        _bp("esi:2", 100, is_bpo=True, me=0, te=0),      # BPO wins despite low ME
        _bp("esi:3", 100, runs=50, me=8, te=10),
    ]
    assert bp.pick_best(cands).key == "esi:2"
    # without a BPO, best ME wins
    assert bp.pick_best(cands[::2]).key == "esi:1"
    assert bp.pick_best([]) is None


def test_total_owned_runs():
    bpcs = [_bp("esi:1", 100, runs=10), _bp("esi:2", 100, runs=15)]
    assert bp.total_owned_runs(bpcs) == 25
    assert bp.total_owned_runs(bpcs + [_bp("esi:3", 100, is_bpo=True)]) is None


def test_report_bpo_covers_any_runs():
    pool = {100: [_bp("esi:1", 100, is_bpo=True, me=10, te=20, owner="Bob")]}
    [r] = bp.build_report([_node(100, runs_needed=999)], pool)
    assert r["available"] == "bpo"
    assert r["shortfall"] == 0
    assert r["runs_owned"] is None
    assert r["me"] == 10 and r["te"] == 20
    assert "BPO" in r["acquisition"] and "Bob" in r["acquisition"]


def test_report_bpc_exact_and_short():
    ok = {100: [_bp("esi:1", 100, runs=30)]}
    [r] = bp.build_report([_node(100, runs_needed=30)], ok)
    assert r["available"] == "bpc_ok" and r["shortfall"] == 0

    short = {100: [_bp("esi:1", 100, runs=10), _bp("esi:2", 100, runs=5)]}
    [r2] = bp.build_report([_node(100, runs_needed=40)], short)
    assert r2["available"] == "bpc_short"
    assert r2["runs_owned"] == 15
    assert r2["shortfall"] == 25
    assert "25" in r2["acquisition"]


def test_report_missing_and_activity_phrasing():
    [r] = bp.build_report([_node(100, runs_needed=7, activity=1)], {})
    assert r["available"] == "missing"
    assert r["shortfall"] == 7
    assert r["is_owned"] is False
    assert "BPO" in r["acquisition"]

    [rr] = bp.build_report([_node(200, runs_needed=3, activity=11)], {})
    assert rr["available"] == "missing"
    assert "reaction" in rr["acquisition"].lower()


def test_report_sort_missing_first_and_summary():
    pool = {
        1: [_bp("esi:a", 1, is_bpo=True)],
        2: [_bp("esi:b", 2, runs=2)],            # short vs needed 10
    }
    nodes = [_node(1, runs_needed=5), _node(2, runs_needed=10), _node(3, runs_needed=4)]
    report = bp.build_report(nodes, pool)
    assert report[0]["available"] == "missing"   # node 3 sorted first
    s = bp.summarize(report)
    assert s == {"nodes": 3, "required_runs": 19, "owned_bpo": 1,
                 "owned_bpc": 1, "short": 1, "missing": 1}


def test_legacy_fields_present():
    pool = {100: [_bp("esi:1", 100, runs=10, me=3, te=6)]}
    [r] = bp.build_report([_node(100, runs_needed=5)], pool)
    for k in ("type_id", "me", "te", "runs_needed", "runs_owned", "shortfall"):
        assert k in r
    assert r["type_id"] == 100
