from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pff_content.config import get_pff_api_key

API_BASE = "https://api.pff.com"


def pff_api_key() -> str:
    return get_pff_api_key()


def safe_headers(headers: dict[str, str]) -> dict[str, str]:
    allowed = {"content-type", "x-request-id", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset", "retry-after"}
    return {key: value for key, value in headers.items() if key.lower() in allowed}


def request_json(path: str, *, key: str, params: dict[str, Any] | None = None) -> tuple[int, dict[str, str], Any]:
    url = f"{API_BASE}{path}"
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"Accept": "application/json", "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
            body = json.loads(raw.decode("utf-8") or "{}")
            return response.status, dict(response.headers), body
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {"non_json_body_length": len(raw)}
        return exc.code, dict(exc.headers), body


def first_table(body: Any) -> tuple[str, int, list[str]]:
    if not isinstance(body, dict):
        return "", 0, []
    for key, value in body.items():
        if isinstance(value, list):
            first = value[0] if value and isinstance(value[0], dict) else {}
            return key, len(value), list(first)[:25]
    return "", 0, []


def main() -> None:
    key = pff_api_key()
    status, headers, body = request_json("/v1/auth/whoami", key=key)
    safe_body = {}
    if isinstance(body, dict):
        for field in ["tier", "entitled", "credential", "credential_type", "type"]:
            if field in body:
                value = body[field]
                safe_body[field] = {"type": value.get("type")} if isinstance(value, dict) else value
    print(f"[auth_status] {status}")
    print(f"[auth_safe_body] {json.dumps(safe_body, sort_keys=True)}")
    print(f"[auth_safe_headers] {json.dumps(safe_headers(headers), sort_keys=True)}")
    if status != 200:
        raise SystemExit(1)
    for name, path in [
        ("games", "/v1/games"),
        ("passing", "/v1/facet/passing/summary"),
        ("receiving", "/v1/facet/receiving/summary"),
    ]:
        sample_status, _, sample_body = request_json(path, key=key, params={"league": "nfl", "season": 2026, "week": 1})
        table, rows, fields = first_table(sample_body)
        print(f"[sample] {name} status={sample_status} table={table} rows={rows} fields={fields}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[error] {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
