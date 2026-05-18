import json
import numpy as np
from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.http import require_POST


class NumpyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

from django import forms
from .services.valuation import get_fundamental_analysis
from .models import WatchlistItem, SearchHistory, PortfolioItem
from .services.market_data import (
    get_dashboard_gauges, get_dashboard_key_stats, get_returns_data,
    get_top_rated, get_trending_portfolios, get_strategy_picks,
    SP500_SYMBOLS, IDX_SYMBOLS, STOCK_LISTS, get_market_scores,
    batch_stock_data, compute_score, _safe_info, _fmt_mcap, _get_cached,
    SCORES_CACHE_TTL,
)
from .services.broker_summary import get_broker_summary
from .firebase_db import (
    get_watchlist, toggle_watchlist as fw_toggle_watchlist, check_in_watchlist,
    add_search_history, get_search_history,
    get_portfolio, add_portfolio, remove_portfolio,
)
import decimal
import logging

logger = logging.getLogger(__name__)


class RegisterForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'auth-input',
            'placeholder': 'Choose a username',
        })
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={
            'class': 'auth-input',
            'placeholder': 'Enter your email',
        })
    )
    password1 = forms.CharField(
        label='Password',
        widget=forms.PasswordInput(attrs={
            'class': 'auth-input',
            'placeholder': 'Create a password',
        })
    )
    password2 = forms.CharField(
        label='Password confirmation',
        widget=forms.PasswordInput(attrs={
            'class': 'auth-input',
            'placeholder': 'Confirm your password',
        })
    )

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exists():
            raise forms.ValidationError('This username is already taken.')
        return username

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email=email).exists():
            raise forms.ValidationError('This email is already registered.')
        return email

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get('password1')
        p2 = cleaned_data.get('password2')
        if p1 and p2 and p1 != p2:
            raise forms.ValidationError('Passwords do not match.')
        return cleaned_data


class LoginForm(forms.Form):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'auth-input',
            'placeholder': 'Enter your username',
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'auth-input',
            'placeholder': 'Enter your password',
        })
    )

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned_data = super().clean()
        username = cleaned_data.get('username')
        password = cleaned_data.get('password')
        if username and password:
            user = authenticate(request=self.request, username=username, password=password)
            if user is None:
                raise forms.ValidationError('Invalid username or password.')
            cleaned_data['user'] = user
        return cleaned_data


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    # Simple per-IP rate limit on POST: max 8 attempts per 5 minutes.
    # Uses Django cache, so it works with locmem in dev and shared cache (e.g.
    # Redis) in production. Returns 429 with a friendly message when exceeded.
    if request.method == 'POST':
        from django.core.cache import cache
        ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() \
             or request.META.get('REMOTE_ADDR', 'unknown')
        key = f'login_attempts:{ip}'
        attempts = cache.get(key, 0)
        if attempts >= 8:
            return render(request, 'registration/login.html', {
                'form': LoginForm(),
                'rate_limited': True,
                'retry_after_minutes': 5,
            }, status=429)
        # Increment first; reset on success below.
        cache.set(key, attempts + 1, timeout=300)

    if request.method == 'POST':
        form = LoginForm(request.POST, request=request)
        if form.is_valid():
            user = form.cleaned_data['user']
            login(request, user)
            # Clear rate-limit counter on successful login.
            try:
                from django.core.cache import cache
                ip = request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip() \
                     or request.META.get('REMOTE_ADDR', 'unknown')
                cache.delete(f'login_attempts:{ip}')
            except Exception:
                pass
            return redirect('dashboard')
    else:
        form = LoginForm()
    return render(request, 'registration/login.html', {'form': form})


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = User.objects.create_user(
                username=form.cleaned_data['username'],
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password1'],
            )
            login(request, user)
            return redirect('dashboard')
    else:
        form = RegisterForm()
    return render(request, 'registration/register.html', {'form': form})


def about(request):
    return render(request, 'alerts/about.html')


def maps(request):
    return render(request, 'alerts/maps.html')


def radar(request):
    return render(request, 'alerts/radar.html')


