from __future__ import annotations
import pandas as pd
from app.core.database import MarketIndexSnapshot, TrackPrice

_INDEX_COLS = ["timestamp", "price", "volume", "top3_share", "h_index", "entropy", "liquidity"]
_TRACK_COLS = ["timestamp", "place_id", "buy", "sell", "volume"]


def index_snapshots_df(db, key: str) -> pd.DataFrame:
    """All snapshots for one index, oldest-first, as a DataFrame."""
    rows = (
        db.query(
            MarketIndexSnapshot.timestamp, MarketIndexSnapshot.price_index,
            MarketIndexSnapshot.volume_index, MarketIndexSnapshot.top3_share,
            MarketIndexSnapshot.h_index, MarketIndexSnapshot.entropy,
            MarketIndexSnapshot.liquidity_index,
        )
        .filter(MarketIndexSnapshot.index_key == key)
        .order_by(MarketIndexSnapshot.timestamp.asc())
        .all()
    )
    df = pd.DataFrame(rows, columns=_INDEX_COLS)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def track_prices_df(db, user_id: int, type_id: int) -> pd.DataFrame:
    """All tracked-price rows for one (user, item), oldest-first, as a DataFrame."""
    rows = (
        db.query(
            TrackPrice.timestamp, TrackPrice.place_id,
            TrackPrice.buy, TrackPrice.sell, TrackPrice.volume,
        )
        .filter(TrackPrice.user_id == user_id, TrackPrice.type_id == type_id)
        .order_by(TrackPrice.timestamp.asc())
        .all()
    )
    df = pd.DataFrame(rows, columns=_TRACK_COLS)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
    return df
