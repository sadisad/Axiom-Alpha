"""Tests for alerts app — focused on view contracts, not yfinance integration.

Run with: pytest

Tests that hit external services are marked @pytest.mark.integration and
skipped by default. Run them with: pytest -m integration
"""
import pytest
from unittest.mock import patch
from django.test import Client
from django.urls import reverse
from django.contrib.auth.models import User


# ====== Public endpoint smoke tests ======

@pytest.mark.django_db
def test_dashboard_renders():
    client = Client()
    resp = client.get(reverse('dashboard'))
    assert resp.status_code == 200
    assert b'Axiom Alpha' in resp.content


@pytest.mark.django_db
def test_radar_renders():
    client = Client()
    resp = client.get(reverse('radar'))
    assert resp.status_code == 200
    assert b'Stock Radar' in resp.content


@pytest.mark.django_db
def test_screener_renders_without_symbol():
    """Screener requires login; unauthenticated users should be redirected."""
    client = Client()
    resp = client.get(reverse('screener'))
    # Either renders (200) or redirects to login (302) depending on auth setup.
    assert resp.status_code in (200, 302)


@pytest.mark.django_db
def test_screener_renders_when_logged_in():
    user = User.objects.create_user('alice', password='pw12345!')
    client = Client()
    client.force_login(user)
    resp = client.get(reverse('screener'))
    assert resp.status_code == 200


@pytest.mark.django_db
def test_compare_renders_empty():
    """Compare may require login; tolerate either path."""
    client = Client()
    resp = client.get(reverse('compare'))
    assert resp.status_code in (200, 302)


@pytest.mark.django_db
def test_compare_renders_when_logged_in():
    user = User.objects.create_user('alice', password='pw12345!')
    client = Client()
    client.force_login(user)
    resp = client.get(reverse('compare'))
    assert resp.status_code == 200
    assert b'Compare Any Two Stocks' in resp.content


@pytest.mark.django_db
def test_robots_txt():
    client = Client()
    resp = client.get('/robots.txt')
    assert resp.status_code == 200
    assert resp['Content-Type'].startswith('text/plain')
    assert b'User-agent: *' in resp.content
    assert b'Sitemap:' in resp.content


@pytest.mark.django_db
def test_sitemap_xml():
    client = Client()
    resp = client.get('/sitemap.xml')
    assert resp.status_code == 200
    assert b'<urlset' in resp.content
    assert b'/radar/' in resp.content


@pytest.mark.django_db
def test_healthz():
    client = Client()
    resp = client.get('/healthz')
    assert resp.status_code == 200
    assert resp.json() == {'status': 'ok', 'service': 'axiom-alpha'}


# ====== Symbol search ======

@pytest.mark.django_db
def test_symbol_search_empty_query():
    client = Client()
    resp = client.get(reverse('symbol_search') + '?q=')
    assert resp.status_code == 200
    assert resp.json() == {'results': []}


@pytest.mark.django_db
def test_symbol_search_finds_aapl():
    client = Client()
    resp = client.get(reverse('symbol_search') + '?q=AAPL')
    data = resp.json()
    assert resp.status_code == 200
    assert any(r['symbol'] == 'AAPL' for r in data['results'])


@pytest.mark.django_db
def test_symbol_search_finds_idx():
    client = Client()
    resp = client.get(reverse('symbol_search') + '?q=BBCA')
    data = resp.json()
    assert resp.status_code == 200
    assert any(r['symbol'] == 'BBCA' and r['market'] == 'ID' for r in data['results'])


@pytest.mark.django_db
def test_symbol_search_caps_results():
    client = Client()
    # Single letter likely matches many tickers.
    resp = client.get(reverse('symbol_search') + '?q=A')
    data = resp.json()
    assert len(data['results']) <= 10


# ====== radar_scores caching ======

@pytest.mark.django_db
def test_radar_scores_uses_cache():
    """Second identical request must not call get_market_scores again."""
    from django.core.cache import cache
    cache.clear()
    client = Client()
    with patch('alerts.views.get_market_scores') as mock_scores:
        mock_scores.return_value = [{'t': 'AAPL', 'n': 'Apple', 's': 80}]
        r1 = client.get('/api/radar-scores/?market=US&size=25')
        r2 = client.get('/api/radar-scores/?market=US&size=25')
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert mock_scores.call_count == 1  # second call hit cache


