"""Offline unit tests for ``app.adapters.market`` (Fuzzwork + ESI HTTP wrappers).

The network is never touched: ``market.requests.get`` is monkeypatched to return a
tiny ``FakeResponse``. Each public function is exercised on its happy path, its
empty/missing-data branch and its error branch. Module-level caches are reset
before every test so a cached value from one test can't leak into another.
"""
import pytest

from app.adapters import market


class FakeResponse:
    def __init__(self, json_data=None, *, status_code=200, text="", headers=None, raise_exc=None):
        self._json = json_data
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._raise_exc = raise_exc

    def json(self):
        return self._json

    def raise_for_status(self):
        if self._raise_exc is not None:
            raise self._raise_exc


@pytest.fixture(autouse=True)
def _reset_caches():
    """Clear every module-level cache so tests are order-independent."""
    market._ADJ_CACHE.update({"data": None, "ts": 0.0})
    market._COST_IDX_CACHE.update({"data": None, "ts": 0.0})
    market._HIST_CACHE.clear()
    market._ORDERS_CACHE.clear()
    market._ORDERS_ALL_CACHE.clear()
    market._HIST_FULL_CACHE.clear()
    market._ROUTE_CACHE.clear()
    yield


# ── esi_adjusted_prices ──────────────────────────────────────────────────────

def test_esi_adjusted_prices_parses_and_caches(monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return FakeResponse([
            {"type_id": 34, "adjusted_price": 5.5},
            {"type_id": "35", "adjusted_price": None},  # missing → 0.0
        ])

    monkeypatch.setattr(market.requests, "get", fake_get)
    out = market.esi_adjusted_prices()
    assert out == {34: 5.5, 35: 0.0}
    # second call is served from cache → no extra HTTP
    assert market.esi_adjusted_prices() == out
    assert len(calls) == 1


def test_esi_adjusted_prices_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: FakeResponse(raise_exc=RuntimeError("500")))
    with pytest.raises(RuntimeError):
        market.esi_adjusted_prices()


# ── esi_cost_indices ─────────────────────────────────────────────────────────

def test_esi_cost_indices_parses_table(monkeypatch):
    payload = [
        {"solar_system_id": 30000142,
         "cost_indices": [{"activity": "manufacturing", "cost_index": 0.04},
                          {"activity": "reaction", "cost_index": 0.02}]},
        {"solar_system_id": 30000144, "cost_indices": []},  # empty branch
    ]
    monkeypatch.setattr(market.requests, "get", lambda *a, **k: FakeResponse(payload))
    table = market.esi_cost_indices()
    assert table[30000142] == {"manufacturing": 0.04, "reaction": 0.02}
    assert table[30000144] == {}


def test_esi_cost_indices_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: FakeResponse(raise_exc=RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        market.esi_cost_indices()


# ── fuzzwork_aggregates / _or_empty ──────────────────────────────────────────

def test_fuzzwork_aggregates_empty_ids_short_circuits(monkeypatch):
    # must not issue any HTTP for an empty id list
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: pytest.fail("should not be called"))
    assert market.fuzzwork_aggregates(10000002, []) == {}


def test_fuzzwork_aggregates_happy_path(monkeypatch):
    captured = {}

    def fake_get(url, params=None, **kw):
        captured["url"], captured["params"] = url, params
        return FakeResponse({"34": {"buy": {"max": 4.0}, "sell": {"min": 5.0}}})

    monkeypatch.setattr(market.requests, "get", fake_get)
    out = market.fuzzwork_aggregates(10000002, [34, 35])
    assert out["34"]["sell"]["min"] == pytest.approx(5.0)
    assert captured["params"] == {"region": 10000002, "types": "34,35"}


def test_fuzzwork_aggregates_or_empty_swallows_errors(monkeypatch):
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: FakeResponse(raise_exc=RuntimeError("down")))
    assert market.fuzzwork_aggregates_or_empty(10000002, [34]) == {}


def test_fuzzwork_aggregates_or_empty_passthrough(monkeypatch):
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: FakeResponse({"34": {"buy": {"max": 1.0}}}))
    assert market.fuzzwork_aggregates_or_empty(10000002, [34]) == {"34": {"buy": {"max": 1.0}}}


# ── esi_region_history (30-day truncation + None on failure) ──────────────────

def test_esi_region_history_truncates_to_30(monkeypatch):
    rows = [{"date": f"d{i}", "lowest": i} for i in range(40)]
    monkeypatch.setattr(market.requests, "get", lambda *a, **k: FakeResponse(rows))
    out = market.esi_region_history(10000002, 34)
    assert len(out) == 30
    assert out[0]["date"] == "d10"  # last 30 of 40


def test_esi_region_history_none_on_failure(monkeypatch):
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: FakeResponse(raise_exc=RuntimeError("404")))
    assert market.esi_region_history(10000002, 34) is None


def test_esi_region_history_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: (calls.append(1), FakeResponse([{"lowest": 1}]))[1])
    market.esi_region_history(1, 2)
    market.esi_region_history(1, 2)
    assert len(calls) == 1


