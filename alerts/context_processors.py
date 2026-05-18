import os
from datetime import datetime


def firebase_config(request):
    return {
        'FIREBASE_API_KEY': os.environ.get('FIREBASE_API_KEY', ''),
        'FIREBASE_AUTH_DOMAIN': os.environ.get('FIREBASE_AUTH_DOMAIN', ''),
        'FIREBASE_PROJECT_ID_JS': os.environ.get('FIREBASE_PROJECT_ID', ''),
    }


def subscription_context(request):
    if request.user.is_authenticated:
        try:
            profile = request.user.profile
            return {
                'user_plan': profile.plan,
                'is_premium': profile.is_premium,
            }
        except Exception:
            return {
                'user_plan': 'basic',
                'is_premium': False,
            }
    return {
        'user_plan': 'basic',
        'is_premium': False,
    }


def market_status_context(request):
    is_open = False
    status_text = 'CLOSED'
    status_color = '#ef4444'
    idx_is_open = False
    idx_status_text = 'CLOSED'
    idx_status_color = '#ef4444'
    try:
        import pytz
        # US market (NYSE / NASDAQ): 09:30–16:00 ET, Mon–Fri
        eastern = pytz.timezone('US/Eastern')
        now_et = datetime.now(eastern)
        is_weekday_us = now_et.weekday() < 5
        market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        is_open = is_weekday_us and market_open <= now_et <= market_close
        status_text = 'OPEN' if is_open else 'CLOSED'
        status_color = '#10b981' if is_open else '#ef4444'

        # IDX (Indonesia Stock Exchange): 09:00–16:00 WIB, Mon–Fri
        wib = pytz.timezone('Asia/Jakarta')
        now_wib = datetime.now(wib)
        is_weekday_id = now_wib.weekday() < 5
        idx_open = now_wib.replace(hour=9, minute=0, second=0, microsecond=0)
        idx_close = now_wib.replace(hour=16, minute=0, second=0, microsecond=0)
        idx_is_open = is_weekday_id and idx_open <= now_wib <= idx_close
        idx_status_text = 'OPEN' if idx_is_open else 'CLOSED'
        idx_status_color = '#10b981' if idx_is_open else '#ef4444'
    except Exception:
        pass
    return {
        'market_is_open': is_open,
        'market_status_text': status_text,
        'market_status_color': status_color,
        'idx_market_is_open': idx_is_open,
        'idx_market_status_text': idx_status_text,
        'idx_market_status_color': idx_status_color,
    }