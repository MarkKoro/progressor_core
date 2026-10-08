"""Telegram proof verification and short, audience-bound cross-domain assertions."""
import base64
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl
from .contracts import canonical, subject

ISSUER = 'progressor-core'
AUDIENCES = ('gym', 'food', 'supply', 'core')


def telegram_user(raw, token, now=None):
    if not isinstance(raw, str) or not raw or len(raw) > 16384 or not token:
        raise ValueError('invalid_launch')
    pairs = parse_qsl(raw, keep_blank_values=True, max_num_fields=64)
    if len({k for k, _ in pairs}) != len(pairs):
        raise ValueError('duplicate_launch_field')
    data = dict(pairs)
    signature = data.pop('hash', '')
    if len(signature) != 64 or any(c not in '0123456789abcdefABCDEF' for c in signature):
        raise ValueError('invalid_launch_signature')
    secret = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, '\n'.join(f'{k}={v}' for k, v in sorted(data.items())).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature.lower()):
        raise ValueError('invalid_launch_signature')
    now = int(time.time()) if now is None else now
    auth_date = int(data['auth_date'])
    if not -30 <= now - auth_date <= 86400:
        raise ValueError('expired_launch')
    user = json.loads(data['user'])
    if not isinstance(user, dict) or type(user.get('id')) is not int:
        raise ValueError('invalid_user')
    subject(user['id'])
    clean = {'id': user['id']}
    for field in ('first_name', 'last_name', 'username'):
        if isinstance(user.get(field), str) and len(user[field]) <= 256:
            clean[field] = user[field]
    return clean, auth_date


def sign_assertion(user, auth_date, audience, key, now=None, ttl=900):
    if audience not in AUDIENCES or len(key) < 32:
        raise ValueError('invalid_assertion_configuration')
    now = int(time.time()) if now is None else now
    payload = {'iss': ISSUER, 'typ': 'progressor.assertion.v1', 'aud': audience, 'sub': subject(user['id']), 'user': user, 'auth_date': auth_date, 'iat': now, 'exp': min(now + ttl, auth_date + 86400)}
    body = base64.urlsafe_b64encode(canonical(payload).encode()).decode().rstrip('=')
    mac = hmac.new(key.encode(), ('v1.' + body).encode(), hashlib.sha256).hexdigest()
    return 'v1.' + body + '.' + mac


def verify_assertion(token, audience, key, now=None):
    if not isinstance(token, str) or len(token) > 4096 or len(key) < 32:
        raise ValueError('invalid_assertion')
    version, body, mac = token.split('.')
    expected = hmac.new(key.encode(), (version + '.' + body).encode(), hashlib.sha256).hexdigest()
    if version != 'v1' or not hmac.compare_digest(expected, mac):
        raise ValueError('invalid_assertion')
    claims = json.loads(base64.b64decode(body + '=' * (-len(body) % 4), altchars=b'-_', validate=True))
    now = int(time.time()) if now is None else now
    if claims.get('iss') != ISSUER or claims.get('typ') != 'progressor.assertion.v1' or claims.get('aud') != audience:
        raise ValueError('invalid_assertion_audience')
    if any(type(claims.get(k)) is not int for k in ('iat', 'exp', 'auth_date')):
        raise ValueError('invalid_assertion_time')
    if not claims['iat'] - 30 <= now < claims['exp'] or not 0 < claims['exp'] - claims['iat'] <= 900 or claims['exp'] > claims['auth_date'] + 86400:
        raise ValueError('expired_assertion')
    if not isinstance(claims.get('user'), dict) or type(claims['user'].get('id')) is not int or subject(claims['user']['id']) != claims.get('sub'):
        raise ValueError('invalid_assertion_subject')
    return claims
