"""Team mode: passwords, sessions, roles on every endpoint, the sign-in throttle, and company sign-in (OpenID Connect)
against a provider simulated in the test (its keys are made here; no network)."""
import base64
import hashlib
import json
import random
import shutil
import subprocess
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from part_audit.server import auth, oidc


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    monkeypatch.setattr(auth, "ITERATIONS", 1_000)     # the real cost is checked in its own test
    oidc.clear_cache()


# ------------------------------------------------------------------------------------------------ passwords
def test_password_hashing_salts_and_verifies():
    assert auth.ITERATIONS == 1_000           # (patched) ...
    h1, h2 = auth.hash_password("סיסמה-ארוכה-1"), auth.hash_password("סיסמה-ארוכה-1")
    assert h1 != h2 and h1.startswith("pbkdf2_sha256$1000$")
    assert auth.verify_password("סיסמה-ארוכה-1", h1) and not auth.verify_password("סיסמה-ארוכה-2", h1)
    assert not auth.verify_password("x", None) and not auth.verify_password("x", "garbage")
    assert not auth.verify_password("x", "pbkdf2_sha256$10$AAAA$AAAA")      # too few iterations is not accepted


def test_the_default_cost_is_the_recommended_one():
    assert auth.DEFAULT_ITERATIONS >= 600_000
    h = auth.hash_password("Gear-box 42!", iterations=auth.DEFAULT_ITERATIONS)
    assert h.startswith(f"pbkdf2_sha256${auth.DEFAULT_ITERATIONS}$") and auth.verify_password("Gear-box 42!", h)


def test_password_and_username_rules():
    assert auth.password_problem("short") and auth.password_problem("12345678") and auth.password_problem("aaaaaaaa")
    assert auth.password_problem("dana.levi", "Dana.Levi")
    assert auth.password_problem("Gear-box 42!") is None
    assert auth.username_problem("דנה.לוי") is None and auth.username_problem("a") and auth.username_problem("a b")


def test_throttle_waits_after_five_failures_and_doubles():
    t = auth.Throttle(limit=5)
    for _ in range(4):
        t.fail("u:dana")
    assert t.wait("u:dana") == 0
    t.fail("u:dana")
    assert 55 <= t.wait("u:dana") <= 60
    t.fail("u:dana")
    assert 115 <= t.wait("u:dana") <= 120
    t.ok("u:dana")
    assert t.wait("u:dana") == 0


def test_required_roles():
    r = auth.required_role
    assert r("GET", "/") is None and r("GET", "/assets/js/app.js") is None and r("POST", "/api/auth/login") is None
    assert r("GET", "/api/runs/latest/groups") == "viewer" and r("GET", "/api/runs/x/export.xlsx") == "viewer"
    assert r("POST", "/api/decisions") == "engineer" and r("POST", "/api/scan") == "engineer"
    assert r("POST", "/api/checks") == "engineer" and r("DELETE", "/api/checks/abc") == "engineer"
    assert r("PUT", "/api/settings") == "admin" and r("GET", "/api/settings") == "admin"
    assert r("POST", "/api/sources") == "admin" and r("DELETE", "/api/sources/s1") == "admin"
    assert r("GET", "/api/users") == "admin" and r("PUT", "/api/users/3") == "admin"
    assert r("POST", "/api/auth/password") == "login" and r("POST", "/api/auth/oidc/test") == "admin"
    assert r("POST", "/api/something/new") == "admin"          # anything not listed needs the highest role


# ------------------------------------------------------------------------------------------------ RS256
SMALL_PRIMES = [p for p in range(3, 2000, 2) if all(p % q for q in range(3, int(p ** 0.5) + 1, 2))]