def radar_scores(request):
    market = request.GET.get('market', 'US')
    try:
        size = min(max(int(request.GET.get('size', 25)), 1), 100)
    except (TypeError, ValueError):
        size = 25
    list_key = request.GET.get('list', '')

    # Cache hot results in-process. Key includes the inputs that affect output.
    # 90s TTL is short enough to feel "live" but cuts ~90% of yfinance load.
    from django.core.cache import cache
    cache_key = f'radar_scores:{market}:{size}:{list_key}'
    cached = cache.get(cache_key)
    if cached is not None:
        return JsonResponse(cached)

    if list_key and list_key in STOCK_LISTS:
        symbols = STOCK_LISTS[list_key]['symbols'][:100]
    elif market == 'ID':
        symbols = IDX_SYMBOLS[:size]
    else:
        symbols = SP500_SYMBOLS[:size]
    try:
        scores = get_market_scores(symbols, market)
        payload = {'stocks': scores, 'market': market, 'size': len(symbols)}
        cache.set(cache_key, payload, timeout=90)
        return JsonResponse(payload)
    except Exception as e:
        # Don't cache errors — let next request retry.
        return JsonResponse({'stocks': [], 'market': market, 'error': str(e)})


def stock_lists(request):
    from django.core.cache import cache
    cached = cache.get('stock_lists:groups')
    if cached is not None:
        return JsonResponse(cached)
    categories = {}
    for key, lst in STOCK_LISTS.items():
        cat = lst['category']
        if cat not in categories:
            categories[cat] = []
        categories[cat].append({
            'key': key,
            'name': lst['name'],
            'emoji': lst['emoji'],
            'count': len(lst['symbols']),
        })
    ordered = ['TRENDING', 'LISTS', 'ETF']
    result = []
    for cat in ordered:
        if cat in categories:
            result.append({'category': cat, 'lists': categories[cat]})
    for cat in categories:
        if cat not in ordered:
            result.append({'category': cat, 'lists': categories[cat]})
    payload = {'groups': result}
    # Static data — cache 1 hour.
    cache.set('stock_lists:groups', payload, timeout=3600)
    return JsonResponse(payload)


def headlines(request):
    return render(request, 'alerts/headlines.html')


def watchtower(request):
    context = {}
    if request.user.is_authenticated:
        uid = request.user.pk
        saved = get_watchlist(uid)
        pairs = [(item['symbol'], item.get('market', 'US')) for item in saved]
        stock_data = batch_stock_data(pairs) if pairs else {}
        watchlist_items = []
        for item in saved:
            data = stock_data.get(item['symbol'], {'name': item['symbol'], 'price': '-', 'change': 0, 'is_positive': True})
            watchlist_items.append({
                'symbol': item['symbol'], 'market': item.get('market', 'US'),
                'name': data.get('name', item['symbol']),
                'price': data.get('price', '-'),
                'change': data.get('change', 0),
                'is_positive': data.get('is_positive', True),
            })
        context['watchlist_items'] = watchlist_items
        from .models import PriceAlert
        context['alerts'] = PriceAlert.objects.filter(user=request.user, is_active=True).order_by('-created_at')
    return render(request, 'alerts/watchtower.html', context)


def portfolios(request):
    context = {}
    if request.user.is_authenticated:
        uid = request.user.pk
        positions = get_portfolio(uid)
        pairs = [(pos['symbol'], pos.get('market', 'US')) for pos in positions]
        stock_data = batch_stock_data(pairs) if pairs else {}
        portfolio_items = []
        total_value = 0
        total_cost = 0
        total_pnl = 0
        first_symbol = 'SPY'
        for idx, pos in enumerate(positions):
            data = stock_data.get(pos['symbol'], {})
            current_price = data.get('current_price', 0)
            buy_price = float(pos['buy_price'])
            qty = float(pos['quantity'])
            cost_basis = buy_price * qty
            current_value = current_price * qty
            pnl = current_value - cost_basis
            pnl_pct = (pnl / cost_basis * 100) if cost_basis else 0
            portfolio_items.append({
                'id': pos['id'],
                'symbol': pos['symbol'], 'market': pos.get('market', 'US'),
                'name': pos.get('company_name', '') or data.get('name', pos['symbol']),
                'quantity': qty, 'buy_price': buy_price,
                'current_price': round(current_price, 2),
                'current_value': round(current_value, 2),
                'cost_basis': round(cost_basis, 2),
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_pct, 2),
                'is_positive': pnl >= 0,
            })
            total_value += current_value
            total_cost += cost_basis
            total_pnl += pnl
            if idx == 0:
                first_symbol = pos['symbol']
        context['portfolio_items'] = portfolio_items
        context['total_value'] = round(total_value, 2)
        context['total_cost'] = round(total_cost, 2)
        context['total_pnl'] = round(total_pnl, 2)
        context['total_pnl_pct'] = round((total_pnl / total_cost * 100) if total_cost else 0, 2)
        context['total_pnl_positive'] = total_pnl >= 0
        allocation = []
        for item in portfolio_items:
            if total_value > 0:
                pct = round((item['current_value'] / total_value) * 100, 1)
            else:
                pct = 0
            allocation.append({
                'symbol': item['symbol'],
                'name': item['name'],
                'value': item['current_value'],
                'pct': pct,
                'color': None,
            })
        colors = ['#56B6C6','#ffc800','#00c896','#ff6464','#8b5cf6','#f59e0b','#3b82f6','#ec4899','#14b8a6','#f97316']
        for i, a in enumerate(allocation):
            a['color'] = colors[i % len(colors)]
        context['allocation_json'] = json.dumps(allocation, cls=NumpyEncoder)
        first_mkt = positions[0].get('market', 'US') if positions else 'US'
        if first_mkt == 'ID':
            context['chart_symbol'] = f"IDX:{first_symbol}"
        else:
            context['chart_symbol'] = first_symbol
    return render(request, 'alerts/portfolios.html', context)


