from django.db import models
from django.contrib.auth.models import User


class WatchlistItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='watchlist_items')
    symbol = models.CharField(max_length=20)
    market = models.CharField(max_length=5, default='US')

    class Meta:
        unique_together = ('user', 'symbol')

    def __str__(self):
        return f"{self.user.username} - {self.symbol}"


class SearchHistory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='search_history')
    symbol = models.CharField(max_length=20)
    market = models.CharField(max_length=5, default='US')
    company_name = models.CharField(max_length=200, blank=True, default='')
    searched_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-searched_at']

    def __str__(self):
        return f"{self.user.username} - {self.symbol}"


class PortfolioItem(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='portfolio_items')
    symbol = models.CharField(max_length=20)
    market = models.CharField(max_length=5, default='US')
    company_name = models.CharField(max_length=200, blank=True, default='')
    quantity = models.DecimalField(max_digits=20, decimal_places=4)
    buy_price = models.DecimalField(max_digits=20, decimal_places=4)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-added_at']

    def __str__(self):
        return f"{self.user.username} - {self.symbol}"