def _prime(bits: int, rng: random.Random) -> int:
    while True:
        c = rng.getrandbits(bits) | (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if any(c % p == 0 for p in SMALL_PRIMES):
            continue
        d, s = c - 1, 0
        while d % 2 == 0:
            d, s = d // 2, s + 1
        for _ in range(24):
            x = pow(rng.randrange(2, c - 2), d, c)
            if x in (1, c - 1):
                continue
            for _ in range(s - 1):
                x = pow(x, 2, c)
                if x == c - 1:
                    break
            else:
                break
        else:
            return c


def rsa_key(bits: int = 2048, seed: int = 1) -> dict:
    rng = random.Random(seed)
    e = 65537
    while True:
        p, q = _prime(bits // 2, rng), _prime(bits // 2, rng)
        phi = (p - 1) * (q - 1)
        if p != q and phi % e and (p * q).bit_length() == bits:
            return {"n": p * q, "e": e, "d": pow(e, -1, phi)}


def sign(key: dict, msg: bytes) -> bytes:
    k = (key["n"].bit_length() + 7) // 8
    t = oidc.SHA256_PREFIX + hashlib.sha256(msg).digest()
    em = b"\x00\x01" + b"\xff" * (k - len(t) - 3) + b"\x00" + t
    return pow(int.from_bytes(em, "big"), key["d"], key["n"]).to_bytes(k, "big")


def jwk(key: dict, kid: str) -> dict:
    n = key["n"].to_bytes((key["n"].bit_length() + 7) // 8, "big")
    return {"kty": "RSA", "kid": kid, "use": "sig", "alg": "RS256", "n": oidc.b64url(n), "e": oidc.b64url(b"\x01\x00\x01")}


def jwt(key: dict, claims: dict, kid: str = "k1", alg: str = "RS256") -> str:
    h = oidc.b64url(json.dumps({"alg": alg, "kid": kid, "typ": "JWT"}).encode())
    c = oidc.b64url(json.dumps(claims).encode())
    return f"{h}.{c}.{oidc.b64url(sign(key, f'{h}.{c}'.encode()))}"


@pytest.fixture(scope="module")
def key():
    return rsa_key(2048, seed=7)


def test_rsa_signature_check(key):
    msg = b"header.payload"
    s = sign(key, msg)
    assert oidc.rsa_verify(key["n"], key["e"], msg, s)
    assert not oidc.rsa_verify(key["n"], key["e"], b"header.payloaD", s)
    bad = bytearray(s)
    bad[-1] ^= 1
    assert not oidc.rsa_verify(key["n"], key["e"], msg, bytes(bad))
    assert not oidc.rsa_verify(key["n"], key["e"], msg, s[1:])             # wrong length
    small = rsa_key(1024, seed=3)
    assert not oidc.rsa_verify(small["n"], small["e"], msg, sign(small, msg))    # keys under 2048 bits are refused


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl not installed")
def test_rsa_signature_check_agrees_with_openssl(tmp_path):
    """A signature made by OpenSSL (an independent implementation) passes; the same with another message fails."""
    k = tmp_path / "k.pem"
    subprocess.run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", str(k)],
                   check=True, capture_output=True)
    (tmp_path / "m").write_bytes(b"eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0")
    sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(k), str(tmp_path / "m")], check=True,
                         capture_output=True).stdout
    txt = subprocess.run(["openssl", "rsa", "-in", str(k), "-noout", "-modulus"], check=True, capture_output=True,
                         text=True).stdout
    n = int(txt.strip().split("=", 1)[1], 16)
    assert oidc.rsa_verify(n, 65537, b"eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxIn0", sig)
    assert not oidc.rsa_verify(n, 65537, b"eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIyIn0", sig)


def _claims(**kw):
    now = int(time.time())
    return {"iss": "https://idp.example.com", "aud": "partaudit", "sub": "u-1", "nonce": "n1", "iat": now,
            "exp": now + 300, "email": "dana@factory.co.il", "name": "דנה לוי", **kw}


