"""Optional sign-in with the company account (OpenID Connect, authorization code flow with PKCE): Microsoft Entra ID,
Okta, Google Workspace, Keycloak, ADFS and other standard providers. Standard library only.

Off by default. When an admin turns it on, the server contacts only the provider at the address the admin entered:
its discovery document, its published signing keys and its token endpoint. The ID token's RS256 signature is
checked against those keys, and its issuer, audience, expiry and nonce against this sign-in.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import ssl
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import quote_plus, urlencode, urlsplit

DEFAULT_OIDC = {"enabled": False, "issuer": "", "client_id": "", "label": "כניסה עם חשבון החברה", "domains": "",
                "default_role": "viewer", "auto_create": True}
SECRET = "oidc_client_secret"
LEEWAY_S = 120                 # clock difference allowed between this server and the provider
CACHE_S = 3600                 # discovery documents and keys are fetched again after an hour
PENDING_S = 600                # a sign-in has to come back from the provider within ten minutes
MAX_BYTES = 1_000_000
# DigestInfo prefix of SHA-256 (RFC 8017, 9.2 note 1)
SHA256_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class OIDCError(Exception):
    """Sign-in with the company account failed; the message is for the user (Hebrew)."""


class UnknownKey(OIDCError):
    pass


def b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def b64url_decode(s: str) -> bytes:
    s = s.strip()
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _check_url(url: str) -> None:
    """Only https, except to this computer (a provider for tests or a local Keycloak)."""
    u = urlsplit(url or "")
    host = (u.hostname or "").lower()
    loop = host == "localhost"
    try:
        loop = loop or ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    if not host or (u.scheme != "https" and not (u.scheme == "http" and loop)):
        raise OIDCError(f"כתובת ספק הזהות חייבת להתחיל ב-https:// ({url or 'ריקה'})")


def http_json(url: str, data: dict | None = None, headers: dict | None = None, timeout: float = 10.0) -> dict:
    """GET (or POST a form) and read a JSON answer. Certificates are checked with the system's trusted roots."""
    _check_url(url)
    req = urllib.request.Request(url, data=urlencode(data).encode("ascii") if data is not None else None,
                                 headers={"Accept": "application/json", "User-Agent": "PartAudit", **(headers or {})})
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            body = r.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            e = json.loads(exc.read(20_000).decode("utf-8", "replace"))
            detail = e.get("error_description") or e.get("error") or ""
        except Exception:
            pass
        raise OIDCError(f"ספק הזהות החזיר שגיאה {exc.code}{': ' + str(detail)[:200] if detail else ''}") from None
    except (urllib.error.URLError, OSError, ssl.SSLError) as exc:
        raise OIDCError(f"אין חיבור לספק הזהות ({urlsplit(url).hostname}): {getattr(exc, 'reason', exc)}") from None
    if len(body) > MAX_BYTES:
        raise OIDCError("התשובה של ספק הזהות גדולה מדי")
    try:
        out = json.loads(body.decode("utf-8"))
    except ValueError:
        raise OIDCError("ספק הזהות לא החזיר JSON") from None
    if not isinstance(out, dict):
        raise OIDCError("ספק הזהות החזיר תשובה לא צפויה")
    return out


_cache: dict[str, tuple[float, object]] = {}
_lock = threading.Lock()


def _cached(key: str, fetch, force: bool = False):
    now = time.time()
    with _lock:
        hit = _cache.get(key)
    if hit and not force and now - hit[0] < CACHE_S:
        return hit[1]
    val = fetch()
    with _lock:
        _cache[key] = (now, val)
    return val


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def discovery(issuer: str, force: bool = False) -> dict:
    issuer = (issuer or "").strip().rstrip("/")
    if not issuer:
        raise OIDCError("לא הוגדרה כתובת ספק הזהות (Issuer)")

    def fetch():
        d = http_json(issuer + "/.well-known/openid-configuration")
        if str(d.get("issuer", "")).rstrip("/") != issuer:
            raise OIDCError(f"ה-Issuer במסמך של ספק הזהות ({d.get('issuer')}) שונה מהכתובת שהוגדרה ({issuer})")
        for k in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
            if not d.get(k):
                raise OIDCError(f"חסר {k} במסמך של ספק הזהות")
            _check_url(d[k])
        return d
    return _cached("d:" + issuer, fetch, force)


def jwks(uri: str, force: bool = False) -> list[dict]:
    def fetch():
        keys = http_json(uri).get("keys")
        if not isinstance(keys, list):
            raise OIDCError("רשימת המפתחות של ספק הזהות לא תקינה")
        return keys
    return _cached("k:" + uri, fetch, force)


