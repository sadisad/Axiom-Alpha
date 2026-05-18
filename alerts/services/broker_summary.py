import requests
import threading
import time
import re
import json

try:
    import cloudscraper
    HAS_CLOUDSCRAPER = True
except ImportError:
    HAS_CLOUDSCRAPER = False

_cache = {}
_cache_lock = threading.Lock()
BROKER_CACHE_TTL = 300


def _get_idx_session():
    if HAS_CLOUDSCRAPER:
        return cloudscraper.create_scraper(browser={'browser': 'chrome', 'platform': 'windows', 'desktop': True})
    return requests.Session()


_BROKER_HEADERS = {
    'Accept': 'application/json',
    'Referer': 'https://www.idx.co.id/en/market-data/trading-summary/broker-summary',
}


def _find_idx_js_bundle(session):
    try:
        resp = session.get('https://www.idx.co.id/en', timeout=20)
        if resp.status_code != 200:
            return None
        bundles = re.findall(r'(_nuxt/[a-f0-9]{6,8}\.js)', resp.text)
        if not bundles:
            bundles = re.findall(r'(_nuxt/\w+\.js)', resp.text)
        if not bundles:
            return None
        for bundle in set(bundles):
            try:
                js_resp = session.get(f'https://www.idx.co.id/{bundle}', timeout=15)
                tokens = re.findall(r'Bearer\s+([A-Za-z0-9._-]+)', js_resp.text)
                if tokens:
                    return tokens[0]
            except Exception:
                continue
    except Exception:
        pass
    return None


def _get_idx_token():
    now = time.time()
    with _cache_lock:
        if '_idx_token' in _cache:
            entry = _cache['_idx_token']
            if now - entry['ts'] < 3600:
                return entry['data']
    try:
        session = _get_idx_session()
        session.headers.update(_BROKER_HEADERS)
        if not HAS_CLOUDSCRAPER:
            session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
        token = _find_idx_js_bundle(session)
        if token:
            with _cache_lock:
                _cache['_idx_token'] = {'data': token, 'ts': now}
            return token
    except Exception:
        pass
    return None


