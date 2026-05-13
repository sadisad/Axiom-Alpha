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
)
from .firebase_db import (
    get_watchlist, toggle_watchlist as fw_toggle_watchlist, check_in_watchlist,
    add_search_history, get_search_history,
    get_portfolio, add_portfolio, remove_portfolio,
)
import yfinance as yf
import json
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
    if request.method == 'POST':
        form = LoginForm(request.POST, request=request)
        if form.is_valid():
            user = form.cleaned_data['user']
            login(request, user)
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
    size = min(int(request.GET.get('size', 25)), 100)
    list_key = request.GET.get('list', '')
    if list_key and list_key in STOCK_LISTS:
        symbols = STOCK_LISTS[list_key]['symbols'][:100]
    elif market == 'ID':
        symbols = IDX_SYMBOLS[:size]
    else:
        symbols = SP500_SYMBOLS[:size]
    try:
        scores = get_market_scores(symbols, market)
        return JsonResponse({'stocks': scores, 'market': market, 'size': len(symbols)})
    except Exception as e:
        return JsonResponse({'stocks': [], 'market': market, 'error': str(e)})


def stock_lists(request):
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
    return JsonResponse({'groups': result})


def headlines(request):
    return render(request, 'alerts/headlines.html')


def watchtower(request):
    context = {}
    if request.user.is_authenticated:
        uid = request.user.pk
        watchlist_items = []
        saved = get_watchlist(uid)
        for item in saved:
            try:
                process_sym = item['symbol']
                if item.get('market') == 'ID' and not process_sym.endswith('.JK'):
                    process_sym += '.JK'
                info = yf.Ticker(process_sym).info
                price = info.get('currentPrice', info.get('regularMarketPrice', 0))
                prev_close = info.get('previousClose', price)
                change = ((price - prev_close) / prev_close * 100) if prev_close and price else 0
                watchlist_items.append({
                    'symbol': item['symbol'], 'market': item.get('market', 'US'),
                    'name': info.get('shortName', item['symbol']),
                    'price': f"{price:,.2f}" if price else '-',
                    'change': round(change, 2),
                    'is_positive': change >= 0,
                })
            except Exception:
                watchlist_items.append({
                    'symbol': item['symbol'], 'market': item.get('market', 'US'),
                    'name': item['symbol'], 'price': '-', 'change': 0, 'is_positive': True,
                })
        context['watchlist_items'] = watchlist_items
    return render(request, 'alerts/watchtower.html', context)


