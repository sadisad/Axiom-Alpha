from django.contrib.auth.backends import BaseBackend
from .firebase_db import get_user_by_username


class FirestoreAuthBackend(BaseBackend):
    def authenticate(self, request=None, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        user = get_user_by_username(username)
        if user and user.check_password(password):
            return user
        return None

    def get_user(self, user_id):
        return get_user_by_username(user_id)