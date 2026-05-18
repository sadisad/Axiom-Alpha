"""Technical analysis indicators computed from yfinance OHLCV history.

Returns a structured payload similar to TradingView's Technical Analysis widget
but fully owned by us. Designed for the per-stock detail page (screener).

Indicators:
    Trend Following: SMA(5,10,20,50,100,200), Super Trend (10, 3)
    Oscillators: RSI(6,12), ADX(6,12), CCI(5,10), Williams %R(5,10),
                 ROC(5,10), Ultimate Oscillator(5,10), Stochastic(5x3, 14x7)

Each indicator returns {value, signal} where signal is 'Buy', 'Sell', or 'Neutral'.
"""
import logging
import math
import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)


def _yf_symbol(symbol, market):
    return f'{symbol}.JK' if market == 'ID' and not str(symbol).endswith('.JK') else symbol


def _fetch_ohlcv(symbol, market):
    sym = _yf_symbol(symbol, market)
    try:
        df = yf.Ticker(sym).history(period='1y', auto_adjust=False)
    except Exception as e:
        logger.warning(f'history fetch failed for {sym}: {e}')
        return None
    if df is None or df.empty:
        return None
    return df.dropna(subset=['Close']).copy()


# ---- Indicator primitives ----

def _wilder(series, n):
    """Wilder's smoothing: EMA with alpha = 1/n."""
    return series.ewm(alpha=1.0 / n, adjust=False).mean()


def _sma(close, n):
    if len(close) < n:
        return None
    return float(close.tail(n).mean())


def _atr_series(df, n):
    high, low, close = df['High'], df['Low'], df['Close']
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs(),
    ], axis=1).max(axis=1)
    return _wilder(tr, n)


def _rsi(close, n):
    if len(close) < n + 1:
        return None
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = _wilder(gain, n)
    avg_loss = _wilder(loss, n)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    val = rsi.iloc[-1]
    return float(val) if pd.notna(val) else None


def _adx(df, n):
    if len(df) < n * 2:
        return None
    high = df['High']
    low = df['Low']
    up = high.diff()
    dn = -low.diff()
    plus_dm = up.where((up > dn) & (up > 0), 0.0)
    minus_dm = dn.where((dn > up) & (dn > 0), 0.0)
    atr = _atr_series(df, n).replace(0, np.nan)
    plus_di = 100 * _wilder(plus_dm, n) / atr
    minus_di = 100 * _wilder(minus_dm, n) / atr
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = _wilder(dx, n)
    val = adx.iloc[-1]
    return float(val) if pd.notna(val) else None


def _cci(df, n):
    if len(df) < n:
        return None
    tp = (df['High'] + df['Low'] + df['Close']) / 3
    sma_tp = tp.rolling(n).mean()
    mad = (tp - sma_tp).abs().rolling(n).mean()
    cci = (tp - sma_tp) / (0.015 * mad.replace(0, np.nan))
    val = cci.iloc[-1]
    return float(val) if pd.notna(val) else None


def _williams_r(df, n):
    if len(df) < n:
        return None
    high_n = df['High'].rolling(n).max()
    low_n = df['Low'].rolling(n).min()
    wr = -100 * (high_n - df['Close']) / (high_n - low_n).replace(0, np.nan)
    val = wr.iloc[-1]
    return float(val) if pd.notna(val) else None


def _roc(close, n):
    if len(close) < n + 1:
        return None
    return float((close.iloc[-1] / close.iloc[-1 - n] - 1) * 100)


def _ultimate_oscillator(df, fast, slow):
    """Simplified Ultimate Oscillator using two periods (fast, slow)."""
    if len(df) < slow + 1:
        return None
    close = df['Close']
    high = df['High']
    low = df['Low']
    bp = close - pd.concat([low, close.shift()], axis=1).min(axis=1)
    tr = pd.concat([high, close.shift()], axis=1).max(axis=1) - pd.concat([low, close.shift()], axis=1).min(axis=1)
    tr_safe = tr.replace(0, np.nan)
    avg_fast = bp.rolling(fast).sum() / tr_safe.rolling(fast).sum()
    avg_slow = bp.rolling(slow).sum() / tr_safe.rolling(slow).sum()
    uo = 100 * (avg_fast + avg_slow) / 2
    val = uo.iloc[-1]
    return float(val) if pd.notna(val) else None


def _stochastic(df, k_period, d_period):
    if len(df) < k_period + d_period:
        return None
    high_n = df['High'].rolling(k_period).max()
    low_n = df['Low'].rolling(k_period).min()
    pct_k = 100 * (df['Close'] - low_n) / (high_n - low_n).replace(0, np.nan)
    pct_d = pct_k.rolling(d_period).mean()
    val = pct_d.iloc[-1]
    return float(val) if pd.notna(val) else None


