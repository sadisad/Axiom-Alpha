from django.apps import AppConfig


class AlertsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'alerts'

    def ready(self):
        import django.contrib.auth

        def _patched_get_user_session_key(request):
            from django.contrib.auth import SESSION_KEY
            return request.session[SESSION_KEY]

        django.contrib.auth._get_user_session_key = _patched_get_user_session_key
