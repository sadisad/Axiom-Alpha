from django.shortcuts import render, redirect
from django.contrib.auth import login, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.views.decorators.http import require_POST

from django import forms
from .services.valuation import get_fundamental_analysis
from .models import WatchlistItem, SearchHistory, PortfolioItem
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

    gauges = [
        {'label': 'Growth', 'value': 80, 'color': '#00c896', 'dash': 80},
        {'label': 'Quality', 'value': 83, 'color': '#00c896', 'dash': 83},
        {'label': 'Value', 'value': 23, 'color': '#ff6464', 'dash': 23},
        {'label': 'Momentum', 'value': 75, 'color': '#00c896', 'dash': 75},
        {'label': 'Risk Shield', 'value': 54, 'color': '#ffc800', 'dash': 54},
    ]

    key_stats = [
        {'label': 'Fwd P/E', 'value': '26.0x'},
        {'label': 'Div Yield', 'value': '0.5%'},
        {'label': 'Rev Growth', 'value': '+15.8%'},
        {'label': '1W', 'value': '+1.3%'},
        {'label': '1M', 'value': '+11.9%'},
    ]

    top_returns = [
        {'symbol': 'MU', 'name': 'Micron', 'pct': '38'},
        {'symbol': 'SNDK', 'name': 'SanDisk Corp', 'pct': '32'},
        {'symbol': 'QCOM', 'name': 'Qualcomm', 'pct': '24'},
        {'symbol': 'GLW', 'name': 'Corning', 'pct': '18'},
        {'symbol': 'ORCL', 'name': 'Oracle', 'pct': '14'},
        {'symbol': 'AMAT', 'name': 'Applied M', 'pct': '12'},
    ]

    bottom_returns = [
        {'symbol': 'BMY', 'name': 'Bristol-My', 'pct': '-4'},
        {'symbol': 'BAC', 'name': 'BofA', 'pct': '-4'},
        {'symbol': 'PLTR', 'name': 'Palantir', 'pct': '-4'},
        {'symbol': 'CVX', 'name': 'Chevron', 'pct': '-5'},
        {'symbol': 'WFC', 'name': 'Wells Farg', 'pct': '-6'},
        {'symbol': 'COP', 'name': 'ConocoPh', 'pct': '-8'},
    ]

    def sc(v):
        if v >= 80: return ('rgba(0,200,150,0.18)', '#00c896')
        if v >= 50: return ('rgba(255,200,0,0.15)', '#ffc800')
        return ('rgba(239,68,68,0.12)', '#ff6464')

    top_rated = []
    for t, n, m, g, q, v, mo, r, s in [
        ('MU','Micron',842,95,97,67,99,26,98),
        ('NVDA','Nvidia',5228,99,100,28,97,97,97),
        ('V','Visa',601,76,100,32,18,92,96),
        ('MSFT','Microsoft',3084,97,99,32,44,70,96),
        ('MA','Mastercard',438,77,100,27,26,92,96),
        ('NEM','Newmont',324,56,98,84,62,61,96),
        ('GOOGL','Alphabet',4836,95,99,19,18,69,95),
        ('CRM','Salesforce',149,74,88,40,17,57,93),
        ('META','Meta',1547,91,44,18,49,95,93),
        ('PGR','Progressive',113,55,88,67,25,92,54),
    ]:
        gb,gf = sc(g); qb,qf = sc(q); vb,vf = sc(v); mb,mf = sc(mo); rb,rf = sc(r)
        top_rated.append({
            'ticker':t,'name':n,'mcap':f"{m:,}",'growth':g,'quality':q,'value':v,'mom':mo,'risk':r,'score':s,
            'growth_bg':gb,'growth_fg':gf,'quality_bg':qb,'quality_fg':qf,
            'value_bg':vb,'value_fg':vf,'mom_bg':mb,'mom_fg':mf,'risk_bg':rb,'risk_fg':rf,
        })

    trending_portfolios = [
        {'name':'US MidCaps Growth','w1':'-6.8%','m1':'+33.2%','ytd':'+35.7%','y1':'+175.8%','w1_pos':False,'m1_pos':True,'ytd_pos':True,'y1_pos':True},
        {'name':'Global Growth','w1':'+7.2%','m1':'+38.0%','ytd':'+29.9%','y1':'+136.0%','w1_pos':True,'m1_pos':True,'ytd_pos':True,'y1_pos':True},
        {'name':'US Growth Rockets','w1':'-6.5%','m1':'+85.5%','ytd':'+54.8%','y1':'+105.1%','w1_pos':False,'m1_pos':True,'ytd_pos':True,'y1_pos':True},
        {'name':'US Smart Value','w1':'+1.3%','m1':'+15.4%','ytd':'+16.2%','y1':'+27.9%','w1_pos':True,'m1_pos':True,'ytd_pos':True,'y1_pos':True},
        {'name':'Global GEAR+','w1':'-0.5%','m1':'+11.4%','ytd':'-3.8%','y1':'+40.5%','w1_pos':False,'m1_pos':True,'ytd_pos':False,'y1_pos':True},
    ]

    return render(request, 'alerts/dashboard.html', {
        'watchlist_items': watchlist_items,
        'recent_searches': recent_searches,
        'portfolio_items': portfolio_items,
        'gauges': gauges,
        'key_stats': key_stats,
        'top_returns': top_returns,
        'bottom_returns': bottom_returns,
        'top_rated': top_rated,
        'trending_portfolios': trending_portfolios,
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