def test_id_token_checks(key):
    keys = [jwk(key, "k1")]
    kw = dict(keys=keys, issuer="https://idp.example.com", client_id="partaudit", nonce="n1")
    assert oidc.verify_id_token(jwt(key, _claims()), **kw)["sub"] == "u-1"
    for bad, msg in [(_claims(iss="https://evil.example.com"), "ספק אחר"), (_claims(aud="other"), "Client ID"),
                     (_claims(aud=["partaudit", "other"]), "Client ID"), (_claims(exp=int(time.time()) - 600), "פג"),
                     (_claims(iat=int(time.time()) + 3600), "עדיין לא"), (_claims(nonce="n2"), "לא שייך"),
                     (_claims(sub=""), "מזהה")]:
        with pytest.raises(oidc.OIDCError, match=msg):
            oidc.verify_id_token(jwt(key, bad), **kw)
    assert oidc.verify_id_token(jwt(key, _claims(aud=["partaudit", "other"], azp="partaudit")), **kw)
    # alg "none" and HMAC are refused before anything else; an unknown key id asks for the keys again
    h = oidc.b64url(json.dumps({"alg": "none"}).encode())
    with pytest.raises(oidc.OIDCError, match="לא נתמך"):
        oidc.verify_id_token(f"{h}.{oidc.b64url(json.dumps(_claims()).encode())}.", **kw)
    with pytest.raises(oidc.OIDCError, match="לא נתמך"):
        oidc.verify_id_token(jwt(key, _claims(), alg="HS256"), **kw)
    with pytest.raises(oidc.UnknownKey):
        oidc.verify_id_token(jwt(key, _claims(), kid="k9"), **kw)
    other = rsa_key(2048, seed=11)
    with pytest.raises(oidc.OIDCError, match="החתימה"):
        oidc.verify_id_token(jwt(other, _claims()), **kw)          # signed by someone else with the same key id


def test_identity_and_domains():
    cfg = {"domains": "factory.co.il"}
    ident = oidc.identity(cfg, _claims())
    assert ident == {"sub": "https://idp.example.com|u-1", "email": "dana@factory.co.il", "login": "", "name": "דנה לוי",
                     "email_trusted": True}                    # not said to be verified, but in the company domain
    with pytest.raises(oidc.OIDCError, match="דומיין"):
        oidc.identity(cfg, _claims(email="x@gmail.com"))
    for v in (False, "false", "FALSE"):
        with pytest.raises(oidc.OIDCError, match="אומתה"):
            oidc.identity({}, _claims(email_verified=v))
    # without a company domain only a verified e-mail may identify an existing account
    assert oidc.identity({}, _claims())["email_trusted"] is False
    assert oidc.identity({}, _claims(email_verified=True))["email_trusted"] is True
    assert oidc.identity({}, _claims(email_verified="true"))["email_trusted"] is True
    # Microsoft Entra ID without the e-mail claim: the sign-in name names a new account, it never identifies one
    ent = oidc.identity(cfg, {**_claims(email=None), "preferred_username": "Dana@Factory.co.il"})
    assert ent["email"] == "" and ent["login"] == "dana@factory.co.il" and ent["email_trusted"] is False
    with pytest.raises(oidc.OIDCError, match="דומיין"):
        oidc.identity(cfg, {**_claims(email=None), "preferred_username": "dana@other.com"})


def test_provider_addresses_must_be_https():
    with pytest.raises(oidc.OIDCError, match="https"):
        oidc._check_url("http://idp.example.com")
    oidc._check_url("https://login.microsoftonline.com/tenant/v2.0")
    oidc._check_url("http://127.0.0.1:8080/realms/test")       # a provider on this computer (tests, local Keycloak)


# ------------------------------------------------------------------------------------------------ the team server
@pytest.fixture
def team(tmp_path):
    from fastapi.testclient import TestClient

    from part_audit.server.app import create_app
    from part_audit.server.store import Store
    ws = tmp_path / "ws"
    st = Store(ws)
    for name, role in (("admin", "admin"), ("eng", "engineer"), ("view", "viewer")):
        st.add_user(name, role, display_name=f"{name} name", pw_hash=auth.hash_password(f"{name}-Passw0rd"))
    app = create_app(ws, factory_dir=None, demo=False, team=True)
    with TestClient(app, base_url="http://partaudit.factory.local:8765") as c:
        yield c, st


def _login(c, name):
    r = c.post("/api/auth/login", json={"username": name, "password": f"{name}-Passw0rd"})
    assert r.status_code == 200, r.text
    return r.json()["user"]


def test_local_mode_is_unchanged(tmp_path):
    from fastapi.testclient import TestClient

    from part_audit.server.app import create_app
    app = create_app(tmp_path / "ws", factory_dir=None, demo=False)
    c = TestClient(app, base_url="http://partaudit.factory.local:8765")
    assert c.get("/api/status").status_code == 403           # another computer: refused, as before
    c = TestClient(app, base_url="http://127.0.0.1:8765")
    st = c.get("/api/status").json()
    assert st["team"] is False and st["user"] is None
    assert c.get("/api/auth/me").json()["team"] is False
    assert c.post("/api/auth/login", json={"username": "x", "password": "y"}).status_code == 400
    # the first admin can be created here, before the team server is started
    r = c.post("/api/users", json={"username": "admin", "role": "admin", "password": "Gear-box 42!"})
    assert r.status_code == 200 and r.json()["role"] == "admin" and "pw_hash" not in r.json()
    assert c.get("/api/users").json()["admins"] == 1


