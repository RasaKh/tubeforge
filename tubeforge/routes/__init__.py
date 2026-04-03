import base64
import hashlib
import hmac
import ipaddress
import shlex
from urllib.parse import urlsplit

from flask import jsonify, request

from ..config import CONFIG, PathError, SESSIONS, SESSION_TTL, _config_lock
import time

def jerr(msg, code=400):
    return jsonify({"ok": False, "error": str(msg)}), code


def body():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        raise ValueError("The request body must be a JSON object.")
    return data


def cmd_string(argv):
    return " ".join(shlex.quote(a) for a in argv)


def public_config(cfg=None):
    """Return configuration without authentication material."""
    value = dict(cfg or CONFIG)
    value.pop("auth_token_hash", None)
    return value


def auth_token_valid(token):
    expected = CONFIG.get("auth_token_hash") or ""
    actual = hashlib.sha256(str(token or "").encode()).hexdigest()
    return bool(expected) and hmac.compare_digest(actual, expected)


def auth_required():
    return bool(CONFIG.get("auth_enabled"))


def request_is_authorized():
    if not auth_required():
        return True
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer "):
        return auth_token_valid(header[7:].strip())
    # The browser UI uses a short-lived, same-origin session cookie after the
    # one-time token exchange.  Keep the token itself out of URLs and logs.
    cookie = request.cookies.get("tubeforge_session")
    if not cookie:
        return False
    with _config_lock:
        return cookie in SESSIONS and SESSIONS[cookie] > time.time()




def register_error_and_hooks(app):
    app.errorhandler(PathError)(api_validation_error)
    app.errorhandler(ValueError)(api_validation_error)
    app.before_request(check_request_origin)
    app.after_request(_no_cache)

def api_validation_error(exc):
    return jsonify({"error": str(exc)}), 400

def check_request_origin():
    if request.path.startswith("/api/") and request.method in ("POST", "DELETE", "PUT", "PATCH"):
        origin = request.headers.get("Origin")
        if origin and (origin == "null" or urlsplit(origin).netloc != request.host):
            return jerr("Cross-origin state changes are not permitted.", 403)
        if request.data and not request.is_json:
            return jerr("Use application/json for API requests.", 415)
    if auth_required() and request.path.startswith("/api/") and request.path != "/api/auth/login" and not request_is_authorized():
        return jerr("Authentication required.", 401)



def _no_cache(resp):
    if request.path.startswith("/api/"):
        resp.headers["Cache-Control"] = "no-store"
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    resp.headers.setdefault("Content-Security-Policy",
        "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
    return resp

