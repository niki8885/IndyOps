from __future__ import annotations
import logging
import time as _time
from typing import Optional
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "IndyOps/1.0"}
_TIMEOUT = 30

_AGG_URL = "https://market.fuzzwork.co.uk/aggregates/"
_ESI_PRICES_URL = "https://esi.evetech.net/latest/markets/prices/?datasource=tranquility"
_GNF_REGION = "C-J6MT"

_ADJ_CACHE: dict = {"data": None, "ts": 0.0}
_ADJ_TTL = 3600


def esi_adjusted_prices() -> dict:
    """ESI adjusted prices keyed by type_id (cached 1h). Raises on HTTP error."""
    now = _time.time()
    if _ADJ_CACHE["data"] is not None and now - _ADJ_CACHE["ts"] < _ADJ_TTL:
        return _ADJ_CACHE["data"]
    resp = requests.get(_ESI_PRICES_URL, timeout=_TIMEOUT, headers=_HEADERS)
    resp.raise_for_status()
    data = {int(e["type_id"]): float(e.get("adjusted_price") or 0) for e in resp.json()}
    _ADJ_CACHE["data"] = data
    _ADJ_CACHE["ts"] = now
    return data


def fuzzwork_aggregates(region: int, type_ids: list[int]) -> dict:
    """Fuzzwork aggregate data keyed by type_id (str). Raises on HTTP error."""
    if not type_ids:
        return {}
    ids = ",".join(str(t) for t in type_ids)
    resp = requests.get(_AGG_URL, params={"region": region, "types": ids}, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def fuzzwork_aggregates_or_empty(region: int, type_ids: list[int]) -> dict:
    """Like :func:`fuzzwork_aggregates` but swallows errors to {} (warns)."""
    try:
        return fuzzwork_aggregates(region, type_ids)
    except Exception as exc:
        logger.warning("fuzzwork region %s failed: %s", region, exc)
        return {}


_HIST_CACHE: dict = {}
_HIST_TTL = 6 * 3600


def esi_region_history(region_id: int, type_id: int) -> Optional[list]:
    """Last 30 days of ESI market history for (region, type). None on failure."""
    key = (region_id, type_id)
    now = _time.time()
    hit = _HIST_CACHE.get(key)
    if hit and now - hit[0] < _HIST_TTL:
        return hit[1]
    try:
        r = requests.get(
            f"https://esi.evetech.net/latest/markets/{region_id}/history/",
            params={"type_id": type_id, "datasource": "tranquility"},
            headers=_HEADERS, timeout=25,
        )
        r.raise_for_status()
        data = r.json()[-30:]
    except Exception:
        data = None
    _HIST_CACHE[key] = (now, data)
    return data


def _fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def gnf_local(type_id: int) -> Optional[dict]:
    """Scrape C-J local buy/sell from appraise.gnf.lt. None on failure."""
    try:
        resp = requests.get(f"https://appraise.gnf.lt/item/{type_id}", timeout=25, headers=_HEADERS)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        tab = soup.find("div", id=_GNF_REGION)
        if not tab:
            return None
        tables = tab.find_all("table")
        if len(tables) < 2:
            return None

        def parse(t):
            out = {}
            for row in t.find_all("tr"):
                th, td = row.find("th"), row.find("td")
                if th and td:
                    raw = td.text.strip().replace(",", "").replace(" ISK", "")
                    out[th.text.strip()] = _fnum(raw)
            return out

        sell = parse(tables[0]);
        buy = parse(tables[1])
        return {"sell": sell.get("Min") or sell.get("1st Percentile"),
                "buy": buy.get("Max") or buy.get("99th Percentile")}
    except Exception:
        return None


# ── ESI live order book (full buy+sell order list for one type in a region) ──
# Fuzzwork only gives aggregates (best/percentile/volume); the Market Browser's
# Orders and Order Book tabs need the individual orders, which only ESI exposes.
_ORDERS_CACHE: dict = {}
_ORDERS_TTL = 180  # orders move fast — a 3-min cache absorbs tab switches without hammering ESI
_ESI_ORDERS_URL = "https://esi.evetech.net/latest/markets/{region_id}/orders/"


def esi_region_orders(region_id: int, type_id: int) -> list[dict]:
    """All live buy+sell orders for (region, type) from ESI. Paginated, cached 3 min.

    Each order carries: order_id, price, volume_remain, volume_total, min_volume,
    is_buy_order, range, location_id, system_id, duration, issued. Returns whatever
    was fetched (possibly ``[]``) — never raises.
    """
    cache_key = (region_id, type_id)
    now = _time.time()
    hit = _ORDERS_CACHE.get(cache_key)
    if hit and now - hit[0] < _ORDERS_TTL:
        return hit[1]

    url = _ESI_ORDERS_URL.format(region_id=region_id)
    params = {"datasource": "tranquility", "order_type": "all", "type_id": type_id, "page": 1}
    orders: list[dict] = []
    try:
        r = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
        r.raise_for_status()
        orders.extend(r.json())
        pages = int(r.headers.get("X-Pages", 1) or 1)
        for page in range(2, min(pages, 10) + 1):  # cap at 10 pages (10k orders) for safety
            params["page"] = page
            rp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
            rp.raise_for_status()
            orders.extend(rp.json())
    except Exception as exc:
        logger.warning("esi orders region %s type %s failed: %s", region_id, type_id, exc)

    _ORDERS_CACHE[cache_key] = (now, orders)
    return orders


_HIST_FULL_CACHE: dict = {}


def esi_region_history_full(region_id: int, type_id: int) -> Optional[list]:
    """Full daily ESI market history (up to ~13 months) for (region, type).

    Like :func:`esi_region_history` but *not* truncated to 30 days — the Market
    Browser uses the long range for technical/risk analytics. None on failure.
    """
    cache_key = (region_id, type_id)
    now = _time.time()
    hit = _HIST_FULL_CACHE.get(cache_key)
    if hit and now - hit[0] < _HIST_TTL:
        return hit[1]
    try:
        r = requests.get(
            f"https://esi.evetech.net/latest/markets/{region_id}/history/",
            params={"type_id": type_id, "datasource": "tranquility"},
            headers=_HEADERS, timeout=25,
        )
        r.raise_for_status()
        data = r.json()
    except Exception:
        data = None
    _HIST_FULL_CACHE[cache_key] = (now, data)
    return data