def test_sign_in_is_needed_and_roles_are_enforced(team):
    c, st = team
    assert c.get("/").status_code == 200 and c.get("/assets/js/app.js").status_code == 200   # the sign-in screen
    r = c.get("/api/status")
    assert r.status_code == 401 and r.json()["login"] is True
    assert c.get("/api/auth/me").json() == {"team": True, "user": None, "roles": auth.ROLE_HE,
                                              "oidc": {"enabled": False, "label": "כניסה עם חשבון החברה"}}
    assert c.post("/api/auth/login", json={"username": "view", "password": "wrong-password"}).status_code == 401

    me = _login(c, "view")
    assert me["role"] == "viewer" and me["display_name"] == "view name"
    st_ = c.get("/api/status").json()
    assert st_["user"]["username"] == "view" and "email" not in st_["settings"] and st_["workspace"] == ""
    for method, path in (("POST", "/api/decisions"), ("POST", "/api/scan"), ("GET", "/api/settings"),
                         ("PUT", "/api/settings"), ("POST", "/api/sources"), ("GET", "/api/users")):
        r = c.request(method, path, json={})
        assert r.status_code == 403 and "צפייה" not in r.json()["error"], (method, path)
    assert c.get("/api/runs").status_code == 200

    c.post("/api/auth/logout")
    assert c.get("/api/status").status_code == 401
    _login(c, "eng")
    r = c.post("/api/decisions", json={"target_type": "group", "target_id": "G1", "decision": "approve"})
    assert r.status_code == 404                           # allowed: refused only because there is no scan yet
    assert c.post("/api/scan").status_code != 403
    assert c.put("/api/settings", json={}).status_code == 403

    c.post("/api/auth/logout")
    _login(c, "admin")
    assert c.get("/api/settings").json()["team"] is True
    users = c.get("/api/users").json()["users"]
    assert {u["username"] for u in users} == {"admin", "eng", "view"} and not any("pw_hash" in u for u in users)


def test_decisions_record_the_signed_in_user(team, tmp_path):
    c, st = team
    _login(c, "eng")
    st.add_decision("issue", "Q1", "approve", user="ignored")      # (direct, for comparison)
    r = c.post("/api/decisions", json={"target_type": "issue", "target_id": "Q2", "decision": "approve",
                                       "user": "somebody else"})
    assert r.status_code == 200
    assert st.current_decisions()["issue:Q2"]["user"] == "eng name"    # the account, not what the page sent


def test_other_sites_and_the_demo_systems_are_refused(team):
    c, st = team
    _login(c, "admin")
    r = c.post("/api/users", json={"username": "x1", "role": "viewer", "password": "Gear-box 42!"},
               headers={"Origin": "http://evil.example.com"})
    assert r.status_code == 403
    r = c.post("/api/users", json={"username": "x1", "role": "viewer", "password": "Gear-box 42!"},
               headers={"Origin": "http://partaudit.factory.local:8765"})
    assert r.status_code == 200
    assert c.get("/sim/vault/AutodeskDM/Services/api/vault/v2/vaults").status_code == 403   # not from the network


def test_throttle_on_the_server(team):
    c, st = team
    for _ in range(5):
        assert c.post("/api/auth/login", json={"username": "eng", "password": "nope-nope-nope"}).status_code == 401
    r = c.post("/api/auth/login", json={"username": "eng", "password": "eng-Passw0rd"})
    assert r.status_code == 429 and "דקות" in r.json()["error"]


