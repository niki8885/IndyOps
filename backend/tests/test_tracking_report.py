"""The tracked-item detail builder (pure, over a track_prices DataFrame)."""
import datetime

import pandas as pd

from app.services.tracking_report import build_item_detail

PLACES = {
    1: {"name": "Jita", "kind": "region", "special": False},
    2: {"name": "Amarr", "kind": "region", "special": False},
}
ITEM = {"id": 10, "type_id": 34, "name": "Tritanium"}


def _tp(rows):
    base = datetime.datetime(2025, 1, 1)
    return pd.DataFrame(
        [{"timestamp": base + datetime.timedelta(hours=o), "place_id": pid, "buy": b, "sell": s, "volume": v}
         for pid, o, b, s, v in rows],
        columns=["timestamp", "place_id", "buy", "sell", "volume"],
    )


def test_two_places_with_indicators():
    rows = []
    for i in range(30):
        rows.append((1, i, 5.0 + i, 6.0 + i, 100.0))
        rows.append((2, i, 4.0 + i, 7.0 + i, 50.0))
    p = build_item_detail(ITEM, PLACES, _tp(rows), [1, 2], None, 10)
    assert p["item"] == ITEM
    assert set(p["series_by_place"]) == {1, 2}
    assert len(p["series_by_place"][1]["buy"]) == 30
    assert p["places"][0]["points"] == 30
    assert p["selected_place_id"] in (1, 2)
    assert p["window"] == 10
    assert p["indicators"] is not None and p["spread"] is not None


def test_requested_place_is_honoured():
    rows = ([(1, i, 5.0 + i, 6.0 + i, 100.0) for i in range(20)]
            + [(2, i, 4.0 + i, 7.0 + i, 50.0) for i in range(20)])
    assert build_item_detail(ITEM, PLACES, _tp(rows), [1, 2], 2, 10)["selected_place_id"] == 2


def test_empty_history():
    p = build_item_detail(ITEM, {1: PLACES[1]}, _tp([]), [1], None, 10)
    assert p["series_by_place"][1]["buy"] == []
    assert p["places"][0]["points"] == 0
    assert p["selected_place_id"] is None
    assert p["indicators"] is None and p["distribution"] is None and p["spread"] is None


def test_window_clamped():
    rows = [(1, i, 5.0 + i, 6.0 + i, 100.0) for i in range(5)]
    assert build_item_detail(ITEM, {1: PLACES[1]}, _tp(rows), [1], None, 1)["window"] == 2
