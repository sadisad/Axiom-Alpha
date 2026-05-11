from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse, HttpResponse
from django.views.decorators.http import require_POST
from .services.valuation import get_fundamental_analysis
from .models import Watchlist, SearchHistory, Portfolio
import yfinance as yf
import decimal


def maps(request):
    return render(request, 'alerts/maps.html')


def dashboard(request):
    watchlist_items = []
    recent_searches = []
    portfolio_items = []

    if request.user.is_authenticated:
        # --- Watchlist ---
        saved = Watchlist.objects.filter(user=request.user)
        for item in saved:
            try:
                process_sym = item.symbol
                if item.market == 'ID' and not process_sym.endswith('.JK'):
                    process_sym += '.JK'
                info = yf.Ticker(process_sym).info
                price = info.get('currentPrice', info.get('regularMarketPrice', 0))
                prev_close = info.get('previousClose', price)
                change = ((price - prev_close) / prev_close * 100) if prev_close and price else 0
                watchlist_items.append({
                    'symbol': item.symbol, 'market': item.market,
                    'name': info.get('shortName', item.symbol),
                    'price': f"{price:,.2f}" if price else '-',
                    'change': round(change, 2),
                    'is_positive': change >= 0,
                })
            except Exception:
                watchlist_items.append({
                    'symbol': item.symbol, 'market': item.market,
                    'name': item.symbol, 'price': '-', 'change': 0, 'is_positive': True,
                })

        # --- Recent Searches ---
        seen = set()
        for s in SearchHistory.objects.filter(user=request.user)[:20]:
            if s.symbol not in seen:
                seen.add(s.symbol)
                recent_searches.append(s)
                if len(recent_searches) >= 6:
                    break

        # --- Portfolio ---
        for pos in Portfolio.objects.filter(user=request.user):
            try:
                process_sym = pos.symbol
                if pos.market == 'ID' and not process_sym.endswith('.JK'):
                    process_sym += '.JK'
                info = yf.Ticker(process_sym).info
                current_price = info.get('currentPrice', info.get('regularMarketPrice', 0)) or 0
                buy_price = float(pos.buy_price)
                qty = float(pos.quantity)
                cost_basis = buy_price * qty
                current_value = current_price * qty
                pnl = current_value - cost_basis
                pnl_pct = (pnl / cost_basis * 100) if cost_basis else 0
                portfolio_items.append({
                    'id': pos.id,
                    'symbol': pos.symbol, 'market': pos.market,
                    'name': pos.company_name or info.get('shortName', pos.symbol),
                    'quantity': qty, 'buy_price': buy_price,
                    'current_price': round(current_price, 2),
                    'current_value': round(current_value, 2),
                    'pnl': round(pnl, 2),
                    'pnl_pct': round(pnl_pct, 2),
                    'is_positive': pnl >= 0,
                })
            except Exception:
                portfolio_items.append({
                    'id': pos.id,
                    'symbol': pos.symbol, 'market': pos.market,
                    'name': pos.company_name or pos.symbol,
                    'quantity': float(pos.quantity), 'buy_price': float(pos.buy_price),
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
    # Score color helper
    def sc(v):
        if v >= 80: return ('rgba(0,200,150,0.18)', '#00c896')
        if v >= 50: return ('rgba(255,200,0,0.15)', '#ffc800')
        return ('rgba(239,68,68,0.12)', '#ff6464')

    top_rated = []
    for t, n, m, g, q, v, mo, r, s in [
        ('MU','Micron',842,95,97,67,99,26,98),
        ('NVDA','NVIDIA',5228,99,100,28,97,97,97),
        ('V','Visa',601,76,100,32,18,92,97),
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

            # Save search history (keep last 50 per user)
            clean_symbol = symbol.upper().strip().replace('.JK', '')
            SearchHistory.objects.create(
                user=request.user,
                symbol=clean_symbol,
                market=market,
                company_name=analysis.get('company_name', '')
            )
            # Trim history to 50 entries
            ids = list(SearchHistory.objects.filter(user=request.user).values_list('id', flat=True)[50:])
            if ids:
                SearchHistory.objects.filter(id__in=ids).delete()

        clean_symbol = symbol.upper().strip().replace('.JK', '')
        in_watchlist = Watchlist.objects.filter(user=request.user, symbol=clean_symbol).exists()

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
    obj, created = Watchlist.objects.get_or_create(user=request.user, symbol=symbol, defaults={'market': market})
    if not created:
        obj.delete()
        return JsonResponse({'status': 'removed', 'symbol': symbol})
    return JsonResponse({'status': 'added', 'symbol': symbol})


@login_required
@require_POST
def portfolio_add(request):
    symbol = request.POST.get('symbol', '').upper().strip().replace('.JK', '')
    market = request.POST.get('market', 'US')
    quantity = request.POST.get('quantity', '0')
    buy_price = request.POST.get('buy_price', '0')
    company_name = request.POST.get('company_name', '')

    try:
        Portfolio.objects.create(
            user=request.user,
            symbol=symbol, market=market,
            company_name=company_name,
            quantity=decimal.Decimal(quantity),
            buy_price=decimal.Decimal(buy_price),
        )
    except Exception:
        pass
    return redirect('dashboard')


@login_required
@require_POST
def portfolio_remove(request, pk):
    pos = get_object_or_404(Portfolio, pk=pk, user=request.user)
    pos.delete()
    return redirect('dashboard')


def register(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('dashboard')
    else:
        form = UserCreationForm()
    return render(request, 'registration/register.html', {'form': form})
