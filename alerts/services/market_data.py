import yfinance as yf
import time
import threading
from datetime import datetime, timedelta

_cache = {}
_cache_lock = threading.Lock()
CACHE_TTL = 300  # 5 minutes

def _get_cached(key, fetch_fn, ttl=None):
    if ttl is None:
        ttl = CACHE_TTL
    now = time.time()
    with _cache_lock:
        if key in _cache:
            entry = _cache[key]
            if now - entry['ts'] < ttl:
                return entry['data']
    data = fetch_fn()
    with _cache_lock:
        _cache[key] = {'data': data, 'ts': now}
    return data

def _safe_info(ticker_sym, fields=None):
    try:
        t = yf.Ticker(ticker_sym)
        info = t.info
        if fields:
            return {f: info.get(f) for f in fields}
        return info
    except Exception:
        return {}

def _safe_history(ticker_sym, period='1mo'):
    try:
        t = yf.Ticker(ticker_sym)
        return t.history(period=period)
    except Exception:
        return None

SP500_SYMBOLS = [
    'MSFT','AAPL','NVDA','AMZN','GOOGL','META','BRK-B','LLY','AVGO','TSLA',
    'JPM','V','UNH','XOM','MA','PG','COST','HD','ABBV','MRK',
    'CRM','AMD','AMGN','ORCL','ADBE','NFLX','INTC','CSCO','PYPL','QCOM',
    'BKNG','SBUX','MDLZ','GILD','ADP','CMCSA','TMUS','PGR','ISRG','VRTX',
    'REGN','MRVL','KLAC','SNPS','CDNS','FTNT','ANET','MCHP','NXPI','MPWR',
]
SP500_SAMPLE = SP500_SYMBOLS[:30]
IDX_SYMBOLS = ['BBCA.JK','BBRI.JK','TLKM.JK','BMRI.JK','ASII.JK','UNVR.JK']

TOP_RATED_SYMBOLS = [
    'MU','NVDA','V','MSFT','MA','NEM','GOOGL','CRM','META','PGR',
]
TRENDING_PORTFOLIO_SYMBOLS = {
    'US MidCaps Growth': ['IWM'],
    'Global Growth': ['VTI','VXUS'],
    'US Growth Rockets': ['QQQ'],
    'US Smart Value': ['VTV'],
    'Global GEAR+': ['SPY','VWO'],
}

SCORING_WEIGHTS = {
    'growth': 0.25,
    'quality': 0.25,
    'value': 0.20,
    'momentum': 0.20,
    'risk': 0.10,
}

def compute_score(info, hist=None):
    scores = {}
    revenue_growth = info.get('revenueGrowth') or info.get('revenueGrowthQuarterly') or 0
    earnings_growth = info.get('earningsGrowth') or info.get('earningsQuarterlyGrowth') or 0
    if isinstance(revenue_growth, (int, float)):
        revenue_growth *= 100
    if isinstance(earnings_growth, (int, float)):
        earnings_growth *= 100
    scores['growth'] = min(100, max(0, 50 + revenue_growth / 2 + earnings_growth / 4))

    roe = info.get('returnOnEquity') or 0
    profit_margin = info.get('profitMargins') or 0
    if isinstance(roe, (int, float)) and isinstance(profit_margin, (int, float)):
        quality = min(100, max(0, 50 + roe * 100 + profit_margin * 80))
    else:
        quality = 50
    scores['quality'] = min(100, max(0, quality))

    pe = info.get('trailingPE') or info.get('forwardPE') or 0
    pb = info.get('priceToBook') or 0
    if pe and isinstance(pe, (int, float)):
        val_score = min(100, max(0, 100 - pe / 3))
    elif pb and isinstance(pb, (int, float)):
        val_score = min(100, max(0, 100 - pb * 10))
    else:
        val_score = 50
    scores['value'] = val_score

    if hist is not None and not hist.empty and len(hist) >= 5:
        try:
            close = hist['Close']
            pct_1m = (close.iloc[-1] / close.iloc[0] - 1) * 100
            mom = min(100, max(0, 50 + pct_1m * 2))
        except Exception:
            mom = 50
    else:
        mom = 50
    scores['momentum'] = mom

    beta = info.get('beta') or 1
    if isinstance(beta, (int, float)):
        risk = min(100, max(0, 100 - abs(beta - 1) * 30))
    else:
        risk = 50
    scores['risk'] = risk

    total = sum(scores[k] * SCORING_WEIGHTS[k] for k in SCORING_WEIGHTS)
    scores['score'] = round(total, 1)
    for k in scores:
        scores[k] = round(scores[k])
    return scores

