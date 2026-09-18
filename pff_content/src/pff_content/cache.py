from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .paths import raw_week_dir


def canonical_params(params: dict[str, Any] | None) -> dict[str, Any]:
    if not params:
        return {}
    return {str(key): params[key] for key in sorted(params)}


def request_hash(path: str, params: dict[str, Any] | None = None) -> str:
    payload = {"path": path, "params": canonical_params(params)}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]


def endpoint_slug(path: str) -> str:
    text = path.strip("/").replace("/", "__")
    text = re.sub(r"[^A-Za-z0-9_]+", "_", text)
    return text.lower()


class RawCache:
    def __init__(self, root: Path | None = None):
        self.root = root

    def dataset_dir(self, season: int, week: int, dataset: str) -> Path:
        base = self.root if self.root is not None else raw_week_dir(season, week)
        return base / dataset

    def paths(self, *, season: int, week: int, dataset: str, path: str, params: dict[str, Any] | None) -> tuple[Path, Path]:
        digest = request_hash(path, params)
        folder = self.dataset_dir(season, week, dataset)
        return folder / f"{digest}.json", folder / f"{digest}.metadata.json"

    def read(self, *, season: int, week: int, dataset: str, path: str, params: dict[str, Any] | None) -> Any | None:
        body_path, _ = self.paths(season=season, week=week, dataset=dataset, path=path, params=params)
        if not body_path.exists():
            return None
        return json.loads(body_path.read_text(encoding="utf-8"))

    def write(
        self,
        *,
        season: int,
        week: int,
        dataset: str,
        path: str,
        params: dict[str, Any] | None,
        status: int,
        headers: dict[str, str],
        body: Any,
        table: str | None = None,
    ) -> Path:
        body_path, meta_path = self.paths(season=season, week=week, dataset=dataset, path=path, params=params)
        body_path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(body, sort_keys=True, indent=2, default=str)
        body_path.write_text(raw + "\n", encoding="utf-8")
        row_count = 0
        if table and isinstance(body, dict) and isinstance(body.get(table), list):
            row_count = len(body[table])
        meta = {
            "endpoint": path,
            "endpoint_slug": endpoint_slug(path),
            "params": canonical_params(params),
            "fetched_at_utc": datetime.now(timezone.utc).isoformat(),
            "http_status": status,
            "response_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
            "safe_headers": sanitize_headers(headers),
            "table": table,
            "row_count": row_count,
            "source": "pff_api",
        }
        meta_path.write_text(json.dumps(meta, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return body_path


def sanitize_headers(headers: dict[str, str]) -> dict[str, str]:
    allowed = {"content-type", "x-request-id", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset", "retry-after"}
    return {key: value for key, value in headers.items() if key.lower() in allowed}