def _supertrend(df, period=10, multiplier=3.0):
    n = len(df)
    if n < period + 2:
        return None, 'Neutral'
    high = df['High'].values
    low = df['Low'].values
    close = df['Close'].values
    atr = _atr_series(df, period).values
    hl2 = (high + low) / 2.0
    upper = hl2 + multiplier * atr
    lower = hl2 - multiplier * atr
    final_up = np.zeros(n)
    final_lo = np.zeros(n)
    st = np.zeros(n)
    # Seed first non-NaN bar
    seed = period
    final_up[seed] = upper[seed] if not math.isnan(upper[seed]) else 0
    final_lo[seed] = lower[seed] if not math.isnan(lower[seed]) else 0
    st[seed] = final_lo[seed]
    for i in range(seed + 1, n):
        if math.isnan(atr[i]):
            final_up[i] = final_up[i-1]
            final_lo[i] = final_lo[i-1]
            st[i] = st[i-1]
            continue
        final_up[i] = upper[i] if (upper[i] < final_up[i-1] or close[i-1] > final_up[i-1]) else final_up[i-1]
        final_lo[i] = lower[i] if (lower[i] > final_lo[i-1] or close[i-1] < final_lo[i-1]) else final_lo[i-1]
        if st[i-1] == final_up[i-1]:
            st[i] = final_up[i] if close[i] <= final_up[i] else final_lo[i]
        else:
            st[i] = final_lo[i] if close[i] >= final_lo[i] else final_up[i]
    last = float(st[-1])
    sig = 'Buy' if close[-1] > last else 'Sell'
    return last, sig


# ---- Signal classifiers ----

def _sma_signal(price, sma):
    if sma is None or price is None:
        return 'Neutral'
    if price > sma:
        return 'Buy'
    if price < sma:
        return 'Sell'
    return 'Neutral'


def _rsi_signal(rsi):
    if rsi is None:
        return 'Neutral'
    if rsi < 30:
        return 'Buy'
    if rsi > 70:
        return 'Sell'
    return 'Neutral'


def _adx_signal(adx, recent_pct):
    if adx is None:
        return 'Neutral'
    if adx < 20:
        return 'Neutral'
    return 'Buy' if recent_pct > 0 else 'Sell'


def _cci_signal(cci):
    if cci is None:
        return 'Neutral'
    if cci > 100:
        return 'Buy'
    if cci < -100:
        return 'Sell'
    return 'Neutral'


def _wr_signal(wr):
    if wr is None:
        return 'Neutral'
    if wr < -80:
        return 'Buy'
    if wr > -20:
        return 'Sell'
    return 'Neutral'


def _roc_signal(roc):
    if roc is None:
        return 'Neutral'
    return 'Buy' if roc > 0 else 'Sell'


def _band_signal(val, lo, hi):
    if val is None:
        return 'Neutral'
    if val < lo:
        return 'Buy'
    if val > hi:
        return 'Sell'
    return 'Neutral'


def _counts(items):
    bear = sum(1 for i in items if i['signal'] == 'Sell')
    neu = sum(1 for i in items if i['signal'] == 'Neutral')
    bull = sum(1 for i in items if i['signal'] == 'Buy')
    return {'bearish': bear, 'neutral': neu, 'bullish': bull}


def _round(v, places=2):
    return round(v, places) if v is not None else None


def get_technical_analysis(symbol, market='US'):
    df = _fetch_ohlcv(symbol, market)
    if df is None or len(df) < 30:
        return {'error': 'Not enough historical data for technical analysis.'}

    close = df['Close']
    last_price = float(close.iloc[-1])
    # Direction context for ADX (last 5 bars %)
    pc5 = float((close.iloc[-1] / close.iloc[-6] - 1) * 100) if len(close) > 6 else 0.0

    # Trend Following
    trend = []
    for n in (5, 10, 20, 50, 100, 200):
        v = _sma(close, n)
        trend.append({'name': f'SMA ({n})', 'value': _round(v), 'signal': _sma_signal(last_price, v)})
    st_val, st_sig = _supertrend(df, period=10, multiplier=3.0)
    trend.append({'name': 'Super Trend (10, 3)', 'value': _round(st_val), 'signal': st_sig})

    # Oscillators
    osc = []
    for n in (6, 12):
        v = _rsi(close, n)
        osc.append({'name': f'RSI ({n})', 'value': _round(v), 'signal': _rsi_signal(v)})
    for n in (6, 12):
        v = _adx(df, n)
        osc.append({'name': f'ADX ({n})', 'value': _round(v), 'signal': _adx_signal(v, pc5)})
    for n in (5, 10):
        v = _cci(df, n)
        osc.append({'name': f'CCI ({n})', 'value': _round(v), 'signal': _cci_signal(v)})
    for n in (5, 10):
        v = _williams_r(df, n)
        osc.append({'name': f'%R ({n})', 'value': _round(v), 'signal': _wr_signal(v)})
    for n in (5, 10):
        v = _roc(close, n)
        osc.append({'name': f'ROC ({n})', 'value': _round(v), 'signal': _roc_signal(v)})
    for fast, slow in ((5, 10), (10, 20)):
        v = _ultimate_oscillator(df, fast, slow)
        osc.append({'name': f'UO ({fast})', 'value': _round(v), 'signal': _band_signal(v, 30, 70)})
    for k, d in ((5, 3), (14, 7)):
        v = _stochastic(df, k, d)
        osc.append({'name': f'Stochastic ({k}, {d})', 'value': _round(v), 'signal': _band_signal(v, 20, 80)})

    return {
        'symbol': str(symbol).upper(),
        'market': market,
        'price': round(last_price, 2),
        'trend_following': {'items': trend, 'counts': _counts(trend)},
        'oscillators': {'items': osc, 'counts': _counts(osc)},
    }