def _to_int(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _fmt_idr(val):
    try:
        v = float(val)
        if v >= 1e12:
            return f'{v / 1e12:.1f}T'
        if v >= 1e9:
            return f'{v / 1e9:.1f}B'
        if v >= 1e6:
            return f'{v / 1e6:.1f}M'
        if v >= 1e3:
            return f'{v / 1e3:.1f}K'
        return str(int(v))
    except Exception:
        return str(val)


def get_broker_summary(symbol=None):
    now = time.time()
    cache_key = f'broker_idx'
    with _cache_lock:
        if cache_key in _cache:
            entry = _cache[cache_key]
            if now - entry['ts'] < BROKER_CACHE_TTL:
                return entry['data']

    data = _fetch_idx_broker_summary()
    if data and 'error' not in data:
        with _cache_lock:
            _cache[cache_key] = {'data': data, 'ts': now}
    return data


def _fetch_idx_broker_summary():
    token = _get_idx_token()
    if not token:
        return _fallback_yfinance_broker()

    try:
        session = _get_idx_session()
        session.headers.update({
            **_BROKER_HEADERS,
            'Authorization': f'Bearer {token}',
        })
        if not HAS_CLOUDSCRAPER:
            session.headers['User-Agent'] = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
        resp = session.get(
            'https://www.idx.co.id/primary/TradingSummary/GetBrokerSummary?length=9999&start=0',
            timeout=20,
        )
        if resp.status_code != 200:
            return _fallback_yfinance_broker()

        result = resp.json()
        items = result.get('data', [])
        if not items:
            return {'error': 'No broker data available'}

        all_brokers = []
        for item in items:
            broker = {
                'code': item.get('IDFirm', ''),
                'name': item.get('FirmName', ''),
                'volume': _to_int(item.get('Volume', 0)),
                'value': _to_int(item.get('Value', 0)),
                'frequency': _to_int(item.get('Frequency', 0)),
            }
            all_brokers.append(broker)

        date_str = ''
        if items and items[0].get('Date'):
            date_str = items[0]['Date'][:10]

        total_volume = sum(b['volume'] for b in all_brokers)
        total_value = sum(b['value'] for b in all_brokers)
        total_frequency = sum(b['frequency'] for b in all_brokers)

        for b in all_brokers:
            b['value_pct'] = round(b['value'] / total_value * 100, 2) if total_value else 0
            b['volume_pct'] = round(b['volume'] / total_volume * 100, 2) if total_volume else 0
            b['freq_pct'] = round(b['frequency'] / total_frequency * 100, 2) if total_frequency else 0

        top_by_value = sorted(all_brokers, key=lambda x: x['value'], reverse=True)[:15]
        top_by_volume = sorted(all_brokers, key=lambda x: x['volume'], reverse=True)[:15]
        top_by_frequency = sorted(all_brokers, key=lambda x: x['frequency'], reverse=True)[:15]
        bottom_by_value = sorted(all_brokers, key=lambda x: x['value'])[:10]

        return {
            'source': 'IDX Exchange-Wide',
            'date': date_str,
            'total_volume': total_volume,
            'total_value': total_value,
            'total_frequency': total_frequency,
            'total_value_fmt': _fmt_idr(total_value),
            'total_volume_fmt': _fmt_idr(total_volume),
            'broker_count': len(all_brokers),
            'top_by_value': top_by_value,
            'top_by_volume': top_by_volume,
            'top_by_frequency': top_by_frequency,
            'bottom_by_value': bottom_by_value,
            'all_brokers': all_brokers,
        }
    except requests.exceptions.Timeout:
        return {'error': 'Request to IDX timed out. Please try again.'}
    except requests.exceptions.ConnectionError:
        return {'error': 'Unable to connect to IDX. Please try again later.'}
    except Exception as e:
        return {'error': f'Failed to fetch broker data: {str(e)}'}


def _fallback_yfinance_broker():
    import yfinance as yf

    symbol = 'BBCA.JK'

    try:
        t = yf.Ticker(symbol)
        major = t.major_holders
        inst = t.institutional_holders
        mf = t.mutualfund_holders

        broker_data = {
            'source': 'Global Holders (yfinance)',
            'date': '',
            'total_volume': 0,
            'total_value': 0,
            'total_frequency': 0,
            'total_value_fmt': '-',
            'total_volume_fmt': '-',
            'broker_count': 0,
            'top_by_value': [],
            'top_by_volume': [],
            'top_by_frequency': [],
            'bottom_by_value': [],
            'all_brokers': [],
        }

        holders = []
        if inst is not None and not inst.empty:
            for _, row in inst.iterrows():
                holders.append({
                    'code': str(row.get('Holder', ''))[:4].upper(),
                    'name': str(row.get('Holder', '')),
                    'volume': _to_int(row.get('Shares', 0)),
                    'value': _to_int(row.get('Value', 0)),
                    'frequency': 0,
                    'value_pct': round(float(row.get('pctHeld', 0)) * 100, 2),
                    'volume_pct': 0,
                    'freq_pct': 0,
                })

        if mf is not None and not mf.empty:
            for _, row in mf.iterrows():
                holders.append({
                    'code': str(row.get('Holder', ''))[:4].upper(),
                    'name': str(row.get('Holder', '')),
                    'volume': _to_int(row.get('Shares', 0)),
                    'value': _to_int(row.get('Value', 0)),
                    'frequency': _to_int(row.get('% Out', 0) * 100) if isinstance(row.get('% Out'), (int, float)) else 0,
                    'value_pct': round(float(row.get('pctHeld', 0)) * 100, 2),
                    'volume_pct': 0,
                    'freq_pct': 0,
                })

        if not holders:
            return {'error': 'No broker or holder data available for IDX stocks. The IDX broker summary API is currently unavailable.'}

        holders.sort(key=lambda x: x.get('value', 0), reverse=True)
        broker_data['broker_count'] = len(holders)
        broker_data['top_by_value'] = holders[:15]
        broker_data['top_by_volume'] = sorted(holders, key=lambda x: x.get('volume', 0), reverse=True)[:15]
        broker_data['top_by_frequency'] = sorted(holders, key=lambda x: x.get('frequency', 0), reverse=True)[:15]
        broker_data['bottom_by_value'] = sorted(holders, key=lambda x: x.get('value', 0))[:10]
        broker_data['all_brokers'] = holders
        total_val = sum(h.get('value', 0) for h in holders)
        total_vol = sum(h.get('volume', 0) for h in holders)
        broker_data['total_value'] = total_val
        broker_data['total_volume'] = total_vol
        broker_data['total_value_fmt'] = _fmt_idr(total_val)
        broker_data['total_volume_fmt'] = _fmt_idr(total_vol)

        return broker_data
    except Exception as e:
        return {'error': f'Failed to fetch holder data: {str(e)}'}


def get_broker_summary_api(request):
    return get_broker_summary()