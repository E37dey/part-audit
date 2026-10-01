"""L4 - OPTIONAL, off by default: LLM explanations for candidate mappings.

Only used when ``--llm-endpoint`` is given. It talks to an OpenAI-compatible
chat endpoint (e.g. a local Ollama / LM Studio / vLLM server). By default only
localhost endpoints are accepted; anything else needs ``--llm-allow-remote``.

What is sent: for each proposed PN mapping and for ambiguous name pairs, the part
numbers, file *names* (no folders), ERP descriptions and the tool's own reason
text. Never CAD files, geometry, or folder paths. The answers are advisory notes
in the report; they do not change any score or classification.
"""
from __future__ import annotations

import json
import urllib.request
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "[::1]"}

SYSTEM_PROMPT = (
    "You help an engineer review part-number cleanup proposals. Answer in one or two short sentences, "
    "plain language, no markdown. Do not invent facts beyond the data given."
)


def is_local(endpoint: str) -> bool:
    host = (urlparse(endpoint).hostname or "").lower()
    return host in LOCAL_HOSTS


def chat(endpoint: str, model: str, prompt: str, timeout: float = 60.0) -> str:
    body = json.dumps({"model": model, "temperature": 0,
                       "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                                    {"role": "user", "content": prompt}]}).encode("utf-8")
    url = endpoint.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
    # never route through HTTP(S)_PROXY: a local endpoint must stay on this machine
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=timeout) as resp:  # noqa: S310 (user-configured endpoint)
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def _file_names(res, ids: str) -> list[str]:
    out = []
    for fid in [x.strip() for x in ids.split(";") if x.strip()]:
        it = res.items.get(fid)
        out.append(it.rec.filename if it else fid.rsplit("/", 1)[-1])
    return out


def mapping_prompt(res, row: dict) -> str:
    def desc(pn):
        for r in res.erp_rows:
            if r["part_number"] == pn:
                return r.get("description", "")
        return ""
    return (f"Proposed change: part number {row['old_pn'] or '(none)'} -> {row['proposed_pn']}.\n"
            f"Old PN ERP description: {desc(row['old_pn'])!r}; proposed PN ERP description: {desc(row['proposed_pn'])!r}.\n"
            f"Files with old PN: {', '.join(_file_names(res, row['files_old']))}.\n"
            f"Files with proposed PN: {', '.join(_file_names(res, row['files_proposed']))}.\n"
            f"Tool evidence: {row['reason']} (confidence {row['confidence']}).\n"
            "Explain to the reviewer why these are probably the same part and what they should double-check.")


def explain_mappings(res, endpoint: str, model: str, allow_remote: bool = False, max_rows: int = 200) -> dict:
    """Return {'mapping': {row_index: text}, 'errors': [...]} - advisory only."""
    if not is_local(endpoint) and not allow_remote:
        raise ValueError(f"LLM endpoint {endpoint} is not localhost; pass --llm-allow-remote to use it")
    notes: dict = {"mapping": {}, "errors": [], "endpoint": endpoint, "model": model}
    for i, row in enumerate(res.mapping[:max_rows]):
        try:
            notes["mapping"][i] = chat(endpoint, model, mapping_prompt(res, row))
        except Exception as exc:  # the audit never fails because of the optional LLM
            notes["errors"].append(f"row {i}: {type(exc).__name__}: {exc}")
            if len(notes["errors"]) >= 3:
                break
    return notes
