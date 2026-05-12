from django.contrib.auth.models import User


def toggle_watchlist(uid, symbol, market='US'):
    try:
        user = User.objects.get(pk=uid)
    except User.DoesNotExist:
        return 'error'
    from .models import WatchlistItem
    item, created = WatchlistItem.objects.get_or_create(
        user=user, symbol=symbol, defaults={'market': market}
    )
    if not created:
        item.delete()
        return 'removed'
    return 'added'


def check_in_watchlist(uid, symbol):
    try:
        user = User.objects.get(pk=uid)
    except User.DoesNotExist:
        return False
    from .models import WatchlistItem
    return WatchlistItem.objects.filter(user=user, symbol=symbol).exists()


def get_watchlist(uid):
    try:
        user = User.objects.get(pk=uid)
    except User.DoesNotExist:
        return []
    from .models import WatchlistItem
    items = WatchlistItem.objects.filter(user=user)
    return [{'id': str(item.id), 'symbol': item.symbol, 'market': item.market} for item in items]


def add_search_history(uid, symbol, market, company_name=''):
    try:
        user = User.objects.get(pk=uid)
    except User.DoesNotExist:
        return
    from .models import SearchHistory
    SearchHistory.objects.create(
        user=user, symbol=symbol, market=market, company_name=company_name
    )


def get_search_history(uid, limit=6):
    try:
        user = User.objects.get(pk=uid)
    except User.DoesNotExist:
        return []
    from .models import SearchHistory
    entries = SearchHistory.objects.filter(user=user).order_by('-searched_at')[:limit * 2]
    seen = set()
    results = []
    for entry in entries:
        if entry.symbol not in seen:
            seen.add(entry.symbol)
            results.append(type('SearchEntry', (), {
                'symbol': entry.symbol,
                'market': entry.market,
                'company_name': entry.company_name,
            })())
        if len(results) >= limit:
            break
    return results


def get_portfolio(uid):
    try:
        user = User.objects.get(pk=uid)
    except User.DoesNotExist:
        return []
    from .models import PortfolioItem
    items = PortfolioItem.objects.filter(user=user).order_by('-added_at')
    return [{
        'id': str(item.id),
        'symbol': item.symbol,
        'market': item.market,
        'company_name': item.company_name,
        'quantity': float(item.quantity),
        'buy_price': float(item.buy_price),
    } for item in items]


def add_portfolio(uid, symbol, market, company_name, quantity, buy_price):
    try:
        user = User.objects.get(pk=uid)
    except User.DoesNotExist:
        return None
    from .models import PortfolioItem
    item = PortfolioItem.objects.create(
        user=user, symbol=symbol, market=market,
        company_name=company_name, quantity=quantity, buy_price=buy_price,
    )
    return str(item.id)


def remove_portfolio(uid, doc_id):
    try:
        user = User.objects.get(pk=uid)
    except User.DoesNotExist:
        return
    from .models import PortfolioItem
    try:
        item = PortfolioItem.objects.get(pk=doc_id, user=user)
        item.delete()
    except PortfolioItem.DoesNotExist:
        pass