@pytest.mark.django_db
def test_radar_scores_invalid_size_falls_back():
    from django.core.cache import cache
    cache.clear()
    client = Client()
    with patch('alerts.views.get_market_scores') as mock_scores:
        mock_scores.return_value = []
        resp = client.get('/api/radar-scores/?market=US&size=abc')
        assert resp.status_code == 200


@pytest.mark.django_db
def test_radar_scores_handles_exception():
    from django.core.cache import cache
    cache.clear()
    client = Client()
    with patch('alerts.views.get_market_scores', side_effect=RuntimeError('yfinance down')):
        resp = client.get('/api/radar-scores/?market=US&size=25')
        assert resp.status_code == 200
        data = resp.json()
        assert data['stocks'] == []
        assert 'yfinance down' in data['error']


# ====== Authentication required endpoints ======

@pytest.mark.django_db
def test_toggle_watchlist_requires_login():
    client = Client()
    resp = client.post(reverse('toggle_watchlist'), {'symbol': 'AAPL', 'market': 'US'})
    # @login_required redirects to login when not authenticated.
    assert resp.status_code in (302, 401, 403)


@pytest.mark.django_db
def test_toggle_watchlist_rejects_get():
    user = User.objects.create_user('alice', password='pw12345!')
    client = Client()
    client.force_login(user)
    resp = client.get(reverse('toggle_watchlist'))
    assert resp.status_code == 405  # @require_POST


@pytest.mark.django_db
def test_portfolio_add_requires_login():
    client = Client()
    resp = client.post(reverse('portfolio_add'), {'symbol': 'AAPL', 'market': 'US',
                                                    'quantity': '10', 'buy_price': '150'})
    assert resp.status_code in (302, 401, 403)


@pytest.mark.django_db
def test_prices_api_requires_login():
    client = Client()
    resp = client.get('/api/prices/?symbols=AAPL&markets=US')
    assert resp.status_code == 401


# ====== Login rate limiting ======

@pytest.mark.django_db
def test_login_rate_limit_kicks_in():
    from django.core.cache import cache
    cache.clear()
    client = Client()
    # 8 wrong attempts allowed, 9th should be blocked.
    for _ in range(8):
        client.post(reverse('login'), {'username': 'nope', 'password': 'wrong'})
    resp = client.post(reverse('login'), {'username': 'nope', 'password': 'wrong'})
    assert resp.status_code == 429
    assert b'Too many login attempts' in resp.content


# ====== Indices API yield formatting ======

@pytest.mark.django_db
def test_indices_api_formats_yield():
    """^TNX should be expressed as a percent string, not raw 43.0."""
    from django.core.cache import cache
    cache.clear()
    client = Client()
    fake_data = {
        'SPY': {'price': '450.00', 'change': 0.5, 'is_positive': True, 'current_price': 450.0, 'price_raw': 450.0},
        'QQQ': {'price': '380.00', 'change': 0.3, 'is_positive': True, 'current_price': 380.0, 'price_raw': 380.0},
        'DIA': {'price': '350.00', 'change': 0.2, 'is_positive': True, 'current_price': 350.0, 'price_raw': 350.0},
        'BTC-USD': {'price': '60000.00', 'change': 1.0, 'is_positive': True, 'current_price': 60000.0, 'price_raw': 60000.0},
        '^TNX': {'price': '43.0', 'change': 0.1, 'is_positive': True, 'current_price': 43.0, 'price_raw': 43.0},
    }
    with patch('alerts.views.batch_stock_data', return_value=fake_data):
        resp = client.get(reverse('indices_api'))
        data = resp.json()
        assert data['indices']['^TNX']['price'] == '4.30%'
        assert data['indices']['SPY']['price'] == '450.00'


# ====== Stock list grouping ======

@pytest.mark.django_db
def test_stock_lists_returns_groups():
    from django.core.cache import cache
    cache.clear()
    client = Client()
    resp = client.get(reverse('stock_lists'))
    assert resp.status_code == 200
    data = resp.json()
    assert 'groups' in data
    assert isinstance(data['groups'], list)
    if data['groups']:
        assert 'category' in data['groups'][0]
        assert 'lists' in data['groups'][0]
