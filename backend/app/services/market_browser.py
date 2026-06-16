from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

from . import indicators, risk
from ._numeric import clean, series


# orders & order book

def _parse_issued(issued: Optional[str]) -> Optional[datetime]:
    if not issued:
        return None
    try:
        return datetime.fromisoformat(issued.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _resolve_location(order: dict, stations: dict, systems: dict, regions: dict) -> dict:
    """Turn an order's location_id/system_id into a display name + region + security."""
    loc_id = order.get("location_id")
    sys_id = order.get("system_id")
    st = stations.get(loc_id)
    if st:
        name = st["name"]
        region_id = st["region_id"]
        sys_id = st["system_id"]
    else:
        srow = systems.get(sys_id)
        name = f"{srow['name']} (structure)" if srow else f"Structure {loc_id}"
        region_id = srow["region_id"] if srow else None
    srow = systems.get(sys_id) or {}
    return {
        "location": name,
        "region": regions.get(region_id),
        "security": clean(srow.get("security")),
        "system_id": sys_id,
    }


def build_orders(orders: list[dict], stations: dict, systems: dict, regions: dict,
                 region_name: Optional[str], limit: int = 250) -> dict:
    """Sellers (sell orders, cheapest first) + Buyers (buy orders, highest first)."""
    sellers: list[dict] = []
    buyers: list[dict] = []
    for o in orders:
        loc = _resolve_location(o, stations, systems, regions)
        issued = _parse_issued(o.get("issued"))
        expires_at = None
        if issued is not None:
            expires_at = (issued + timedelta(days=int(o.get("duration") or 0))).isoformat()
        row = {
            "order_id": o.get("order_id"),
            "price": clean(o.get("price")),
            "quantity": int(o.get("volume_remain") or 0),
            "location": loc["location"],
            "region": loc["region"] or region_name,
            "security": loc["security"],
            "issued": o.get("issued"),
            "expires_at": expires_at,
        }
        if o.get("is_buy_order"):
            row["range"] = o.get("range")
            row["min_volume"] = int(o.get("min_volume") or 1)
            buyers.append(row)
        else:
            sellers.append(row)

    sellers.sort(key=lambda r: (r["price"] is None, r["price"] or 0))
    buyers.sort(key=lambda r: (r["price"] is None, -(r["price"] or 0)))

    best_sell = sellers[0]["price"] if sellers else None
    best_buy = buyers[0]["price"] if buyers else None
    spread = best_sell - best_buy if (best_sell is not None and best_buy is not None) else None
    mid = (best_sell + best_buy) / 2 if (best_sell is not None and best_buy is not None) else None

    return {
        "sellers": sellers[:limit],
        "buyers": buyers[:limit],
        "summary": {
            "best_sell": best_sell,
            "best_buy": best_buy,
            "spread": clean(spread),
            "spread_pct": clean(spread / mid * 100 if (spread is not None and mid) else None),
            "mid": clean(mid),
            "sell_orders": len(sellers),
            "buy_orders": len(buyers),
            "sell_volume": sum(r["quantity"] for r in sellers),
            "buy_volume": sum(r["quantity"] for r in buyers),
        },
    }


def build_orderbook(orders: list[dict], depth: int = 60) -> dict:
    """Aggregate orders into price levels with cumulative volume"""
    asks_map: dict[float, dict] = {}
    bids_map: dict[float, dict] = {}
    for o in orders:
        price = o.get("price")
        if price is None:
            continue
        vol = int(o.get("volume_remain") or 0)
        book = bids_map if o.get("is_buy_order") else asks_map
        lvl = book.setdefault(price, {"price": price, "volume": 0, "orders": 0})
        lvl["volume"] += vol
        lvl["orders"] += 1

    asks = sorted(asks_map.values(), key=lambda x: x["price"])  # ascending
    bids = sorted(bids_map.values(), key=lambda x: -x["price"])  # descending

    cum = 0
    for a in asks:
        cum += a["volume"]
        a["cum"] = cum
    cum = 0
    for b in bids:
        cum += b["volume"]
        b["cum"] = cum

    best_ask = asks[0]["price"] if asks else None
    best_bid = bids[0]["price"] if bids else None
    spread = best_ask - best_bid if (best_ask is not None and best_bid is not None) else None
    mid = (best_ask + best_bid) / 2 if (best_ask is not None and best_bid is not None) else None

    def lvl(x):
        return {"price": clean(x["price"]), "volume": x["volume"],
                "cum": x["cum"], "orders": x["orders"]}

    return {
        "asks": [lvl(a) for a in asks[:depth]],
        "bids": [lvl(b) for b in bids[:depth]],
        "best_ask": clean(best_ask),
        "best_bid": clean(best_bid),
        "spread": clean(spread),
        "spread_pct": clean(spread / mid * 100 if (spread is not None and mid) else None),
        "mid": clean(mid),
        "ask_levels": len(asks),
        "bid_levels": len(bids),
        "ask_depth": asks[-1]["cum"] if asks else 0,
        "bid_depth": bids[-1]["cum"] if bids else 0,
    }


#  history analytics

def _history_frame(history: list[dict]) -> pd.DataFrame:
    """ESI history rows → tidy, time-sorted DataFrame (timestamp/price/volume/…)."""
    df = pd.DataFrame(history)
    df["timestamp"] = pd.to_datetime(df["date"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["price"] = df["average"].astype(float)
    for col in ("highest", "lowest", "volume", "order_count"):
        if col not in df.columns:
            df[col] = None
    return df


def history_payload(history: list[dict], type_id: int, label: str,
                    region_name: Optional[str], window: int) -> dict:
    """Full indicator + risk analytics for one type, shaped like the index payload."""
    win = max(2, int(window))
    df = _history_frame(history)
    price = df["price"]
    vol = pd.to_numeric(df["volume"], errors="coerce")

    ind = indicators.compute(price, win)

    last = float(price.iloc[-1])
    prev = float(price.iloc[-2]) if len(price) > 1 else last
    last7 = df[df["timestamp"] >= df["timestamp"].max() - pd.Timedelta(days=7)]
    stats = {
        "last": clean(last),
        "change_pct": clean((last - prev) / prev * 100 if prev else None),
        "day_high": clean(pd.to_numeric(df["highest"], errors="coerce").iloc[-1]),
        "day_low": clean(pd.to_numeric(df["lowest"], errors="coerce").iloc[-1]),
        "week_avg": clean(last7["price"].mean()),
        "all_max": clean(price.max()),
        "all_min": clean(price.min()),
        "all_avg": clean(price.mean()),
        "volatility": clean(ind.volatility.iloc[-1]),
        "avg_volume": clean(vol.mean()),
        "last_volume": clean(vol.iloc[-1]),
        "points": int(len(df)),
    }

    var = risk.value_at_risk(ind.returns)
    montecarlo = risk.monte_carlo_gbm(ind.returns, last)
    states = risk.volatility_regimes(ind.volatility)

    wd = df.assign(wd=df["timestamp"].dt.weekday, v=vol)
    weekday_volume = [
        clean(wd.loc[wd["wd"] == k, "v"].mean()) if (wd["wd"] == k).any() else None
        for k in range(7)
    ]

    return {
        "type_id": type_id,
        "label": label,
        "region_name": region_name,
        "window": win,
        "timestamps": [t.isoformat() for t in df["timestamp"]],
        "series": {
            "price": series(price), "volume": series(vol),
            "highest": series(pd.to_numeric(df["highest"], errors="coerce")),
            "lowest": series(pd.to_numeric(df["lowest"], errors="coerce")),
            "order_count": series(pd.to_numeric(df["order_count"], errors="coerce")),
            "sma": series(ind.sma), "ema": series(ind.ema),
            "bb_upper": series(ind.bb_upper), "bb_lower": series(ind.bb_lower),
            "rsi": series(ind.rsi), "macd": series(ind.macd),
            "macd_signal": series(ind.macd_signal), "macd_hist": series(ind.macd_hist),
            "returns": series(ind.returns), "volatility": series(ind.volatility),
            "tenkan": series(ind.tenkan), "kijun": series(ind.kijun),
            "senkou_a": series(ind.senkou_a), "senkou_b": series(ind.senkou_b),
        },
        "stats": stats,
        "risk": {"var95": clean(var.var95), "cvar95": clean(var.cvar95),
                 "hist_counts": var.hist_counts, "hist_edges": var.hist_edges},
        "montecarlo": asdict(montecarlo) if montecarlo else None,
        "weekday_volume": weekday_volume,
        "states": asdict(states) if states else None,
    }


# correlation

def correlation_payload(target_label: str, histories: dict[str, list]) -> dict:
    frames: dict[str, pd.Series] = {}
    for label, hist in histories.items():
        if not hist:
            continue
        df = pd.DataFrame(hist)
        if "date" not in df.columns or "average" not in df.columns:
            continue
        s = pd.Series(df["average"].astype(float).values, index=pd.to_datetime(df["date"]))
        frames[label] = s[~s.index.duplicated(keep="last")]

    if target_label not in frames or len(frames) < 2:
        return {"labels": list(frames.keys()), "matrix": [], "to_target": [],
                "target": target_label, "points": 0}

    prices = pd.DataFrame(frames).sort_index()
    returns = prices.pct_change().replace([float("inf"), float("-inf")], pd.NA)
    corr = returns.corr(min_periods=5)

    labels = list(corr.columns)
    matrix = [[clean(corr.iloc[i, j]) for j in range(len(labels))] for i in range(len(labels))]

    to_target = [
        {"label": lbl, "corr": clean(corr.loc[lbl, target_label])}
        for lbl in labels if lbl != target_label
    ]
    to_target.sort(key=lambda x: (x["corr"] is None, -(x["corr"] or 0)))

    overlap = int(returns.dropna(how="any").shape[0])
    return {
        "target": target_label,
        "labels": labels,
        "matrix": matrix,
        "to_target": to_target,
        "points": overlap,
    }
