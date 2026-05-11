from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('about/', views.about, name='about'),
    path('maps/', views.maps, name='maps'),
    path('screener/', views.screener, name='screener'),
    path('compare/', views.compare, name='compare'),
    path('toggle-watchlist/', views.toggle_watchlist, name='toggle_watchlist'),
    path('portfolio/add/', views.portfolio_add, name='portfolio_add'),
    path('portfolio/remove/<str:pk>/', views.portfolio_remove, name='portfolio_remove'),
    path('login/', auth_views.LoginView.as_view(template_name='registration/login.html'), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('register/', views.register, name='register'),
]
