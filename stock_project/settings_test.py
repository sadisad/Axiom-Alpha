"""Test-only settings overlay.

Importing this module imports the main settings then forces SQLite in-memory
for the test database, regardless of DATABASE_URL.
"""
from stock_project.settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Disable production hardening so the test client can hit views over HTTP.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
DEBUG = False  # Keep DEBUG off so we test prod-ish behavior, just without HTTPS.

# Use a dedicated locmem cache so tests don't share state with a running server.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'axiom-test',
    }
}