# ── gnf_local (HTML scrape) ──────────────────────────────────────────────────

_GNF_HTML = """
<html><body>
<div id="C-J6MT">
  <table><tr><th>Min</th><td>1,234.50 ISK</td></tr></table>
  <table><tr><th>Max</th><td>1,000.00 ISK</td></tr></table>
</div>
</body></html>
"""


def test_gnf_local_parses_buy_sell(monkeypatch):
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: FakeResponse(text=_GNF_HTML))
    out = market.gnf_local(34)
    assert out == {"sell": 1234.5, "buy": 1000.0}


def test_gnf_local_missing_region_div(monkeypatch):
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: FakeResponse(text="<html><body>nope</body></html>"))
    assert market.gnf_local(34) is None


def test_gnf_local_too_few_tables(monkeypatch):
    html = '<div id="C-J6MT"><table><tr><th>Min</th><td>5</td></tr></table></div>'
    monkeypatch.setattr(market.requests, "get", lambda *a, **k: FakeResponse(text=html))
    assert market.gnf_local(34) is None


def test_gnf_local_none_on_failure(monkeypatch):
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: FakeResponse(raise_exc=RuntimeError("x")))
    assert market.gnf_local(34) is None


def test_fnum_helper():
    assert market._fnum("3.5") == pytest.approx(3.5)
    assert market._fnum(None) is None
    assert market._fnum("abc") is None


# ── esi_region_orders (paginated, never raises) ──────────────────────────────

def test_esi_region_orders_paginates(monkeypatch):
    def fake_get(url, params=None, **kw):
        page = params["page"]
        if page == 1:
            return FakeResponse([{"order_id": 1}], headers={"X-Pages": "2"})
        return FakeResponse([{"order_id": 2}])

    monkeypatch.setattr(market.requests, "get", fake_get)
    out = market.esi_region_orders(10000002, 34)
    assert [o["order_id"] for o in out] == [1, 2]


def test_esi_region_orders_returns_empty_on_failure(monkeypatch):
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: FakeResponse(raise_exc=RuntimeError("boom")))
    assert market.esi_region_orders(10000002, 34) == []


def test_esi_region_orders_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: (calls.append(1), FakeResponse([{"order_id": 1}]))[1])
    market.esi_region_orders(7, 8)
    market.esi_region_orders(7, 8)
    assert len(calls) == 1


# ── esi_region_orders_all (whole region, page cap) ───────────────────────────

def test_esi_region_orders_all_paginates(monkeypatch):
    def fake_get(url, params=None, **kw):
        if params["page"] == 1:
            return FakeResponse([{"type_id": 34}], headers={"X-Pages": "3"})
        return FakeResponse([{"type_id": 35}])

    monkeypatch.setattr(market.requests, "get", fake_get)
    out = market.esi_region_orders_all(10000002)
    assert len(out) == 3  # page 1 + pages 2,3


def test_esi_region_orders_all_caps_pages(monkeypatch):
    fetched = []

    def fake_get(url, params=None, **kw):
        fetched.append(params["page"])
        if params["page"] == 1:
            return FakeResponse([{"type_id": 1}], headers={"X-Pages": "50"})
        return FakeResponse([{"type_id": 2}])

    monkeypatch.setattr(market.requests, "get", fake_get)
    market.esi_region_orders_all(10000002, max_pages=2)
    assert fetched == [1, 2]  # capped, never reaches page 3+


def test_esi_region_orders_all_empty_on_failure(monkeypatch):
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: FakeResponse(raise_exc=RuntimeError("x")))
    assert market.esi_region_orders_all(10000002) == []


# ── esi_region_history_full (untruncated) ────────────────────────────────────

def test_esi_region_history_full_not_truncated(monkeypatch):
    rows = [{"lowest": i} for i in range(40)]
    monkeypatch.setattr(market.requests, "get", lambda *a, **k: FakeResponse(rows))
    out = market.esi_region_history_full(10000002, 34)
    assert len(out) == 40


def test_esi_region_history_full_none_on_failure(monkeypatch):
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: FakeResponse(raise_exc=RuntimeError("x")))
    assert market.esi_region_history_full(10000002, 34) is None


# ── esi_route ────────────────────────────────────────────────────────────────

def test_esi_route_parses_ids(monkeypatch):
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: FakeResponse([30000142, "30000144", 30000139]))
    route = market.esi_route(30000142, 30000139)
    assert route == [30000142, 30000144, 30000139]


def test_esi_route_none_on_failure(monkeypatch):
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: FakeResponse(raise_exc=RuntimeError("unreachable")))
    assert market.esi_route(1, 2) is None


def test_esi_route_caches(monkeypatch):
    calls = []
    monkeypatch.setattr(market.requests, "get",
                        lambda *a, **k: (calls.append(1), FakeResponse([1, 2]))[1])
    market.esi_route(1, 2)
    market.esi_route(1, 2)
    assert len(calls) == 1
