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


class UserProfile(models.Model):
    PLAN_CHOICES = [
        ('basic', 'Basic'),
        ('premium_annual', 'Premium Annual'),
        ('premium_monthly', 'Premium Monthly'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    plan = models.CharField(max_length=20, choices=PLAN_CHOICES, default='basic')

    @property
    def is_premium(self):
        return self.plan in ('premium_annual', 'premium_monthly')

    def __str__(self):
        return f"{self.user.username} - {self.get_plan_display()}"


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


class PriceAlert(models.Model):
    CONDITION_CHOICES = [
        ('above', 'Above'),
        ('below', 'Below'),
        ('crosses_up', 'Crosses Up'),
        ('crosses_down', 'Crosses Down'),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='price_alerts')
    symbol = models.CharField(max_length=20)
    market = models.CharField(max_length=5, default='US')
    condition = models.CharField(max_length=15, choices=CONDITION_CHOICES, default='above')
    target_price = models.DecimalField(max_digits=20, decimal_places=4)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    triggered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username} - {self.symbol} {self.condition} ${self.target_price}"