def dashboard(request):
    watchlist_items = []
    recent_searches = []
    portfolio_items = []

    if request.user.is_authenticated:
        uid = request.user.pk

        saved = get_watchlist(uid)
        positions = get_portfolio(uid)

        all_pairs = [(item['symbol'], item.get('market', 'US')) for item in saved]
        all_pairs += [(pos['symbol'], pos.get('market', 'US')) for pos in positions]
        stock_data = batch_stock_data(all_pairs) if all_pairs else {}

        for item in saved:
            data = stock_data.get(item['symbol'], {'name': item['symbol'], 'price': '-', 'change': 0, 'is_positive': True})
            watchlist_items.append({
                'symbol': item['symbol'], 'market': item.get('market', 'US'),
                'name': data.get('name', item['symbol']),
                'price': data.get('price', '-'),
                'change': data.get('change', 0),
                'is_positive': data.get('is_positive', True),
            })

        recent_searches = get_search_history(uid, limit=6)

        total_value = 0
        total_cost = 0
        total_pnl = 0
        for pos in positions:
            data = stock_data.get(pos['symbol'], {})
            current_price = data.get('current_price', 0)
            buy_price = float(pos['buy_price'])
            qty = float(pos['quantity'])
            cost_basis = buy_price * qty
            current_value = current_price * qty
            pnl = current_value - cost_basis
            pnl_pct = (pnl / cost_basis * 100) if cost_basis else 0
            portfolio_items.append({
                'id': pos['id'],
                'symbol': pos['symbol'], 'market': pos.get('market', 'US'),
                'name': pos.get('company_name', '') or data.get('name', pos['symbol']),
                'quantity': qty, 'buy_price': buy_price,
                'current_price': round(current_price, 2),
                'current_value': round(current_value, 2),
                'pnl': round(pnl, 2),
                'pnl_pct': round(pnl_pct, 2),
                'is_positive': pnl >= 0,
            })
            total_value += current_value
            total_cost += cost_basis
            total_pnl += pnl

    try:
        gauges = get_dashboard_gauges()
    except Exception:
        gauges = [
            {'label': 'Growth', 'value': 50, 'color': '#ffc800', 'dash': 50},
            {'label': 'Quality', 'value': 50, 'color': '#ffc800', 'dash': 50},
            {'label': 'Value', 'value': 50, 'color': '#ffc800', 'dash': 50},
            {'label': 'Momentum', 'value': 50, 'color': '#ffc800', 'dash': 50},
            {'label': 'Risk Shield', 'value': 50, 'color': '#ffc800', 'dash': 50},
        ]

    try:
        key_stats = get_dashboard_key_stats()
    except Exception:
        key_stats = [
            {'label': 'Fwd P/E', 'value': '-'},
            {'label': 'Div Yield', 'value': '-'},
            {'label': 'Rev Growth', 'value': '-'},
            {'label': '1D', 'value': '-'},
            {'label': '1M', 'value': '-'},
        ]

    try:
        returns_raw = get_returns_data()
        returns_data = {}
        for pk, pv in returns_raw.items():
            top_list = []
            for t in pv.get('top', []):
                top_list.append({'symbol': t['symbol'], 'name': t['name'], 'pct': t['pct']})
            bot_list = []
            for b in pv.get('bottom', []):
                bot_list.append({'symbol': b['symbol'], 'name': b['name'], 'pct': b['pct']})
            returns_data[pk] = {'top': top_list, 'bottom': bot_list}
        top_returns = returns_data.get('1W', {}).get('top', [])
        bottom_returns = returns_data.get('1W', {}).get('bottom', [])
    except Exception:
        returns_data = {
            '1W': {'top': [], 'bottom': []},
            '1M': {'top': [], 'bottom': []},
            '3M': {'top': [], 'bottom': []},
            'YTD': {'top': [], 'bottom': []},
            '1Y': {'top': [], 'bottom': []},
        }
        top_returns = []
        bottom_returns = []

    try:
        top_rated = get_top_rated()
    except Exception:
        top_rated = []

    try:
        trending_portfolios = get_trending_portfolios()
    except Exception:
        trending_portfolios = []

    try:
        strategy_picks = get_strategy_picks()
    except Exception:
        strategy_picks = {}

    return render(request, 'alerts/dashboard.html', {
        'watchlist_items': watchlist_items,
        'recent_searches': recent_searches,
        'portfolio_items': portfolio_items,
        'gauges': gauges,
        'key_stats': key_stats,
        'top_returns': top_returns,
        'bottom_returns': bottom_returns,
        'returns_data_json': json.dumps(returns_data, cls=NumpyEncoder),
        'top_rated': top_rated,
        'trending_portfolios': trending_portfolios,
        'strategy_picks_json': json.dumps(strategy_picks, cls=NumpyEncoder),
    })


