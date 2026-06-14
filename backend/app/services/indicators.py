from __future__ import annotations
from dataclasses import dataclass

import pandas as pd


@dataclass
class Indicators:
    sma: pd.Series
    std: pd.Series
    ema: pd.Series  # EMA(window) — used by tracking
    bb_upper: pd.Series
    bb_lower: pd.Series
    returns: pd.Series  # pct_change — used by analysis (risk)
    volatility: pd.Series  # rolling std of returns — used by analysis
    rsi: pd.Series
    macd: pd.Series
    macd_signal: pd.Series
    macd_hist: pd.Series
    tenkan: pd.Series
    kijun: pd.Series
    senkou_a: pd.Series
    senkou_b: pd.Series


def compute(price: pd.Series, window: int) -> Indicators:
    """
    Full indicator set for ``price``. ``window`` drives SMA/BB/EMA/volatility;
    RSI(14), MACD(12/26/9) and Ichimoku(9/26/52) use their conventional spans.
    """
    win = max(2, int(window))

    sma = price.rolling(win).mean()
    std = price.rolling(win).std()
    ema = price.ewm(span=win, adjust=False).mean()
    bb_upper = sma + 2 * std
    bb_lower = sma - 2 * std

    returns = price.pct_change()
    volatility = returns.rolling(win).std()

    delta = price.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    rs = up.rolling(14).mean() / down.rolling(14).mean()
    rsi = 100 - (100 / (1 + rs))

    ema12 = price.ewm(span=12, adjust=False).mean()
    ema26 = price.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    macd_hist = macd - macd_signal

    hi9 = price.rolling(9).max();
    lo9 = price.rolling(9).min()
    tenkan = (hi9 + lo9) / 2
    hi26 = price.rolling(26).max();
    lo26 = price.rolling(26).min()
    kijun = (hi26 + lo26) / 2
    senkou_a = ((tenkan + kijun) / 2).shift(26)
    hi52 = price.rolling(52).max();
    lo52 = price.rolling(52).min()
    senkou_b = ((hi52 + lo52) / 2).shift(26)

    return Indicators(
        sma=sma, std=std, ema=ema, bb_upper=bb_upper, bb_lower=bb_lower,
        returns=returns, volatility=volatility,
        rsi=rsi, macd=macd, macd_signal=macd_signal, macd_hist=macd_hist,
        tenkan=tenkan, kijun=kijun, senkou_a=senkou_a, senkou_b=senkou_b,
    )