def score_color(v):
    if v >= 80: return '#00c896'
    if v >= 50: return '#ffc800'
    return '#ff6464'

def score_bg(v):
    if v >= 80: return ('rgba(0,200,150,0.18)', '#00c896')
    if v >= 50: return ('rgba(255,200,0,0.15)', '#ffc800')
    return ('rgba(239,68,68,0.12)', '#ff6464')

def get_market_scores(symbols=None, market='US'):
    if symbols is None:
        symbols = SP500_SAMPLE

    def fetch():
        results = []
        for sym in symbols:
            try:
                info = _safe_info(sym, [
                    'shortName','marketCap','revenueGrowth','revenueGrowthQuarterly',
                    'earningsGrowth','earningsQuarterlyGrowth','returnOnEquity',
                    'profitMargins','trailingPE','forwardPE','priceToBook','beta',
                    'currentPrice','previousClose',
                ])
                if not info or not info.get('shortName'):
                    continue
                hist = _safe_history(sym, period='1mo')
                scores = compute_score(info, hist)
                price = info.get('currentPrice') or info.get('previousClose') or 0
                prev = info.get('previousClose') or price
                change_pct = ((price - prev) / prev * 100) if prev and price else 0
                sym_display = sym.replace('.JK','')
                results.append({
                    't': sym_display,
                    'n': info.get('shortName','')[:20],
                    'mc': _fmt_mcap(info.get('marketCap')),
                    'g': scores['growth'],
                    'q': scores['quality'],
                    'v': scores['value'],
                    'm': scores['momentum'],
                    'r': scores['risk'],
                    's': scores['score'],
                    'p': round(price, 2) if price else 0,
                    'ch': round(change_pct, 2),
                })
            except Exception:
                continue
        results.sort(key=lambda x: x['s'], reverse=True)
        return results

    cache_key = f'scores_{market}_{hash(tuple(symbols))}'
    return _get_cached(cache_key, fetch, ttl=CACHE_TTL)

def get_dashboard_gauges(market='US'):
    symbols = SP500_SYMBOLS[:20]

    def fetch():
        all_scores = {'growth': [], 'quality': [], 'value': [], 'momentum': [], 'risk': []}
        for sym in symbols:
            try:
                info = _safe_info(sym, ['revenueGrowth','revenueGrowthQuarterly',
                    'earningsGrowth','earningsQuarterlyGrowth','returnOnEquity',
                    'profitMargins','trailingPE','forwardPE','priceToBook','beta'])
                if not info or not info.get('trailingPE'):
                    continue
                scores = compute_score(info)
                for k in all_scores:
                    all_scores[k].append(scores[k])
            except Exception:
                continue

        gauges = []
        labels = {'growth':'Growth','quality':'Quality','value':'Value',
                  'momentum':'Momentum','risk':'Risk Shield'}
        if not any(all_scores.values()):
            gauges = [
                {'label':'Growth','value':50,'color':'#ffc800','dash':50},
                {'label':'Quality','value':50,'color':'#ffc800','dash':50},
                {'label':'Value','value':50,'color':'#ffc800','dash':50},
                {'label':'Momentum','value':50,'color':'#ffc800','dash':50},
                {'label':'Risk Shield','value':50,'color':'#ffc800','dash':50},
            ]
        else:
            for k in ['growth','quality','value','momentum','risk']:
                avg = round(sum(all_scores[k]) / len(all_scores[k])) if all_scores[k] else 50
                gauges.append({
                    'label': labels[k],
                    'value': avg,
                    'color': score_color(avg),
                    'dash': avg,
                })
        return gauges

    return _get_cached('dash_gauges', fetch, ttl=CACHE_TTL)