@login_required
def screener(request):
    symbol = request.GET.get('symbol', 'NVDA')
    market = request.GET.get('market', 'US')

    analysis = None
    in_watchlist = False
    if symbol:
        process_symbol = symbol.upper().strip()
        if market == 'ID' and not process_symbol.endswith('.JK'):
            process_symbol += '.JK'

        analysis = get_fundamental_analysis(process_symbol)

        if analysis and 'error' not in analysis:
            tv_symbol = process_symbol.replace('.JK', '')
            if market == 'ID' or process_symbol.endswith('.JK'):
                tv_symbol = f"IDX:{tv_symbol}"
            analysis['tv_symbol'] = tv_symbol

            if request.user.is_authenticated:
                clean_symbol = symbol.upper().strip().replace('.JK', '')
                add_search_history(request.user.pk, clean_symbol, market, analysis.get('company_name', ''))

        if request.user.is_authenticated:
            clean_symbol = symbol.upper().strip().replace('.JK', '')
            in_watchlist = check_in_watchlist(request.user.pk, clean_symbol)

    sector = ''
    if analysis and 'error' not in analysis and analysis.get('metrics'):
        sector = analysis['metrics'].get('Sector', '')

    return render(request, 'alerts/screener.html', {
        'symbol': symbol.replace('.JK', ''),
        'market': market,
        'analysis': analysis,
        'in_watchlist': in_watchlist,
        'sector': sector,
    })


@login_required
def compare(request):
    symbol1 = request.GET.get('s1', '').upper().strip()
    symbol2 = request.GET.get('s2', '').upper().strip()
    market1 = request.GET.get('m1', 'US')
    market2 = request.GET.get('m2', 'US')

    analysis1 = None
    analysis2 = None

    if symbol1:
        proc1 = symbol1 + '.JK' if market1 == 'ID' and not symbol1.endswith('.JK') else symbol1
        analysis1 = get_fundamental_analysis(proc1)
        if analysis1 and 'error' not in analysis1:
            tv1 = proc1.replace('.JK', '')
            analysis1['tv_symbol'] = f"IDX:{tv1}" if market1 == 'ID' else tv1

    if symbol2:
        proc2 = symbol2 + '.JK' if market2 == 'ID' and not symbol2.endswith('.JK') else symbol2
        analysis2 = get_fundamental_analysis(proc2)
        if analysis2 and 'error' not in analysis2:
            tv2 = proc2.replace('.JK', '')
            analysis2['tv_symbol'] = f"IDX:{tv2}" if market2 == 'ID' else tv2

    return render(request, 'alerts/compare.html', {
        's1': symbol1, 's2': symbol2,
        'm1': market1, 'm2': market2,
        'analysis1': analysis1, 'analysis2': analysis2,
    })


