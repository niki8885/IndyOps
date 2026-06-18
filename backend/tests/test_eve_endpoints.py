"""
EVE SDE-lookup endpoints (app/api/eve_router.py): SDE status, system/region/type
search, per-type volumes, live industry cost indices, and the C-J6MT price
scrape. Tested the project's no-HTTP way — the async endpoint functions are
called directly against an in-memory SQLite SDE session seeded with EveBase
rows; ESI / GNF-scrape I/O is monkeypatched so no network is touched.
"""
import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import eve_router as er
from app.core.database_eve import (
    EveBase, EveType, EveGroup, EveRegion, EveSolarSystem,
)

USER = SimpleNamespace(id=1)


def run(coro):
    return asyncio.run(coro)


def _mem_db(base):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


@pytest.fixture
def eve_db():
    session, engine = _mem_db(EveBase)
    yield session
    session.close(); engine.dispose()


# ── seeders ────────────────────────────────────────────────────────────────

def _seed_types(eve_db):
    eve_db.add_all([
        EveGroup(group_id=27, category_id=6, group_name="Battleship"),
        EveGroup(group_id=18, category_id=4, group_name="Mineral"),
        # The Raven family — exercises the relevance ranking in /types/search.
        EveType(type_id=638, type_name="Raven", group_id=27, volume=486000.0,
                portion_size=1, market_group_id=80, published=True),
        EveType(type_id=17636, type_name="Raven Navy Issue", group_id=27,
                volume=486000.0, portion_size=1, market_group_id=80, published=True),
        EveType(type_id=998, type_name="Raven Blueprint", group_id=27,
                volume=0.01, portion_size=1, market_group_id=None, published=False),
        EveType(type_id=34, type_name="Tritanium", group_id=18, volume=0.01,
                portion_size=1, published=True),
    ])
    eve_db.commit()


def _seed_map(eve_db):
    eve_db.add_all([
        EveRegion(region_id=10000002, region_name="The Forge"),
        EveRegion(region_id=10000043, region_name="Domain"),
        EveSolarSystem(solar_system_id=30000142, solar_system_name="Jita",
                       security=0.9, region_id=10000002),
        EveSolarSystem(solar_system_id=30002187, solar_system_name="Amarr",
                       security=1.0, region_id=10000043),
        EveSolarSystem(solar_system_id=30000144, solar_system_name="Perimeter",
                       security=0.95, region_id=10000002),
    ])
    eve_db.commit()


# ── /sde/status ──────────────────────────────────────────────────────────────

def test_sde_status_empty(eve_db):
    out = run(er.sde_status(eve_db=eve_db))
    assert out == {"synced": False, "type_count": 0}


def test_sde_status_synced(eve_db):
    _seed_types(eve_db)
    out = run(er.sde_status(eve_db=eve_db))
    assert out["synced"] is True and out["type_count"] == 4


# ── POST /sde/update (spawns a daemon thread; stub the worker) ────────────────

def test_trigger_sde_update(monkeypatch):
    import app.tasks.update_sde as upd
    called = {}
    monkeypatch.setattr(upd, "run_sde_update", lambda **kw: called.update(kw))
    out = run(er.trigger_sde_update(current_user=USER))
    assert out["status"] == "started"
    # the daemon thread should have invoked the stubbed worker with force=True
    import time
    for _ in range(50):
        if called:
            break
        time.sleep(0.01)
    assert called == {"force": True}


# ── /systems ─────────────────────────────────────────────────────────────────

def test_search_systems_prefix(eve_db):
    _seed_map(eve_db)
    rows = run(er.search_systems(q="Ji", limit=15, eve_db=eve_db))
    assert [r.solar_system_name for r in rows] == ["Jita"]
    assert rows[0].solar_system_id == 30000142
    assert rows[0].security == pytest.approx(0.9)


def test_search_systems_ordered(eve_db):
    _seed_map(eve_db)
    # ilike "{q}%" → prefix match only; "Pe" matches Perimeter, not Jita/Amarr
    rows = run(er.search_systems(q="Pe", limit=15, eve_db=eve_db))
    assert [r.solar_system_name for r in rows] == ["Perimeter"]


