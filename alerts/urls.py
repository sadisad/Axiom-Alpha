from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('about/', views.about, name='about'),
    path('maps/', views.maps, name='maps'),
    path('radar/', views.radar, name='radar'),
    path('api/radar-scores/', views.radar_scores, name='radar_scores'),
    path('api/stock-lists/', views.stock_lists, name='stock_lists'),
    path('api/prices/', views.prices_api, name='prices_api'),
    path('api/market-status/', views.market_status, name='market_status'),
    path('screener/', views.screener, name='screener'),
    path('compare/', views.compare, name='compare'),
    path('headlines/', views.headlines, name='headlines'),
    path('watchtower/', views.watchtower, name='watchtower'),
    path('alerts/create/', views.alert_create, name='alert_create'),
    path('alerts/delete/<int:pk>/', views.alert_delete, name='alert_delete'),
    path('portfolios/', views.portfolios, name='portfolios'),
    path('toggle-watchlist/', views.toggle_watchlist, name='toggle_watchlist'),
    path('portfolio/add/', views.portfolio_add, name='portfolio_add'),
    path('portfolio/remove/<str:pk>/', views.portfolio_remove, name='portfolio_remove'),
    path('portfolio/edit/<str:pk>/', views.portfolio_edit, name='portfolio_edit'),
    path('portfolio/export/', views.portfolio_export_csv, name='portfolio_export'),
    path('portfolio/import/', views.portfolio_import_csv, name='portfolio_import'),
    path('watchlist/export/', views.watchlist_export_csv, name='watchlist_export'),
    path('login/', views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
]