def test_password_change_ends_other_sessions_and_admins_stay(team):
    from fastapi.testclient import TestClient
    c, st = team
    _login(c, "eng")
    other = TestClient(c.app, base_url="http://partaudit.factory.local:8765")
    _login(other, "eng")
    assert c.post("/api/auth/password", json={"current": "wrong", "new": "New-Passw0rd-2"}).status_code == 400
    assert c.post("/api/auth/password", json={"current": "eng-Passw0rd", "new": "12345678"}).status_code == 400
    assert c.post("/api/auth/password", json={"current": "eng-Passw0rd", "new": "New-Passw0rd-2"}).json()["ok"]
    assert c.get("/api/status").status_code == 200 and other.get("/api/status").status_code == 401

    c.post("/api/auth/logout")
    _login(c, "admin")
    admin_id = st.find_user("admin")["id"]
    r = c.put(f"/api/users/{admin_id}", json={"role": "viewer"})
    assert r.status_code == 400 and "מנהל" in r.json()["error"]          # the last admin
    view_id = st.find_user("view")["id"]
    assert c.put(f"/api/users/{view_id}", json={"disabled": True}).json()["disabled"] is True
    assert c.post("/api/auth/login", json={"username": "view", "password": "view-Passw0rd"}).status_code == 403


def test_cli_users_and_server_needs_an_admin(tmp_path, monkeypatch, capsys):
    import io

    from part_audit.cli import main
    ws = str(tmp_path / "ws")
    assert main(["serve", "--workspace", ws]) == 2
    assert "admin" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO("Gear-box 42!\n"))
    assert main(["users", "add", "dana", "--role", "admin", "--display", "דנה", "--password-stdin", "--workspace", ws]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("12345678\n"))
    assert main(["users", "add", "yossi", "--password-stdin", "--workspace", ws]) == 2
    assert main(["users", "role", "dana", "viewer", "--workspace", ws]) == 2        # the last admin stays
    assert main(["users", "list", "--workspace", ws]) == 0
    assert "dana" in capsys.readouterr().out


# ------------------------------------------------------------------------------------------------ company sign-in
class FakeProvider:
    """The provider's three addresses, answered in-process: discovery, keys, token endpoint."""

    def __init__(self, key, kid="k1"):
        self.key, self.kid = key, kid
        self.issuer = "https://idp.example.com"
        self.codes: dict[str, dict] = {}
        self.calls: list[tuple] = []

    def http_json(self, url, data=None, headers=None, timeout=10.0):
        self.calls.append((url, data, headers))
        if url == self.issuer + "/.well-known/openid-configuration":
            return {"issuer": self.issuer, "authorization_endpoint": self.issuer + "/authorize",
                    "token_endpoint": self.issuer + "/token", "jwks_uri": self.issuer + "/keys",
                    "token_endpoint_auth_methods_supported": ["client_secret_basic"],
                    "id_token_signing_alg_values_supported": ["RS256"], "code_challenge_methods_supported": ["S256"]}
        if url == self.issuer + "/keys":
            return {"keys": [jwk(self.key, self.kid)]}
        if url == self.issuer + "/token":
            want = "Basic " + base64.b64encode(b"partaudit:s3cret").decode()
            if headers.get("Authorization") != want:
                raise oidc.OIDCError("ספק הזהות החזיר שגיאה 401: invalid_client")
            c = self.codes.pop(data["code"], None)
            if not c or oidc.b64url(hashlib.sha256(data["code_verifier"].encode()).digest()) != c["challenge"]:
                raise oidc.OIDCError("ספק הזהות החזיר שגיאה 400: invalid_grant")
            return {"id_token": jwt(self.key, c["claims"], kid=self.kid), "access_token": "x"}
        raise AssertionError(url)

    def sign_in(self, c, **claims):
        """The browser's trip: our start page -> the provider (signs the user in) -> our callback."""
        r = c.get("/api/auth/oidc/start", follow_redirects=False)
        assert r.status_code == 302, r.text
        q = {k: v[0] for k, v in parse_qs(urlsplit(r.headers["location"]).query).items()}
        assert r.headers["location"].startswith(self.issuer + "/authorize?")
        assert q["code_challenge_method"] == "S256" and q["scope"] == "openid email profile"
        assert q["redirect_uri"] == "http://partaudit.factory.local:8765/api/auth/oidc/callback"
        code = f"code-{len(self.codes)}-{random.random()}"
        now = int(time.time())
        self.codes[code] = {"challenge": q["code_challenge"],
                            "claims": {"iss": self.issuer, "aud": "partaudit", "nonce": q["nonce"], "iat": now,
                                       "exp": now + 300, "sub": "u-1", "email": "dana@factory.co.il",
                                       "name": "דנה לוי", **claims}}
        return c.get("/api/auth/oidc/callback", params={"code": code, "state": q["state"]}, follow_redirects=False), q