@login_required
@require_POST
def toggle_watchlist(request):
    symbol = request.POST.get('symbol', '').upper().strip().replace('.JK', '')
    market = request.POST.get('market', 'US')
    if not symbol:
        return JsonResponse({'error': 'Symbol is required'}, status=400)
    result = fw_toggle_watchlist(request.user.pk, symbol, market)
    return JsonResponse({'status': result, 'symbol': symbol})


@login_required
@require_POST
def portfolio_add(request):
    symbol = request.POST.get('symbol', '').upper().strip().replace('.JK', '')
    market = request.POST.get('market', 'US')
    quantity = request.POST.get('quantity', '0')
    buy_price = request.POST.get('buy_price', '0')
    company_name = request.POST.get('company_name', '')

    if not symbol:
        return redirect('portfolios')
    try:
        qty_dec = decimal.Decimal(quantity)
        price_dec = decimal.Decimal(buy_price)
        if qty_dec <= 0 or price_dec <= 0:
            return redirect('portfolios')
        add_portfolio(request.user.pk, symbol, market, company_name, qty_dec, price_dec)
    except (decimal.InvalidOperation, ValueError) as e:
        logger.warning(f"Invalid portfolio input for {symbol}: {e}")
    except Exception as e:
        logger.error(f"Failed to add portfolio position for {symbol}: {e}")
    return redirect('portfolios')


@login_required
@require_POST
def portfolio_remove(request, pk):
    remove_portfolio(request.user.pk, pk)
    return redirect('portfolios')


def prices_api(request):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'auth required'}, status=401)
    symbols_param = request.GET.get('symbols', '')
    markets_param = request.GET.get('markets', '')
    if not symbols_param:
        return JsonResponse({'prices': {}})
    symbols = [s.strip().upper() for s in symbols_param.split(',') if s.strip()]
    markets = [m.strip() for m in markets_param.split(',')] if markets_param else ['US'] * len(symbols)
    while len(markets) < len(symbols):
        markets.append('US')
    pairs = list(zip(symbols, markets[:len(symbols)]))

    # Cache by sorted pair list so order-different requests share results.
    from django.core.cache import cache
    cache_key = 'prices:' + ','.join(sorted(f'{s}:{m}' for s, m in pairs))
    cached = cache.get(cache_key)
    if cached is not None:
        return JsonResponse({'prices': cached})

    stock_data = batch_stock_data(pairs)
    prices = {}
    for sym in symbols:
        d = stock_data.get(sym, {})
        if d:
            prices[sym] = {
                'name': d.get('name', sym),
                'price': d.get('price', '-'),
                'change': d.get('change', 0),
                'is_positive': d.get('is_positive', True),
                'current_price': d.get('current_price', 0),
            }
    # 25s TTL — slightly less than client refresh interval to keep prices fresh
    # while still cutting most yfinance round-trips.
    cache.set(cache_key, prices, timeout=25)
    return JsonResponse({'prices': prices})


def symbol_search(request):
    """Lightweight symbol search for autocomplete dropdowns.

    Searches known SP500 + IDX symbol lists. Names come from the radar score
    cache when available (no extra network call); otherwise the symbol itself
    is shown. Capped at 10 results, debounced on the client side.
    """
    from django.core.cache import cache
    q = (request.GET.get('q', '') or '').strip().upper()
    if len(q) < 1:
        return JsonResponse({'results': []})

    # Build a name lookup table from any radar-scores payloads currently cached.
    # This piggybacks on data already paid for; no extra yfinance calls.
    name_map = {}
    for market in ('US', 'ID'):
        for size in (25, 50, 75, 100):
            payload = cache.get(f'radar_scores:{market}::') or cache.get(f'radar_scores:{market}:{size}:')
            if payload and payload.get('stocks'):
                for s in payload['stocks']:
                    if s.get('t') and s.get('n'):
                        name_map.setdefault(s['t'], s['n'])

    results = []
    seen = set()
    # Match against ticker first (prefix preferred), then name.
    candidates = []
    for sym in SP500_SYMBOLS:
        candidates.append((sym, 'US'))
    for sym in IDX_SYMBOLS:
        candidates.append((sym.replace('.JK', ''), 'ID'))

    # Prefix matches first
    prefix_hits = []
    name_hits = []
    other_hits = []
    for sym, market in candidates:
        if sym in seen:
            continue
        seen.add(sym)
        name = name_map.get(sym, '')
        if sym.startswith(q):
            prefix_hits.append((sym, market, name))
        elif q in sym:
            other_hits.append((sym, market, name))
        elif name and q in name.upper():
            name_hits.append((sym, market, name))

    for sym, market, name in (prefix_hits + name_hits + other_hits)[:10]:
        results.append({'symbol': sym, 'market': market, 'name': name})

    return JsonResponse({'results': results, 'query': q})


