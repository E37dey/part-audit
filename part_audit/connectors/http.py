"""HTTP client for connectors that can only read.

Every connector declares which non-GET calls it needs (logins, search endpoints that the
vendor implemented as POST, logouts). Anything else that is not GET/HEAD raises before a
request leaves the machine - the audit cannot change data in a PDM, PLM or ERP even by
mistake.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urljoin, urlsplit

import httpx


class WriteBlocked(RuntimeError):
    """A connector tried a request that is not on its read-only allow-list."""


class ConnectorError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, detail: str = ""):
        super().__init__(message)
        self.status = status
        self.detail = detail


class ReadOnlyHttp:
    def __init__(self, base_url: str, allowed: list[tuple[str, str]] | None = None, timeout: float = 30.0,
                 verify: bool | str = True, auth=None, headers: dict | None = None, retries: int = 2,
                 trust_env: bool = True):
        """allowed: [(METHOD, regex on the URL path)] for methods other than GET/HEAD."""
        self.base_url = base_url.rstrip("/") + "/"
        self.allowed = [(m.upper(), re.compile(rx)) for m, rx in (allowed or [])]
        self.retries = retries
        # the guard also runs on every request httpx sends by itself (redirects), not only on the first one
        hook = lambda req: self._check(req.method, str(req.url))  # noqa: E731
        # a local address (the demo simulators, a server on this computer) is never sent through a proxy
        local = (urlsplit(self.base_url).hostname or "") in ("127.0.0.1", "localhost", "::1")
        self.client = httpx.Client(timeout=timeout, verify=verify, auth=auth, headers=headers or {},
                                   follow_redirects=True, trust_env=trust_env and not local,
                                   event_hooks={"request": [hook]})
        self.calls = 0
        self.log: list[str] = []

    def url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        if path.startswith("/"):
            parts = urlsplit(self.base_url)
            return f"{parts.scheme}://{parts.netloc}{path}"
        return urljoin(self.base_url, path)

    def _check(self, method: str, url: str) -> None:
        m = method.upper()
        if m in ("GET", "HEAD"):
            return
        path = urlsplit(url).path
        for am, rx in self.allowed:
            if am == m and rx.search(path):
                return
        raise WriteBlocked(f"{m} {path} is not on the read-only allow-list of this connector")

    def request(self, method: str, path: str, **kw) -> httpx.Response:
        url = self.url(path)
        self._check(method, url)
        last = None
        for attempt in range(self.retries + 1):
            try:
                self.calls += 1
                r = self.client.request(method, url, **kw)
                self.log.append(f"{method} {urlsplit(url).path} -> {r.status_code}")
                if r.status_code in (429, 502, 503, 504) and attempt < self.retries:
                    time.sleep(float(r.headers.get("Retry-After", "1") or 1))
                    continue
                return r
            except httpx.TransportError as exc:
                last = exc
                if attempt < self.retries:
                    time.sleep(0.5 * (attempt + 1))
                    continue
        raise ConnectorError(f"השרת לא זמין: {last}", detail=str(last))

    def get(self, path: str, **kw) -> httpx.Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw) -> httpx.Response:
        return self.request("POST", path, **kw)

    def delete(self, path: str, **kw) -> httpx.Response:
        return self.request("DELETE", path, **kw)

    def json(self, method: str, path: str, ok=(200,), **kw):
        r = self.request(method, path, **kw)
        if r.status_code not in ok:
            raise ConnectorError(http_error_he(r.status_code), status=r.status_code, detail=r.text[:500])
        try:
            return r.json()
        except ValueError as exc:
            raise ConnectorError("התשובה מהשרת אינה JSON תקין", status=r.status_code, detail=r.text[:300]) from exc

    def download(self, path: str, dest, **kw) -> int:
        """Download to dest atomically: a broken transfer never leaves a partial file that later runs would reuse."""
        import os
        from pathlib import Path
        url = self.url(path)
        self._check("GET", url)
        self.calls += 1
        dest = Path(dest)
        tmp = dest.with_name(dest.name + ".part")
        n = 0
        try:
            with self.client.stream("GET", url, **kw) as r:
                if r.status_code != 200:
                    raise ConnectorError(http_error_he(r.status_code), status=r.status_code)
                expected = r.headers.get("content-length")
                with open(tmp, "wb") as fh:
                    for chunk in r.iter_bytes():
                        fh.write(chunk)
                        n += len(chunk)
            if expected and expected.isdigit() and int(expected) != n and not r.headers.get("content-encoding"):
                raise ConnectorError(f"ההורדה נקטעה ({n} מתוך {expected} בתים)")
            os.replace(tmp, dest)
        except httpx.TransportError as exc:
            raise ConnectorError(f"ההורדה נכשלה: {exc}", detail=str(exc)) from exc
        finally:
            if tmp.exists():
                tmp.unlink()
        return n

    def close(self) -> None:
        self.client.close()


def http_error_he(status: int) -> str:
    return {
        400: "הבקשה נדחתה על ידי השרת (400) – ייתכן ששם שדה או טופס שגוי",
        401: "שם משתמש או סיסמה שגויים (401)",
        403: "אין הרשאה לפעולה הזו (403) – בדקו הרשאות קריאה למשתמש",
        404: "הכתובת לא נמצאה בשרת (404) – בדקו את כתובת השרת והגרסה",
        429: "השרת מגביל את קצב הבקשות (429) – נסו שוב מאוחר יותר",
        500: "שגיאה בשרת (500)",
    }.get(status, f"שגיאת HTTP {status}")