def _error(r) -> str:
    """The message the sign-in screen shows after a failed company sign-in."""
    assert r.status_code == 303 and r.headers["location"].startswith("/?login_error=")
    return parse_qs(urlsplit(r.headers["location"]).query)["login_error"][0]


def test_company_sign_in_end_to_end(team, key, monkeypatch):
    c, st = team
    idp = FakeProvider(key)
    monkeypatch.setattr(oidc, "http_json", idp.http_json)
    _login(c, "admin")
    r = c.put("/api/settings", json={"oidc": {"enabled": True, "issuer": "https://idp.example.com/", "client_id": "partaudit",
                                              "client_secret": "s3cret", "domains": "factory.co.il"}})
    assert r.status_code == 200 and r.json()["oidc"]["client_secret"] == "••••••" and "s3cret" not in r.text
    assert c.post("/api/auth/oidc/test").json()["keys"] == 1
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").json()["oidc"]["enabled"] is True

    r, q = idp.sign_in(c)
    assert r.status_code == 303 and r.headers["location"] == "/"
    me = c.get("/api/auth/me").json()["user"]
    assert me["username"] == "dana@factory.co.il" and me["role"] == "viewer" and me["company"] and not me["password"]
    assert me["display_name"] == "דנה לוי"
    assert c.post("/api/decisions", json={"target_type": "issue", "target_id": "Q", "decision": "approve"}).status_code == 403

    # the same person again: the same account; a code is good once; another domain is refused
    c.post("/api/auth/logout")
    r, _ = idp.sign_in(c)
    assert r.status_code == 303 and len(st.list_users()) == 4
    r = c.get("/api/auth/oidc/callback", params={"code": "code-0-x", "state": q["state"]}, follow_redirects=False)
    assert "לא הושלמה" in _error(r)
    c.post("/api/auth/logout")
    r, _ = idp.sign_in(c, sub="u-2", email="x@gmail.com")
    assert "דומיין" in _error(r) and c.get("/api/auth/me").json()["user"] is None


def test_company_sign_in_refuses_tampering(team, key, monkeypatch):
    c, st = team
    idp = FakeProvider(key)
    monkeypatch.setattr(oidc, "http_json", idp.http_json)
    st.set_settings({"oidc": {**oidc.DEFAULT_OIDC, "enabled": True, "issuer": "https://idp.example.com",
                              "client_id": "partaudit"}})
    st.set_secret(oidc.SECRET, "s3cret")
    # a callback with a state this browser did not start
    r = c.get("/api/auth/oidc/start", follow_redirects=False)
    state = parse_qs(urlsplit(r.headers["location"]).query)["state"][0]
    c.cookies.clear()
    r = c.get("/api/auth/oidc/callback", params={"code": "c", "state": state}, follow_redirects=False)
    assert "לא הושלמה" in _error(r)
    # a token signed with a key the provider does not publish
    idp.key = rsa_key(2048, seed=11)
    real_jwks = idp.http_json

    def keys_of_the_real_provider(url, data=None, headers=None, timeout=10.0):
        if url.endswith("/keys"):
            return {"keys": [jwk(key, "k1")]}
        return real_jwks(url, data, headers, timeout)
    monkeypatch.setattr(oidc, "http_json", keys_of_the_real_provider)
    r, _ = idp.sign_in(c)
    assert "החתימה" in _error(r) and c.get("/api/auth/me").json()["user"] is None
    # an account an admin added for company sign-in (no password) is linked by a verified e-mail, and keeps its role;
    # without auto-create a stranger is refused
    idp.key = key
    st.add_user("dana@factory.co.il", "engineer", pw_hash=None)
    st.set_settings({"oidc": {**oidc.DEFAULT_OIDC, "enabled": True, "issuer": "https://idp.example.com",
                              "client_id": "partaudit", "auto_create": False}})
    monkeypatch.setattr(oidc, "http_json", idp.http_json)
    r, _ = idp.sign_in(c)                                  # the provider does not say the e-mail is verified
    assert "עוד לא נוסף" in _error(r)
    r, _ = idp.sign_in(c, email_verified=True)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert c.get("/api/auth/me").json()["user"]["role"] == "engineer"
    c.post("/api/auth/logout")
    r, _ = idp.sign_in(c, sub="u-3", email="new@factory.co.il", email_verified=True)
    assert "עוד לא נוסף" in _error(r)