def get_dashboard_key_stats(market='US'):
    sp500_sym = 'SPY' if market == 'US' else 'EIDO'

    def fetch():
        info = _safe_info(sp500_sym, [
            'forwardPE','dividendYield','revenueGrowth','currentPrice','previousClose',
            'fiftyDayAverage','twoHundredDayAverage',
        ])
        price = info.get('currentPrice') or 0
        prev = info.get('previousClose') or price
        ch_1d = ((price - prev) / prev * 100) if prev and price else 0
        fwd_pe = info.get('forwardPE') or 0
        div_y = info.get('dividendYield') or 0
        rev_g = info.get('revenueGrowth') or 0
        if isinstance(div_y, (int, float)):
            div_y *= 100
        if isinstance(rev_g, (int, float)):
            rev_g *= 100

        stats = [
            {'label': 'Fwd P/E', 'value': f'{fwd_pe:.1f}x' if fwd_pe else '-'},
            {'label': 'Div Yield', 'value': f'{div_y:.1f}%' if div_y else '-'},
            {'label': 'Rev Growth', 'value': f'+{rev_g:.1f}%' if rev_g else '-'},
            {'label': '1D', 'value': f'{ch_1d:+.1f}%' if ch_1d else '-'},
        ]

        try:
            hist = _safe_history(sp500_sym, period='1mo')
            if hist is not None and not hist.empty and len(hist) >= 2:
                ch_1m = (hist['Close'].iloc[-1] / hist['Close'].iloc[0] - 1) * 100
                stats.append({'label': '1M', 'value': f'{ch_1m:+.1f}%'})
            else:
                stats.append({'label': '1M', 'value': '-'})
        except Exception:
            stats.append({'label': '1M', 'value': '-'})

        return stats

    return _get_cached('dash_key_stats', fetch, ttl=CACHE_TTL)

def get_returns_data(market='US'):
    symbols = ['NVDA','MU','META','AVGO','CRM','PLTR','AMD','TSLA','INTC','BA',
                'DIS','PGR','XOM','CVX','BMY','WFC','COP','BAC','ORCL','QCOM']

    periods = {'1W':'5d','1M':'1mo','3M':'3mo','YTD':'ytd','1Y':'1y'}

    def fetch():
        data = {}
        for period_key, yf_period in periods.items():
            top = []
            bottom = []
            changes = []
            for sym in symbols:
                try:
                    hist = _safe_history(sym, period=yf_period)
                    if hist is not None and not hist.empty and len(hist) >= 2:
                        pct = (hist['Close'].iloc[-1] / hist['Close'].iloc[0] - 1) * 100
                        info = _safe_info(sym, ['shortName'])
                        name = info.get('shortName', sym)[:15]
                        changes.append({'sym': sym, 'name': name, 'pct': round(pct, 1)})
                except Exception:
                    continue
            changes.sort(key=lambda x: x['pct'], reverse=True)
            for c in changes[:6]:
                pct_val = c['pct']
                top.append({
                    'symbol': c['sym'],
                    'name': c['name'],
                    'pct': str(abs(pct_val)),
                    'is_positive': pct_val >= 0,
                })
            for c in changes[-6:]:
                pct_val = c['pct']
                bottom.append({
                    'symbol': c['sym'],
                    'name': c['name'],
                    'pct': str(abs(pct_val)),
                    'is_positive': pct_val >= 0,
                })
            data[period_key] = {'top': top, 'bottom': bottom}
        return data

    return _get_cached(f'returns_{market}', fetch, ttl=CACHE_TTL)

def get_top_rated(market='US'):
    symbols = TOP_RATED_SYMBOLS if market == 'US' else IDX_SYMBOLS[:8]

    def fetch():
        results = []
        for sym in symbols:
            try:
                info = _safe_info(sym, [
                    'shortName','marketCap','revenueGrowth','revenueGrowthQuarterly',
                    'earningsGrowth','earningsQuarterlyGrowth','returnOnEquity',
                    'profitMargins','trailingPE','forwardPE','priceToBook','beta',
                ])
                if not info or not info.get('shortName'):
                    continue
                scores = compute_score(info)
                bg_g, fg_g = score_bg(scores['growth'])
                bg_q, fg_q = score_bg(scores['quality'])
                bg_v, fg_v = score_bg(scores['value'])
                bg_m, fg_m = score_bg(scores['momentum'])
                bg_r, fg_r = score_bg(scores['risk'])
                sym_display = sym.replace('.JK','')
                results.append({
                    'ticker': sym_display,
                    'name': info.get('shortName','')[:20],
                    'mcap': _fmt_mcap(info.get('marketCap')),
                    'growth': scores['growth'],
                    'quality': scores['quality'],
                    'value': scores['value'],
                    'mom': scores['momentum'],
                    'risk': scores['risk'],
                    'score': scores['score'],
                    'growth_bg': bg_g, 'growth_fg': fg_g,
                    'quality_bg': bg_q, 'quality_fg': fg_q,
                    'value_bg': bg_v, 'value_fg': fg_v,
                    'mom_bg': bg_m, 'mom_fg': fg_m,
                    'risk_bg': bg_r, 'risk_fg': fg_r,
                })
            except Exception:
                continue
        results.sort(key=lambda x: x['score'], reverse=True)
        return results

    return _get_cached(f'top_rated_{market}', fetch, ttl=CACHE_TTL)

