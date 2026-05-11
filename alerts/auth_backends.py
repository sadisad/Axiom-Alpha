import logging
from django.contrib.auth.backends import BaseBackend
from .firebase_db import get_user_by_username

logger = logging.getLogger(__name__)


class FirestoreAuthBackend(BaseBackend):
    def authenticate(self, request=None, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        try:
            user = get_user_by_username(username)
        except Exception as e:
            logger.error("Firestore auth error: %s", e)
            return None
        if user and user.check_password(password):
            return user
        return None

    def get_user(self, user_id):
        try:
            return get_user_by_username(user_id)
        except Exception:
            return None