def indices_api(request):
    """Public endpoint that returns live quotes for the dashboard index strip.
    Symbols are hard-coded since they are part of the page chrome, not user input."""
    from django.core.cache import cache
    cached = cache.get('indices:dashboard')
    if cached is not None:
        return JsonResponse(cached)

    # SPY = S&P 500 ETF, QQQ = Nasdaq 100 ETF, DIA = Dow 30 ETF,
    # BTC-USD = Bitcoin USD, ^TNX = 10Y Treasury yield index.
    symbols = ['SPY', 'QQQ', 'DIA', 'BTC-USD', '^TNX']
    pairs = [(s, 'US') for s in symbols]
    data = batch_stock_data(pairs)
    out = {}
    for s in symbols:
        d = data.get(s) or {}
        price_str = d.get('price', '-')
        # ^TNX is reported as 43.0 meaning 4.30% — divide by 10 and append %.
        if s == '^TNX':
            raw = d.get('current_price') or d.get('price_raw') or 0
            try:
                pct = float(raw) / 10.0
                price_str = f'{pct:.2f}%'
            except (TypeError, ValueError):
                price_str = '-'
        out[s] = {
            'price': price_str,
            'change': d.get('change', 0),
            'is_positive': d.get('is_positive', True),
        }
    payload = {'indices': out}
    cache.set('indices:dashboard', payload, timeout=30)
    return JsonResponse(payload)


def market_status(request):
    from datetime import datetime as dt, timedelta
    import pytz
    try:
        eastern = pytz.timezone('US/Eastern')
        now_et = dt.now(eastern)
        is_weekday = now_et.weekday() < 5
        market_open_time = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
        market_close_time = now_et.replace(hour=16, minute=0, second=0, microsecond=0)
        is_open = is_weekday and market_open_time <= now_et <= market_close_time
        next_open = None
        if not is_open:
            if now_et < market_open_time and is_weekday:
                next_open = int((market_open_time - now_et).total_seconds())
            else:
                for days_ahead in range(1, 7):
                    next_day = now_et + timedelta(days=days_ahead)
                    if next_day.weekday() < 5:
                        next_open = int(((next_day.replace(hour=9, minute=30, second=0, microsecond=0) - now_et).total_seconds()))
                        break
        return JsonResponse({'is_open': is_open, 'next_open_seconds': next_open})
    except Exception:
        return JsonResponse({'is_open': False})


@login_required
def alert_list(request):
    from .models import PriceAlert
    alerts = PriceAlert.objects.filter(user=request.user, is_active=True).order_by('-created_at')
    uid = request.user.pk
    saved = get_watchlist(uid)
    pairs = [(item['symbol'], item.get('market', 'US')) for item in saved]
    stock_data = batch_stock_data(pairs) if pairs else {}
    watchlist_items = []
    for item in saved:
        data = stock_data.get(item['symbol'], {'name': item['symbol'], 'price': '-', 'change': 0, 'is_positive': True})
        watchlist_items.append({
            'symbol': item['symbol'], 'market': item.get('market', 'US'),
            'name': data.get('name', item['symbol']),
            'price': data.get('price', '-'),
            'change': data.get('change', 0),
            'is_positive': data.get('is_positive', True),
        })
    return render(request, 'alerts/watchtower.html', {
        'watchlist_items': watchlist_items,
        'alerts': alerts,
    })


@login_required
@require_POST
def alert_create(request):
    from .models import PriceAlert
    symbol = request.POST.get('symbol', '').upper().strip().replace('.JK', '')
    market = request.POST.get('market', 'US')
    condition = request.POST.get('condition', 'above')
    target_price = request.POST.get('target_price', '0')
    if not symbol or condition not in dict(PriceAlert.CONDITION_CHOICES):
        return redirect('watchtower')
    try:
        PriceAlert.objects.create(
            user=request.user,
            symbol=symbol,
            market=market,
            condition=condition,
            target_price=decimal.Decimal(target_price),
        )
    except (decimal.InvalidOperation, ValueError):
        pass
    return redirect('watchtower')