# ------------------------------------------------------------------------------------------- RS256 (RSASSA-PKCS1-v1_5)
def rsa_verify(n: int, e: int, message: bytes, signature: bytes) -> bool:
    """RSASSA-PKCS1-v1_5 with SHA-256 (RFC 8017, 8.2.2): the expected encoding is built and compared as a whole,
    never parsed, so a malformed padding cannot pass. Keys under 2048 bits are refused."""
    if n.bit_length() < 2048 or e < 3 or e % 2 == 0:
        return False
    k = (n.bit_length() + 7) // 8
    if len(signature) != k:
        return False
    s = int.from_bytes(signature, "big")
    if s >= n:
        return False
    em = pow(s, e, n).to_bytes(k, "big")
    t = SHA256_PREFIX + hashlib.sha256(message).digest()
    expected = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return hmac.compare_digest(em, expected)


def verify_id_token(token: str, *, keys: list[dict], issuer: str, client_id: str, nonce: str,
                    now: float | None = None) -> dict:
    """The claims of a valid ID token; raises OIDCError (UnknownKey when no published key has its key id)."""
    now = time.time() if now is None else now
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise OIDCError("אסימון הזהות לא תקין")
    try:
        header = json.loads(b64url_decode(parts[0]))
        claims = json.loads(b64url_decode(parts[1]))
        sig = b64url_decode(parts[2])
    except (ValueError, TypeError):
        raise OIDCError("אסימון הזהות לא תקין") from None
    if not isinstance(header, dict) or not isinstance(claims, dict):
        raise OIDCError("אסימון הזהות לא תקין")
    if header.get("alg") != "RS256":
        raise OIDCError(f"סוג החתימה של אסימון הזהות לא נתמך: {header.get('alg')!r} (נתמך: RS256)")
    kid = header.get("kid")
    cands = [k for k in keys if isinstance(k, dict) and k.get("kty") == "RSA" and k.get("use", "sig") == "sig"
             and k.get("alg", "RS256") == "RS256" and (kid is None or k.get("kid") == kid)]
    if not cands:
        raise UnknownKey("המפתח שחתם על אסימון הזהות לא נמצא אצל ספק הזהות")
    msg = f"{parts[0]}.{parts[1]}".encode("ascii")
    ok = False
    for k in cands:
        try:
            n = int.from_bytes(b64url_decode(k["n"]), "big")
            e = int.from_bytes(b64url_decode(k["e"]), "big")
        except (KeyError, ValueError, TypeError):
            continue
        if rsa_verify(n, e, msg, sig):
            ok = True
            break
    if not ok:
        raise OIDCError("החתימה של אסימון הזהות לא תקינה")
    if claims.get("iss") != issuer:
        raise OIDCError("אסימון הזהות הונפק על ידי ספק אחר")
    aud = claims.get("aud")
    auds = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
    if client_id not in auds or (len(auds) > 1 and claims.get("azp") != client_id):
        raise OIDCError("אסימון הזהות לא הונפק לתוכנה הזו (Client ID)")
    for k in ("exp", "iat"):
        if not isinstance(claims.get(k), (int, float)):
            raise OIDCError("חסר זמן תוקף באסימון הזהות")
    if now > claims["exp"] + LEEWAY_S:
        raise OIDCError("תוקף אסימון הזהות פג – נסו להיכנס שוב")
    if claims["iat"] > now + LEEWAY_S or (isinstance(claims.get("nbf"), (int, float)) and claims["nbf"] > now + LEEWAY_S):
        raise OIDCError("אסימון הזהות עדיין לא בתוקף – בדקו את השעון של השרת")
    if not isinstance(claims.get("nonce"), str) or not hmac.compare_digest(claims["nonce"], nonce):
        raise OIDCError("אסימון הזהות לא שייך לכניסה הזו")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise OIDCError("חסר מזהה משתמש באסימון הזהות")
    return claims


# ------------------------------------------------------------------------------------------- the sign-in itself
def start(cfg: dict, redirect_uri: str) -> tuple[str, dict]:
    """The provider's sign-in address, and what to keep until the user comes back."""
    d = discovery(cfg["issuer"])
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    q = {"response_type": "code", "client_id": cfg["client_id"], "redirect_uri": redirect_uri,
         "scope": "openid email profile", "state": state, "nonce": nonce, "code_challenge": challenge,
         "code_challenge_method": "S256"}
    ep = d["authorization_endpoint"]
    return ep + ("&" if "?" in ep else "?") + urlencode(q), {"state": state, "nonce": nonce, "verifier": verifier,
                                                              "redirect_uri": redirect_uri, "at": time.time()}


