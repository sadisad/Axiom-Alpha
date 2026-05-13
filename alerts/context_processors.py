import os


def firebase_config(request):
    return {
        'FIREBASE_API_KEY': os.environ.get('FIREBASE_API_KEY', ''),
        'FIREBASE_AUTH_DOMAIN': os.environ.get('FIREBASE_AUTH_DOMAIN', ''),
        'FIREBASE_PROJECT_ID_JS': os.environ.get('FIREBASE_PROJECT_ID', ''),
    }


def subscription_context(request):
    if request.user.is_authenticated:
        try:
            profile = request.user.profile
            return {
                'user_plan': profile.plan,
                'is_premium': profile.is_premium,
            }
        except Exception:
            return {
                'user_plan': 'basic',
                'is_premium': False,
            }
    return {
        'user_plan': 'basic',
        'is_premium': False,
    }