@login_required
@require_POST
def alert_delete(request, pk):
    from .models import PriceAlert
    try:
        alert = PriceAlert.objects.get(pk=pk, user=request.user)
        alert.delete()
    except PriceAlert.DoesNotExist:
        pass
    return redirect('watchtower')


@login_required
def portfolio_export_csv(request):
    import csv
    from django.http import HttpResponse
    positions = get_portfolio(request.user.pk)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="portfolio.csv"'
    writer = csv.writer(response)
    writer.writerow(['Symbol', 'Market', 'Company Name', 'Quantity', 'Buy Price'])
    for pos in positions:
        writer.writerow([pos['symbol'], pos['market'], pos.get('company_name', ''), pos['quantity'], pos['buy_price']])
    return response


@login_required
@require_POST
def portfolio_import_csv(request):
    import csv
    from io import StringIO
    csv_file = request.FILES.get('csv_file')
    if not csv_file or not csv_file.name.endswith('.csv'):
        return redirect('portfolios')
    try:
        decoded = csv_file.read().decode('utf-8')
        reader = csv.DictReader(StringIO(decoded))
        count = 0
        for row in reader:
            symbol = row.get('Symbol', row.get('symbol', '')).strip().upper().replace('.JK', '')
            market = row.get('Market', row.get('market', 'US')).strip()
            company_name = row.get('Company Name', row.get('company_name', row.get('name', ''))).strip()
            qty_str = row.get('Quantity', row.get('quantity', '0')).strip()
            price_str = row.get('Buy Price', row.get('buy_price', row.get('price', '0'))).strip()
            if not symbol:
                continue
            try:
                qty = decimal.Decimal(qty_str)
                price = decimal.Decimal(price_str)
                if qty > 0 and price > 0:
                    add_portfolio(request.user.pk, symbol, market, company_name, qty, price)
                    count += 1
            except (decimal.InvalidOperation, ValueError):
                continue
    except Exception as e:
        logger.error(f"CSV import error: {e}")
    return redirect('portfolios')


@login_required
def watchlist_export_csv(request):
    import csv
    from django.http import HttpResponse
    items = get_watchlist(request.user.pk)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="watchlist.csv"'
    writer = csv.writer(response)
    writer.writerow(['Symbol', 'Market'])
    for item in items:
        writer.writerow([item['symbol'], item.get('market', 'US')])
    return response


@login_required
@require_POST
def portfolio_edit(request, pk):
    from .models import PortfolioItem
    try:
        item = PortfolioItem.objects.get(pk=pk, user=request.user)
        qty = request.POST.get('quantity')
        price = request.POST.get('buy_price')
        if qty:
            item.quantity = decimal.Decimal(qty)
        if price:
            item.buy_price = decimal.Decimal(price)
        item.save()
    except (PortfolioItem.DoesNotExist, decimal.InvalidOperation, ValueError):
        pass
    return redirect('portfolios')


def broker_summary(request):
    broker_data = get_broker_summary()
    return render(request, 'alerts/broker_summary.html', {
        'broker_data': broker_data,
    })


def broker_summary_api(request):
    data = get_broker_summary()
    return JsonResponse(json.loads(json.dumps(data, cls=NumpyEncoder)))


