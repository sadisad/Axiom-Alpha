import os
import firebase_admin
from firebase_admin import credentials, firestore, auth as firebase_auth
from django.contrib.auth.hashers import make_password, check_password
from django.utils.crypto import salted_hmac


_creds_dict = None
_app = None


def _init():
    global _app, _creds_dict
    if _app:
        return _app
    project_id = os.environ.get('FIREBASE_PROJECT_ID', '')
    if not project_id:
        raise RuntimeError('FIREBASE_PROJECT_ID env var is missing')
    private_key = os.environ.get('FIREBASE_PRIVATE_KEY', '').replace('\\n', '\n')
    _creds_dict = {
        'type': 'service_account',
        'project_id': project_id,
        'private_key_id': os.environ.get('FIREBASE_PRIVATE_KEY_ID', ''),
        'private_key': private_key,
        'client_email': os.environ.get('FIREBASE_CLIENT_EMAIL', ''),
        'client_id': os.environ.get('FIREBASE_CLIENT_ID', ''),
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token',
        'auth_provider_x509_cert_url': 'https://www.googleapis.com/oauth2/v1/certs',
        'client_x509_cert_url': os.environ.get('FIREBASE_CLIENT_X509_CERT_URL', ''),
    }
    cred = credentials.Certificate(_creds_dict)
    _app = firebase_admin.initialize_app(cred)
    return _app


def _db():
    _init()
    return firestore.client()


class FirestoreUser:
    def __init__(self, uid, data):
        self.uid = uid
        self.username = data.get('username', uid)
        self.email = data.get('email', '')
        self._password = data.get('password', '')
        self.is_authenticated = True
        self.is_active = True
        self.is_staff = False
        self.is_superuser = False

    @property
    def pk(self):
        return self.uid

    @property
    def id(self):
        return self.uid

    def check_password(self, raw_password):
        if not self._password:
            return False
        return check_password(raw_password, self._password)

    def get_session_auth_hash(self):
        key_salt = "alerts.firebase_db.FirestoreUser.get_session_auth_hash"
        return salted_hmac(key_salt, self._password or 'google-auth').hexdigest()

    @property
    def is_anonymous(self):
        return False

    def __str__(self):
        return self.username

    def __eq__(self, other):
        if isinstance(other, FirestoreUser):
            return self.uid == other.uid
        return False

    def __hash__(self):
        return hash(self.uid)


def create_user(username, email, password):
    db = _db()
    user_data = {
        'username': username,
        'email': email,
        'password': make_password(password),
    }
    db.collection('users').document(username).set(user_data)
    return FirestoreUser(username, user_data)


def get_user_by_username(username):
    db = _db()
    doc = db.collection('users').document(username).get()
    if doc.exists:
        return FirestoreUser(doc.id, doc.to_dict())
    return None


def find_or_create_google_user(id_token):
    decoded = firebase_auth.verify_id_token(id_token)
    email = decoded.get('email', '')
    name = decoded.get('name', '')
    uid = decoded.get('uid', '')
    username = email.split('@')[0] if email else uid

    db = _db()

    users_by_email = db.collection('users').where('email', '==', email).limit(1).stream()
    for doc in users_by_email:
        data = doc.to_dict()
        return FirestoreUser(doc.id, data)

    users_by_uid = db.collection('users').where('firebase_uid', '==', uid).limit(1).stream()
    for doc in users_by_uid:
        data = doc.to_dict()
        return FirestoreUser(doc.id, data)

    user_data = {
        'username': username,
        'email': email,
        'password': '',
        'firebase_uid': uid,
        'auth_provider': 'google',
    }
    if name:
        user_data['display_name'] = name

    db.collection('users').document(username).set(user_data)
    return FirestoreUser(username, user_data)


def get_watchlist(uid):
    db = _db()
    docs = db.collection('watchlist').where('uid', '==', uid).stream()
    return [{'id': doc.id, **doc.to_dict()} for doc in docs]


def toggle_watchlist(uid, symbol, market='US'):
    db = _db()
    doc_ref = db.collection('watchlist').document(f'{uid}_{symbol}')
    doc = doc_ref.get()
    if doc.exists:
        doc_ref.delete()
        return 'removed'
    doc_ref.set({'uid': uid, 'symbol': symbol, 'market': market})
    return 'added'


def check_in_watchlist(uid, symbol):
    db = _db()
    doc = db.collection('watchlist').document(f'{uid}_{symbol}').get()
    return doc.exists


def add_search_history(uid, symbol, market, company_name=''):
    db = _db()
    db.collection('search_history').add({
        'uid': uid,
        'symbol': symbol,
        'market': market,
        'company_name': company_name,
        'searched_at': firestore.SERVER_TIMESTAMP,
    })


def get_search_history(uid, limit=6):
    db = _db()
    docs = db.collection('search_history') \
        .where('uid', '==', uid) \
        .order_by('searched_at', direction=firestore.Query.DESCENDING) \
        .limit(limit * 2) \
        .stream()
    seen = set()
    results = []
    for doc in docs:
        data = doc.to_dict()
        sym = data.get('symbol', '')
        if sym not in seen:
            seen.add(sym)
            results.append(type('SearchEntry', (), {
                'symbol': sym,
                'market': data.get('market', 'US'),
                'company_name': data.get('company_name', ''),
            })())
        if len(results) >= limit:
            break
    return results


def get_portfolio(uid):
    db = _db()
    docs = db.collection('portfolio').where('uid', '==', uid).order_by('added_at', direction=firestore.Query.DESCENDING).stream()
    return [{'id': doc.id, **doc.to_dict()} for doc in docs]


def add_portfolio(uid, symbol, market, company_name, quantity, buy_price):
    db = _db()
    doc_ref = db.collection('portfolio').add({
        'uid': uid,
        'symbol': symbol,
        'market': market,
        'company_name': company_name,
        'quantity': quantity,
        'buy_price': buy_price,
        'added_at': firestore.SERVER_TIMESTAMP,
    })
    return doc_ref[1].id


def remove_portfolio(uid, doc_id):
    db = _db()
    doc_ref = db.collection('portfolio').document(doc_id)
    doc = doc_ref.get()
    if doc.exists and doc.to_dict().get('uid') == uid:
        doc_ref.delete()