def test_search_systems_no_match(eve_db):
    _seed_map(eve_db)
    rows = run(er.search_systems(q="zz", limit=15, eve_db=eve_db))
    assert rows == []


# ── /regions ─────────────────────────────────────────────────────────────────

def test_search_regions_substring(eve_db):
    _seed_map(eve_db)
    # region uses %q% (substring); "or" hits "The Forge"
    rows = run(er.search_regions(q="or", limit=15, eve_db=eve_db))
    assert [r.region_name for r in rows] == ["The Forge"]


def test_search_regions_no_match(eve_db):
    _seed_map(eve_db)
    rows = run(er.search_regions(q="zzz", limit=15, eve_db=eve_db))
    assert rows == []


# ── /volumes ─────────────────────────────────────────────────────────────────

def test_get_volumes(eve_db):
    _seed_types(eve_db)
    out = run(er.get_volumes(type_ids="638,34", eve_db=eve_db))
    assert out == {638: 486000.0, 34: 0.01}


def test_get_volumes_filters_non_numeric(eve_db):
    _seed_types(eve_db)
    # "abc" is dropped; "34" survives
    out = run(er.get_volumes(type_ids="abc,34", eve_db=eve_db))
    assert out == {34: 0.01}


def test_get_volumes_empty(eve_db):
    out = run(er.get_volumes(type_ids="abc,,xyz", eve_db=eve_db))
    assert out == {}


# ── /types/search (relevance ranking) ────────────────────────────────────────

def test_search_types_exact_beats_variants(eve_db):
    _seed_types(eve_db)
    rows = run(er.search_types(q="Raven", limit=25, eve_db=eve_db))
    names = [r.type_name for r in rows]
    # exact "Raven" first; published variants before the unpublished blueprint
    assert names[0] == "Raven"
    assert set(names) == {"Raven", "Raven Navy Issue", "Raven Blueprint"}
    assert names.index("Raven Navy Issue") < names.index("Raven Blueprint")
    # group_name comes from the outer join
    assert rows[0].group_name == "Battleship"
    assert rows[0].volume == pytest.approx(486000.0)


def test_search_types_no_match(eve_db):
    _seed_types(eve_db)
    rows = run(er.search_types(q="zzz", limit=25, eve_db=eve_db))
    assert rows == []


# ── /industry/cost-index ──────────────────────────────────────────────────────

def test_cost_index_by_system_name(eve_db, monkeypatch):
    _seed_map(eve_db)
    monkeypatch.setattr(er.market, "esi_cost_indices",
                        lambda: {30000142: {"manufacturing": 0.0421, "reaction": 0.02}})
    out = run(er.get_cost_index(system_name="Jita", solar_system_id=None, eve_db=eve_db))
    assert out["solar_system_id"] == 30000142
    assert out["manufacturing"] == pytest.approx(0.0421)
    assert out["reaction"] == pytest.approx(0.02)
    assert out["copying"] is None


def test_cost_index_by_system_id(eve_db, monkeypatch):
    _seed_map(eve_db)
    monkeypatch.setattr(er.market, "esi_cost_indices",
                        lambda: {30002187: {"manufacturing": 0.01}})
    out = run(er.get_cost_index(system_name=None, solar_system_id=30002187, eve_db=eve_db))
    assert out["solar_system_id"] == 30002187
    assert out["manufacturing"] == pytest.approx(0.01)


def test_cost_index_requires_input(eve_db):
    with pytest.raises(er.HTTPException) as ei:
        run(er.get_cost_index(system_name=None, solar_system_id=None, eve_db=eve_db))
    assert ei.value.status_code == 400


def test_cost_index_system_not_found(eve_db):
    _seed_map(eve_db)
    with pytest.raises(er.HTTPException) as ei:
        run(er.get_cost_index(system_name="Nowhere", solar_system_id=None, eve_db=eve_db))
    assert ei.value.status_code == 404