def sector_peers_api(request):
    market = request.GET.get('market', 'US')
    sector = request.GET.get('sector', '').strip()
    exclude = request.GET.get('exclude', '').strip().upper()
    if not sector:
        return JsonResponse({'peers': []})
    symbols = SP500_SYMBOLS if market == 'US' else IDX_SYMBOLS
    try:
        limit = min(max(int(request.GET.get('limit', 8)), 1), 20)
    except (TypeError, ValueError):
        limit = 8

    # Sector composition is relatively stable. Cache 10 minutes.
    from django.core.cache import cache
    cache_key = f'sector_peers:{market}:{sector.lower()}:{exclude}:{limit}'
    cached = cache.get(cache_key)
    if cached is not None:
        return JsonResponse(cached)

    def fetch():
        results = []
        for sym in symbols:
            sym_clean = sym.replace('.JK', '').upper()
            if sym_clean == exclude:
                continue
            try:
                info = _safe_info(sym, ['shortName', 'sector', 'industry', 'marketCap',
                    'revenueGrowth', 'returnOnEquity', 'trailingPE', 'forwardPE',
                    'revenueGrowthQuarterly', 'earningsGrowth', 'profitMargins',
                    'priceToBook', 'beta'])
                if not info or not info.get('shortName'):
                    continue
                sym_sector = (info.get('sector') or '').strip().lower()
                if sector.lower() not in sym_sector and sym_sector not in sector.lower():
                    continue
                scores = compute_score(info)
                results.append({
                    'ticker': sym_clean,
                    'name': info.get('shortName', '')[:25],
                    'sector': info.get('sector', ''),
                    'industry': info.get('industry', ''),
                    'mcap': _fmt_mcap(info.get('marketCap')),
                    'scores': scores,
                })
            except Exception:
                continue
        results.sort(key=lambda x: x['scores']['score'], reverse=True)
        return results[:limit]

    cache_key_internal = f'peers_{market}_{sector}_{exclude}'
    results = _get_cached(cache_key_internal, fetch, ttl=SCORES_CACHE_TTL)
    payload = {'peers': results}
    cache.set(cache_key, payload, timeout=600)
    return JsonResponse(payload)


# === SEO and ops endpoints ===

def robots_txt(request):
    """Tells search-engine crawlers what to index. Disallows API and auth pages."""
    from django.http import HttpResponse
    lines = [
        'User-agent: *',
        'Disallow: /api/',
        'Disallow: /login/',
        'Disallow: /register/',
        'Disallow: /logout/',
        'Disallow: /portfolio/',
        'Disallow: /watchtower/',
        'Disallow: /alerts/',
        'Allow: /',
        '',
        f'Sitemap: {request.scheme}://{request.get_host()}/sitemap.xml',
    ]
    return HttpResponse('\n'.join(lines), content_type='text/plain; charset=utf-8')


def sitemap_xml(request):
    """Static sitemap covering public pages plus a curated set of popular tickers."""
    from django.http import HttpResponse
    from django.urls import reverse
    base = f'{request.scheme}://{request.get_host()}'
    public_pages = [
        ('dashboard', 'daily', '1.0'),
        ('radar', 'daily', '0.9'),
        ('compare', 'weekly', '0.8'),
        ('maps', 'daily', '0.8'),
        ('headlines', 'hourly', '0.7'),
        ('about', 'monthly', '0.5'),
    ]
    urls = []
    for name, freq, prio in public_pages:
        try:
            urls.append((base + reverse(name), freq, prio))
        except Exception:
            continue
    # Popular tickers — useful for indexing per-stock pages.
    popular = ['NVDA', 'AAPL', 'MSFT', 'GOOGL', 'META', 'AMZN', 'TSLA',
               'AMD', 'INTC', 'JPM', 'BBCA', 'BBRI', 'TLKM', 'ASII']
    for sym in popular:
        market = 'ID' if sym in ('BBCA', 'BBRI', 'TLKM', 'ASII') else 'US'
        urls.append((f'{base}{reverse("screener")}?symbol={sym}&market={market}', 'daily', '0.6'))
    body = ['<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for loc, freq, prio in urls:
        body.append(f'  <url><loc>{loc}</loc><changefreq>{freq}</changefreq><priority>{prio}</priority></url>')
    body.append('</urlset>')
    return HttpResponse('\n'.join(body), content_type='application/xml; charset=utf-8')


def healthz(request):
    """Liveness probe for monitoring. Returns 200 with minimal info; no DB queries."""
    return JsonResponse({'status': 'ok', 'service': 'axiom-alpha'})


def service_worker(request):
    """Serve the service worker from the site root so it can control the whole origin.

    A SW served from /static/alerts/sw.js would be limited to that path; serving
    from /sw.js (or with Service-Worker-Allowed header) lets it scope to "/".
    """
    from django.http import HttpResponse
    from django.contrib.staticfiles import finders
    path = finders.find('alerts/sw.js')
    if not path:
        return HttpResponse('// service worker not found', status=404, content_type='application/javascript')
    with open(path, 'rb') as f:
        content = f.read()
    resp = HttpResponse(content, content_type='application/javascript')
    resp['Service-Worker-Allowed'] = '/'
    resp['Cache-Control'] = 'no-cache'
    return resp