def get_trending_portfolios():
    def fetch():
        results = []
        for name, syms in TRENDING_PORTFOLIO_SYMBOLS.items():
            etf_sym = syms[0]
            try:
                hist = _safe_history(etf_sym, period='1y')
                if hist is None or hist.empty or len(hist) < 5:
                    continue
                close = hist['Close']
                w1 = ((close.iloc[-1] / close.iloc[-6]) - 1) * 100 if len(close) >= 6 else 0
                m1 = ((close.iloc[-1] / close.iloc[-22]) - 1) * 100 if len(close) >= 22 else 0
                ytd_start = close.iloc[0] if len(close) > 0 else close.iloc[-1]
                ytd = ((close.iloc[-1] / ytd_start) - 1) * 100
                y1 = ((close.iloc[-1] / close.iloc[0]) - 1) * 100
                results.append({
                    'name': name,
                    'w1': f'{w1:+.1f}%',
                    'm1': f'{m1:+.1f}%',
                    'ytd': f'{ytd:+.1f}%',
                    'y1': f'{y1:+.1f}%',
                    'w1_pos': w1 >= 0,
                    'm1_pos': m1 >= 0,
                    'ytd_pos': ytd >= 0,
                    'y1_pos': y1 >= 0,
                })
            except Exception:
                continue
        return results

    return _get_cached('trending_portfolios', fetch, ttl=CACHE_TTL)

def get_strategy_picks():
    strategies = {
        'compounders': ['MSFT','AAPL','V','MA','COST'],
        'hypergrowth': ['NVDA','AVGO','PLTR','AMD','CRM'],
        'value': ['XOM','BAC','NEM','PGR','INTC'],
        'momentum': ['META','GOOGL','NFLX','TSLA','QCOM'],
    }

    def fetch():
        picks = {}
        for strategy, syms in strategies.items():
            items = []
            for sym in syms:
                try:
                    info = _safe_info(sym, [
                        'shortName','trailingPE','forwardPE',
                        'currentPrice','previousClose',
                    ])
                    if not info or not info.get('shortName'):
                        continue
                    price = info.get('currentPrice') or info.get('previousClose') or 0
                    prev = info.get('previousClose') or price
                    m1 = ((price / prev) - 1) * 100 if prev and price else 0

                    try:
                        h = _safe_history(sym, period='1y')
                        if h is not None and not h.empty and len(h) >= 2:
                            y1 = (h['Close'].iloc[-1] / h['Close'].iloc[0] - 1) * 100
                        else:
                            y1 = 0
                    except Exception:
                        y1 = 0

                    fwd_pe = info.get('forwardPE') or info.get('trailingPE') or '-'
                    if isinstance(fwd_pe, (int, float)):
                        fwd_pe = f'{fwd_pe:.1f}'
                    sector = info.get('industry', info.get('sector', ''))
                    market = 'US'

                    items.append({
                        'symbol': sym,
                        'name': info.get('shortName', sym),
                        'strategy': strategy,
                        'sector': sector,
                        'market': market,
                        'fwd_pe': fwd_pe,
                        'm1': f'{m1:+.0f}%' if isinstance(m1, (int, float)) else '-',
                        'y1': f'{y1:+.0f}%' if isinstance(y1, (int, float)) else '-',
                        'm1_pos': m1 >= 0,
                        'y1_pos': y1 >= 0,
                    })
                except Exception:
                    continue
            picks[strategy] = items
        return picks

    return _get_cached('strategy_picks', fetch, ttl=CACHE_TTL)

def get_stock_info_batch(symbols):
    results = {}
    for sym in symbols:
        try:
            info = _safe_info(sym, ['shortName','currentPrice','previousClose'])
            price = info.get('currentPrice') or info.get('previousClose') or 0
            prev = info.get('previousClose') or price
            change = ((price - prev) / prev * 100) if prev and price else 0
            results[sym] = {
                'name': info.get('shortName', sym),
                'price': f'{price:,.2f}' if price else '-',
                'change': round(change, 2),
                'is_positive': change >= 0,
            }
        except Exception:
            results[sym] = {'name': sym, 'price': '-', 'change': 0, 'is_positive': True}
    return results

def _fmt_mcap(mc):
    if mc is None:
        return '-'
    try:
        mc = float(mc)
        if mc >= 1e12: return f'${mc/1e12:.1f}T'
        if mc >= 1e9: return f'${mc/1e9:.1f}B'
        if mc >= 1e6: return f'${mc/1e6:.1f}M'
        return f'${mc:,.0f}'
    except Exception:
        return '-'