def test_cost_index_esi_failure(eve_db, monkeypatch):
    _seed_map(eve_db)
    def _boom():
        raise RuntimeError("timeout")
    monkeypatch.setattr(er.market, "esi_cost_indices", _boom)
    with pytest.raises(er.HTTPException) as ei:
        run(er.get_cost_index(system_name=None, solar_system_id=30000142, eve_db=eve_db))
    assert ei.value.status_code == 502


def test_cost_index_no_data_for_system(eve_db, monkeypatch):
    _seed_map(eve_db)
    monkeypatch.setattr(er.market, "esi_cost_indices", lambda: {99999999: {"manufacturing": 0.05}})
    with pytest.raises(er.HTTPException) as ei:
        run(er.get_cost_index(system_name=None, solar_system_id=30000142, eve_db=eve_db))
    assert ei.value.status_code == 404


# ── /prices/cj (GNF scrape, monkeypatched) ────────────────────────────────────

def test_cj_prices(monkeypatch):
    monkeypatch.setattr(er, "_fetch_gnf_price",
                        lambda tid: {"buy": 100.0, "sell": 120.0, "split": 110.0} if tid == 34 else None)
    out = run(er.get_cj_prices(type_ids="34,638"))
    # only type 34 returned a price; 638 → None is dropped
    assert out == {34: {"buy": 100.0, "sell": 120.0, "split": 110.0}}


def test_cj_prices_no_valid_ids():
    with pytest.raises(er.HTTPException) as ei:
        run(er.get_cj_prices(type_ids="abc,,xyz"))
    assert ei.value.status_code == 400


# ── _get_eve_db dependency generator ──────────────────────────────────────────

def test_get_eve_db_yields_and_closes(monkeypatch):
    closed = {"v": False}

    class _Sess:
        def close(self):
            closed["v"] = True

    monkeypatch.setattr(er, "EveSessionLocal", lambda: _Sess())
    gen = er._get_eve_db()
    sess = next(gen)
    assert isinstance(sess, _Sess)
    gen.close()  # triggers the finally → close()
    assert closed["v"] is True


# ── _fetch_gnf_price (HTML scrape parsing, no network) ────────────────────────

_GNF_HTML = """
<html><body>
<div id="C-J6MT">
  <table><tr><th>Min</th><td>1,234.50 ISK</td></tr><tr><th>junk</th><td>oops</td></tr></table>
  <table><tr><th>Max</th><td>1,000.00 ISK</td></tr></table>
</div>
</body></html>
"""


class _Resp:
    def __init__(self, text, raise_exc=None):
        self.text = text
        self._raise = raise_exc

    def raise_for_status(self):
        if self._raise:
            raise self._raise


def test_fetch_gnf_price_parses_html(monkeypatch):
    monkeypatch.setattr(er._requests, "get", lambda url, **kw: _Resp(_GNF_HTML))
    out = er._fetch_gnf_price(34)
    assert out == {"buy": 1000.0, "sell": 1234.5, "split": pytest.approx(1117.25)}


def test_fetch_gnf_price_region_div_missing(monkeypatch):
    monkeypatch.setattr(er._requests, "get",
                        lambda url, **kw: _Resp("<html><body>no region</body></html>"))
    assert er._fetch_gnf_price(34) is None


def test_fetch_gnf_price_too_few_tables(monkeypatch):
    html = '<html><body><div id="C-J6MT"><table></table></div></body></html>'
    monkeypatch.setattr(er._requests, "get", lambda url, **kw: _Resp(html))
    assert er._fetch_gnf_price(34) is None


def test_fetch_gnf_price_missing_prices(monkeypatch):
    # both tables present but neither has Min/Max/percentile rows
    html = ('<html><body><div id="C-J6MT">'
            '<table><tr><th>foo</th><td>1.0</td></tr></table>'
            '<table><tr><th>bar</th><td>2.0</td></tr></table>'
            '</div></body></html>')
    monkeypatch.setattr(er._requests, "get", lambda url, **kw: _Resp(html))
    assert er._fetch_gnf_price(34) is None


def test_fetch_gnf_price_request_exception(monkeypatch):
    def _boom(url, **kw):
        raise RuntimeError("connection refused")
    monkeypatch.setattr(er._requests, "get", _boom)
    assert er._fetch_gnf_price(34) is None
