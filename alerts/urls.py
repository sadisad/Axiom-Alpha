from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('about/', views.about, name='about'),
    path('maps/', views.maps, name='maps'),
    path('screener/', views.screener, name='screener'),
    path('compare/', views.compare, name='compare'),
    path('headlines/', views.headlines, name='headlines'),
    path('watchtower/', views.watchtower, name='watchtower'),
    path('portfolios/', views.portfolios, name='portfolios'),
    path('toggle-watchlist/', views.toggle_watchlist, name='toggle_watchlist'),
    path('portfolio/add/', views.portfolio_add, name='portfolio_add'),
    path('portfolio/remove/<str:pk>/', views.portfolio_remove, name='portfolio_remove'),
    path('login/', views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
    path('api/google-auth/', views.google_auth, name='google_auth'),
]