def portfolios(request):
    context = {}
    if request.user.is_authenticated:
        uid = request.user.pk
        portfolio_items = []
        total_value = 0
        total_cost = 0
        total_pnl = 0
        first_symbol = 'SPY'
        positions = get_portfolio(uid)
        for idx, pos in enumerate(positions):
            try:
                process_sym = pos['symbol']
                if pos.get('market') == 'ID' and not process_sym.endswith('.JK'):
                    process_sym += '.JK'
                info = yf.Ticker(process_sym).info
                current_price = info.get('currentPrice', info.get('regularMarketPrice', 0)) or 0
                buy_price = float(pos['buy_price'])
                qty = float(pos['quantity'])
                cost_basis = buy_price * qty
                current_value = current_price * qty
                pnl = current_value - cost_basis
                pnl_pct = (pnl / cost_basis * 100) if cost_basis else 0
                portfolio_items.append({
                    'id': pos['id'],
                    'symbol': pos['symbol'], 'market': pos.get('market', 'US'),
                    'name': pos.get('company_name', '') or info.get('shortName', pos['symbol']),
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
            except Exception:
                portfolio_items.append({
                    'id': pos['id'],
                    'symbol': pos['symbol'], 'market': pos.get('market', 'US'),
                    'name': pos.get('company_name', '') or pos['symbol'],
                    'quantity': float(pos['quantity']), 'buy_price': float(pos['buy_price']),
                    'current_price': 0, 'current_value': 0,
                    'cost_basis': float(pos['quantity']) * float(pos['buy_price']),
                    'pnl': 0, 'pnl_pct': 0, 'is_positive': True,
                })
                total_cost += float(pos['quantity']) * float(pos['buy_price'])
                if idx == 0:
                    first_symbol = pos['symbol']
        context['portfolio_items'] = portfolio_items
        context['total_value'] = round(total_value, 2)
        context['total_cost'] = round(total_cost, 2)
        context['total_pnl'] = round(total_pnl, 2)
        context['total_pnl_pct'] = round((total_pnl / total_cost * 100) if total_cost else 0, 2)
        context['total_pnl_positive'] = total_pnl >= 0
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
        for item in saved:
            try:
                process_sym = item['symbol']
                if item.get('market') == 'ID' and not process_sym.endswith('.JK'):
                    process_sym += '.JK'
                info = yf.Ticker(process_sym).info
                price = info.get('currentPrice', info.get('regularMarketPrice', 0))
                prev_close = info.get('previousClose', price)
                change = ((price - prev_close) / prev_close * 100) if prev_close and price else 0
                watchlist_items.append({
                    'symbol': item['symbol'], 'market': item.get('market', 'US'),
                    'name': info.get('shortName', item['symbol']),
                    'price': f"{price:,.2f}" if price else '-',
                    'change': round(change, 2),
                    'is_positive': change >= 0,
                })
            except Exception:
                watchlist_items.append({
                    'symbol': item['symbol'], 'market': item.get('market', 'US'),
                    'name': item['symbol'], 'price': '-', 'change': 0, 'is_positive': True,
                })

        recent_searches = get_search_history(uid, limit=6)

        positions = get_portfolio(uid)
        for pos in positions:
            try:
                process_sym = pos['symbol']
                if pos.get('market') == 'ID' and not process_sym.endswith('.JK'):
                    process_sym += '.JK'
                info = yf.Ticker(process_sym).info
                current_price = info.get('currentPrice', info.get('regularMarketPrice', 0)) or 0
                buy_price = float(pos['buy_price'])
                qty = float(pos['quantity'])
                cost_basis = buy_price * qty
                current_value = current_price * qty
                pnl = current_value - cost_basis
                pnl_pct = (pnl / cost_basis * 100) if cost_basis else 0
                portfolio_items.append({
                    'id': pos['id'],
                    'symbol': pos['symbol'], 'market': pos.get('market', 'US'),
                    'name': pos.get('company_name', '') or info.get('shortName', pos['symbol']),
                    'quantity': qty, 'buy_price': buy_price,
                    'current_price': round(current_price, 2),
                    'current_value': round(current_value, 2),
                    'pnl': round(pnl, 2),
                    'pnl_pct': round(pnl_pct, 2),
                    'is_positive': pnl >= 0,
                })
            except Exception:
                portfolio_items.append({
                    'id': pos['id'],
                    'symbol': pos['symbol'], 'market': pos.get('market', 'US'),
                    'name': pos.get('company_name', '') or pos['symbol'],
                    'quantity': float(pos['quantity']), 'buy_price': float(pos['buy_price']),
                    'current_price': 0, 'current_value': 0,
                    'pnl': 0, 'pnl_pct': 0, 'is_positive': True,
                })

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

    return render(request, 'alerts/screener.html', {
        'symbol': symbol.replace('.JK', ''),
        'market': market,
        'analysis': analysis,
        'in_watchlist': in_watchlist,
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

    try:
        add_portfolio(
            request.user.pk, symbol, market, company_name,
            decimal.Decimal(quantity), decimal.Decimal(buy_price),
        )
    except Exception:
        pass
    return redirect('dashboard')


@login_required
@require_POST
def portfolio_remove(request, pk):
    remove_portfolio(request.user.pk, pk)
    return redirect('dashboard')