def finish(cfg: dict, client_secret: str, code: str, pending: dict) -> dict:
    """Exchange the code for tokens and return the verified ID token claims."""
    if time.time() - pending["at"] > PENDING_S:
        raise OIDCError("עבר יותר מדי זמן מתחילת הכניסה – נסו שוב")
    d = discovery(cfg["issuer"])
    issuer = d["issuer"]
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": pending["redirect_uri"],
            "code_verifier": pending["verifier"]}
    headers = {}
    methods = d.get("token_endpoint_auth_methods_supported") or ["client_secret_basic"]
    if client_secret and "client_secret_basic" in methods:
        raw = f"{quote_plus(cfg['client_id'])}:{quote_plus(client_secret)}".encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
    elif client_secret:
        form.update(client_id=cfg["client_id"], client_secret=client_secret)
    else:
        form["client_id"] = cfg["client_id"]       # a public client: PKCE only
    tok = http_json(d["token_endpoint"], data=form, headers=headers)
    idt = tok.get("id_token")
    if not isinstance(idt, str):
        raise OIDCError("ספק הזהות לא החזיר אסימון זהות (בדקו שה-scope כולל openid)")
    kw = dict(issuer=issuer, client_id=cfg["client_id"], nonce=pending["nonce"])
    try:
        return verify_id_token(idt, keys=jwks(d["jwks_uri"]), **kw)
    except UnknownKey:                      # the provider rolled its keys: fetch them once more
        return verify_id_token(idt, keys=jwks(d["jwks_uri"], force=True), **kw)


def _verified(v) -> bool | None:
    """email_verified as sent: true / false, also as the strings "true" / "false"; None when not sent."""
    if isinstance(v, str):
        return {"true": True, "false": False}.get(v.strip().lower(), False)
    return None if v is None else bool(v)


def identity(cfg: dict, claims: dict) -> dict:
    """Who signed in: a stable key (issuer + subject), the e-mail of the "email" claim, the sign-in name
    (preferred_username / upn, which some providers let users change - used only to name a new account), and
    whether the e-mail may identify an existing account: the provider says it is verified, or it says nothing
    and the e-mail is in a company domain set in PartAudit. Checks the allowed domains."""
    email = str(claims.get("email") or "").strip().lower()
    email = email if "@" in email else ""
    login = str(claims.get("preferred_username") or claims.get("upn") or "").strip().lower()
    verified = _verified(claims.get("email_verified"))
    if email and verified is False:
        raise OIDCError("כתובת המייל בחשבון לא אומתה אצל ספק הזהות")
    domains = [x.strip().lower().lstrip("@") for x in str(cfg.get("domains") or "").replace(";", ",").split(",")
               if x.strip()]
    shown = email or login
    in_domain = "@" in shown and shown.rsplit("@", 1)[1] in domains
    if domains and not in_domain:
        raise OIDCError("החשבון לא שייך לדומיין של החברה שהוגדר ב-PartAudit")
    name = str(claims.get("name") or " ".join(x for x in (claims.get("given_name"), claims.get("family_name")) if x)
               or email or login or claims["sub"])
    return {"sub": f"{claims['iss']}|{claims['sub']}", "email": email, "login": login, "name": name[:120],
            "email_trusted": bool(email) and (verified is True or (verified is None and bool(domains) and in_domain))}


def check_config(cfg: dict) -> dict:
    """For the settings screen: can the provider be reached, and does it publish what sign-in needs."""
    d = discovery(cfg.get("issuer", ""), force=True)
    keys = jwks(d["jwks_uri"], force=True)
    rsa = [k for k in keys if isinstance(k, dict) and k.get("kty") == "RSA"]
    if not rsa:
        raise OIDCError("ספק הזהות לא מפרסם מפתחות RSA (נדרש RS256)")
    if "RS256" not in (d.get("id_token_signing_alg_values_supported") or ["RS256"]):
        raise OIDCError("ספק הזהות לא חותם ב-RS256")
    if not cfg.get("client_id"):
        raise OIDCError("חסר Client ID")
    return {"issuer": d["issuer"], "authorization_endpoint": d["authorization_endpoint"], "keys": len(rsa),
            "pkce": "S256" in (d.get("code_challenge_methods_supported") or ["S256"])}
