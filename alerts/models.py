from django.db import models
from django.contrib.auth.models import User


class Watchlist(models.Model):
    """
    Stores a user's saved stock symbols for quick tracking on the Dashboard.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='watchlist')
    symbol = models.CharField(max_length=20)
    market = models.CharField(max_length=5, default='US')  # 'US' or 'ID'
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'symbol')
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.user.username} → {self.symbol} ({self.market})"


class SearchHistory(models.Model):
    """
    Tracks the last N stock symbols a user has analyzed in the Deep Screener.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='search_history')
    symbol = models.CharField(max_length=20)
    market = models.CharField(max_length=5, default='US')
    company_name = models.CharField(max_length=120, blank=True)
    searched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-searched_at']

    def __str__(self):
        return f"{self.user.username} searched {self.symbol}"


class Portfolio(models.Model):
    """
    Tracks a user's stock holdings: symbol, quantity, and buy price for P&L tracking.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolio')
    symbol = models.CharField(max_length=20)
    market = models.CharField(max_length=5, default='US')
    company_name = models.CharField(max_length=120, blank=True)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    buy_price = models.DecimalField(max_digits=14, decimal_places=4)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.user.username} — {self.symbol} x{self.quantity}"
