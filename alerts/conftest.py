"""Pytest fixtures for the alerts app."""
import pytest


@pytest.fixture(autouse=True)
def clear_cache_between_tests():
    from django.core.cache import cache
    cache.clear()
    yield
    cache.clear()
