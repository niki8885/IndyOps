"""Columnar (DataFrame) access to the market tables."""
import datetime

from app.core.database import MarketIndexSnapshot, TrackPrice
from app.repositories import market_repo

_BASE = datetime.datetime(2025, 1, 1)
_INDEX_COLS = ["timestamp", "price", "volume", "top3_share", "h_index", "entropy", "liquidity"]
_TRACK_COLS = ["timestamp", "place_id", "buy", "sell", "volume"]


def test_index_snapshots_df(app_session):
    for i in range(3):
        app_session.add(MarketIndexSnapshot(
            index_key="mineral", timestamp=_BASE + datetime.timedelta(hours=i),
            price_index=100 + i, volume_index=10 + i,
            top3_share=0.5, h_index=0.3, entropy=1.0, liquidity_index=2.0))
    app_session.add(MarketIndexSnapshot(index_key="plex", timestamp=_BASE, price_index=999))
    app_session.commit()

    df = market_repo.index_snapshots_df(app_session, "mineral")
    assert list(df.columns) == _INDEX_COLS
    assert len(df) == 3
    assert df["price"].tolist() == [100.0, 101.0, 102.0]          # only 'mineral', oldest-first


def test_index_snapshots_df_empty_keeps_columns(app_session):
    df = market_repo.index_snapshots_df(app_session, "nope")
    assert df.empty
    assert list(df.columns) == _INDEX_COLS


def test_track_prices_df_scopes_to_user_and_item(app_session):
    for i in range(2):
        app_session.add(TrackPrice(user_id=1, type_id=34, place_id=60003760,
                                   timestamp=_BASE + datetime.timedelta(hours=i),
                                   buy=5.0 + i, sell=6.0 + i, volume=100.0))
    app_session.add(TrackPrice(user_id=1, type_id=35, place_id=1, timestamp=_BASE, buy=1.0))  # other item
    app_session.add(TrackPrice(user_id=2, type_id=34, place_id=1, timestamp=_BASE, buy=9.0))  # other user
    app_session.commit()

    df = market_repo.track_prices_df(app_session, 1, 34)
    assert list(df.columns) == _TRACK_COLS
    assert len(df) == 2
    assert df["buy"].tolist() == [5.0, 6.0]
