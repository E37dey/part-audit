"""Team mode: user accounts with roles, password sign-in, sessions and who may do what. Standard library only.

In the default single-computer mode the app answers only this computer's browser and nobody signs in. In team mode
(`python -m part_audit serve`) one computer serves the app to the network and every request needs a signed-in user:

* viewer   - sees everything and exports
* engineer - also decides on duplicates, runs scans and pre-release checks
* admin    - also manages sources, settings and users
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import threading
import time

ROLES = ("viewer", "engineer", "admin")
RANK = {r: i for i, r in enumerate(ROLES)}
ROLE_HE = {"viewer": "צפייה", "engineer": "מהנדס", "admin": "מנהל"}

DEFAULT_ITERATIONS = 600_000    # PBKDF2-HMAC-SHA256 (OWASP password storage recommendation, 2023)
ITERATIONS = DEFAULT_ITERATIONS
SESSION_IDLE_S = 7 * 86400      # a session ends after a week without use
SESSION_MAX_S = 30 * 86400      # and 30 days after sign-in at the latest
COOKIE = "pa_session"
USERNAME = re.compile(r"[\w.@\-]{2,64}")     # \w includes Hebrew letters
COMMON = {"12345678", "123456789", "1234567890", "password", "password1", "qwertyui", "qwerty123", "11111111",
          "00000000", "abcd1234", "abcdefgh", "iloveyou", "admin123", "administrator", "partaudit", "12341234"}


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def hash_password(password: str, iterations: int | None = None) -> str:
    """'pbkdf2_sha256$<iterations>$<salt>$<hash>' (the iterations travel with the hash, so they can be raised later)."""
    it = int(iterations or ITERATIONS)
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, it)
    return f"pbkdf2_sha256${it}${_b64(salt)}${_b64(dk)}"


_DUMMY: list[str] = []


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. An unknown user or an account without a password costs the same time as a wrong one."""
    try:
        algo, it, salt, dk = (stored or "").split("$")
        it = int(it)
        ok_format = algo == "pbkdf2_sha256" and 1_000 <= it <= 10_000_000
        salt_b, dk_b = base64.b64decode(salt), base64.b64decode(dk)
    except (ValueError, TypeError):
        ok_format = False
    if not ok_format:
        if not _DUMMY:
            _DUMMY.append(hash_password("x"))
        verify_password(password, _DUMMY[0])
        return False
    got = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_b, it)
    return hmac.compare_digest(got, dk_b)


def password_problem(password: str, username: str = "") -> str | None:
    """Why a new password is not accepted (Hebrew), or None."""
    if len(password) < 8:
        return "הסיסמה צריכה להיות באורך 8 תווים לפחות"
    if len(password) > 256:
        return "הסיסמה ארוכה מדי"
    low = password.strip().lower()
    if username and low == username.strip().lower():
        return "הסיסמה לא יכולה להיות שם המשתמש"
    if low in COMMON or len(set(low)) < 3:
        return "הסיסמה פשוטה מדי – בחרו סיסמה אחרת"
    return None


def username_problem(username: str) -> str | None:
    if not USERNAME.fullmatch(username or ""):
        return "שם משתמש: 2 עד 64 אותיות, ספרות, נקודה, מקף או @"
    return None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class Throttle:
    """Slows down password guessing: after 5 failed sign-ins within 15 minutes for the same user name or from the
    same address, the next try has to wait - one minute, doubling with every further failure, at most 15."""

    def __init__(self, limit: int = 5, window_s: float = 900.0):
        self.limit, self.window = limit, window_s
        self.fails: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def _recent(self, key: str, now: float) -> list[float]:
        xs = [t for t in self.fails.get(key, []) if now - t < self.window]
        if xs:
            self.fails[key] = xs
        else:
            self.fails.pop(key, None)
        return xs

    def wait(self, *keys: str) -> int:
        """Seconds until another try is allowed (0 = now)."""
        now = time.time()
        with self.lock:
            out = 0.0
            for k in keys:
                xs = self._recent(k, now)
                if len(xs) >= self.limit:
                    delay = min(900.0, 60.0 * 2 ** (len(xs) - self.limit))
                    out = max(out, xs[-1] + delay - now)
            return int(out + 0.999) if out > 0 else 0

    def fail(self, *keys: str) -> None:
        now = time.time()
        with self.lock:
            for k in keys:
                self._recent(k, now)
                self.fails.setdefault(k, []).append(now)
            if len(self.fails) > 10_000:         # a flood of names: keep memory bounded
                for k in list(self.fails)[:5_000]:
                    self.fails.pop(k, None)

    def ok(self, *keys: str) -> None:
        with self.lock:
            for k in keys:
                self.fails.pop(k, None)


# ---------------------------------------------------------------------------------------------- who may do what
PUBLIC = {"/api/auth/me", "/api/auth/login", "/api/auth/logout", "/api/auth/oidc/start", "/api/auth/oidc/callback"}
ENGINEER_WRITES = (re.compile(r"/api/decisions"), re.compile(r"/api/scan"), re.compile(r"/api/jobs/[^/]+/cancel"),
                   re.compile(r"/api/checks"), re.compile(r"/api/checks/sample/[^/]+"), re.compile(r"/api/checks/[^/]+"),
                   re.compile(r"/api/packages"))
ADMIN_READS = (re.compile(r"/api/settings"), re.compile(r"/api/users(/.*)?"), re.compile(r"/api/backup"), re.compile(r"/api/sources/[^/]+/discovery"))


def required_role(method: str, path: str) -> str | None:
    """What a request needs in team mode: None = nobody has to be signed in, "login" = any signed-in user,
    otherwise the lowest role that may do it."""
    if path in PUBLIC or not (path.startswith("/api/") or path.startswith("/sim/")):
        return None                              # the page itself and its files: the sign-in screen is part of it
    if path == "/api/auth/password":
        return "login"
    if method in ("GET", "HEAD", "OPTIONS"):
        return "admin" if any(p.fullmatch(path) for p in ADMIN_READS) else "viewer"
    if any(p.fullmatch(path) for p in ENGINEER_WRITES):
        return "engineer"
    return "admin"


def allowed(user: dict | None, need: str | None) -> bool:
    if need is None:
        return True
    if not user:
        return False
    return need == "login" or RANK.get(user.get("role"), -1) >= RANK[need]


def public_user(u: dict | None) -> dict | None:
    """A user as the API shows it: never the password hash."""
    if not u:
        return None
    return {"id": u["id"], "username": u["username"], "display_name": u.get("display_name") or u["username"],
            "email": u.get("email") or "", "role": u["role"], "role_he": ROLE_HE.get(u["role"], u["role"]),
            "password": bool(u.get("pw_hash")), "company": bool(u.get("oidc_sub")), "disabled": bool(u.get("disabled")),
            "created": u.get("created"), "last_login": u.get("last_login")}