def test_company_sign_in_never_takes_over_a_password_account(team, key, monkeypatch):
    c, st = team
    idp = FakeProvider(key)
    monkeypatch.setattr(oidc, "http_json", idp.http_json)
    st.add_user("boss@factory.co.il", "admin", pw_hash=auth.hash_password("Boss-Passw0rd!"))
    st.set_settings({"oidc": {**oidc.DEFAULT_OIDC, "enabled": True, "issuer": "https://idp.example.com",
                              "client_id": "partaudit", "auto_create": True, "domains": "factory.co.il"}})
    st.set_secret(oidc.SECRET, "s3cret")
    # another identity whose sign-in name was chosen to match: a new viewer account, not the admin
    r, _ = idp.sign_in(c, sub="someone-else", email=None, preferred_username="boss@factory.co.il")
    assert r.status_code == 303 and r.headers["location"] == "/"
    me = c.get("/api/auth/me").json()["user"]
    assert me["role"] == "viewer" and me["username"] != "boss@factory.co.il" and not me["password"]
    c.post("/api/auth/logout")
    # even a verified e-mail does not link to an account that signs in with a password
    r, _ = idp.sign_in(c, sub="boss-sub", email="boss@factory.co.il", email_verified=True)
    assert "סיסמה" in _error(r) and c.get("/api/auth/me").json()["user"] is None
    assert st.find_user("boss@factory.co.il")["oidc_sub"] is None


@pytest.mark.parametrize("host", ["x?", "x#", "partaudit.factory.local:8765?a=/", "a b", "evil.com/api", ""])
def test_a_malformed_host_header_is_refused(team, host):
    """Some framework versions rebuild the request's address from the Host header; a '?' in it used to make that
    address's path disagree with the routed one. Such a Host is refused before anything else."""
    c, st = team
    r = c.post("/api/users", json={"username": "mallory", "role": "admin", "password": "Mallory-Passw0rd!"},
               headers={"host": host})
    assert r.status_code == 400 and st.find_user("mallory") is None


def test_path_variants_do_not_skip_the_sign_in(team):
    c, st = team
    for path in ("/api/users", "/api/%75sers", "/api/users/", "/api/settings", "/api/auth/me/../../users"):
        assert c.get(path).status_code in (401, 404, 307), path
    assert c.get("//api/users").status_code == 404 and c.get("/API/users").status_code == 404


def test_admin_moves_a_user_to_company_sign_in(team, key, monkeypatch):
    c, st = team
    idp = FakeProvider(key)
    monkeypatch.setattr(oidc, "http_json", idp.http_json)
    _login(c, "admin")
    c.put("/api/settings", json={"oidc": {"enabled": True, "issuer": "https://idp.example.com", "client_id": "partaudit",
                                          "client_secret": "s3cret", "auto_create": False}})
    eng = st.find_user("eng")
    assert c.put(f"/api/users/{eng['id']}", json={"company_only": True}).status_code == 400      # no e-mail yet
    r = c.put(f"/api/users/{eng['id']}", json={"company_only": True, "email": "Dana@Factory.co.il"})
    assert r.status_code == 200 and r.json()["password"] is False and r.json()["email"] == "dana@factory.co.il"
    admin = st.find_user("admin")
    assert c.put(f"/api/users/{admin['id']}", json={"company_only": True, "email": "a@factory.co.il"}).status_code == 400
    # a new account for company sign-in only
    r = c.post("/api/users", json={"username": "yossi@factory.co.il", "role": "viewer", "company": True})
    assert r.status_code == 200 and r.json()["password"] is False
    assert c.post("/api/users", json={"username": "noam", "role": "viewer", "company": True}).status_code == 400
    c.post("/api/auth/logout")
    assert c.post("/api/auth/login", json={"username": "eng", "password": "eng-Passw0rd"}).status_code == 401
    r, _ = idp.sign_in(c, sub="eng-sub", email="dana@factory.co.il", email_verified=True)
    me = c.get("/api/auth/me").json()["user"]
    assert r.headers["location"] == "/" and me["username"] == "eng" and me["role"] == "engineer" and me["company"]
