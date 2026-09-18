from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .cache import RawCache
from .config import PFFConfig, load_config


class PFFClientError(RuntimeError):
    pass


@dataclass(frozen=True)
class PFFResponse:
    body: Any
    status: int
    cache_hit: bool


class PFFClient:
    def __init__(
        self,
        config: PFFConfig | None = None,
        *,
        cache: RawCache | None = None,
        timeout: int = 30,
        retries: int = 2,
        retry_sleep: float = 1.0,
    ):
        self.config = config or load_config()
        self.cache = cache or RawCache()
        self.timeout = timeout
        self.retries = retries
        self.retry_sleep = retry_sleep

    def get(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        dataset: str | None = None,
        season: int | None = None,
        week: int | None = None,
        table: str | None = None,
        use_cache: bool = True,
    ) -> PFFResponse:
        if use_cache and dataset and season is not None and week is not None:
            cached = self.cache.read(season=season, week=week, dataset=dataset, path=path, params=params)
            if cached is not None:
                return PFFResponse(cached, 200, True)
        status, headers, body = self._request(path, params=params)
        if dataset and season is not None and week is not None:
            self.cache.write(
                season=season,
                week=week,
                dataset=dataset,
                path=path,
                params=params,
                status=status,
                headers=headers,
                body=body,
                table=table,
            )
        return PFFResponse(body, status, False)

    def _request(self, path: str, *, params: dict[str, Any] | None = None) -> tuple[int, dict[str, str], Any]:
        url = f"{self.config.api_base}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "Authorization": f"Bearer {self.config.api_key}"},
        )
        last_error: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    raw = response.read().decode("utf-8")
                    return response.status, dict(response.headers), json.loads(raw or "{}")
            except urllib.error.HTTPError as exc:
                body = _decode_error_body(exc)
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= self.retries:
                    raise PFFClientError(f"PFF GET {path} failed with HTTP {exc.code}: {_safe_error_body(body)}") from exc
                last_error = exc
                time.sleep(_retry_delay(exc, self.retry_sleep, attempt))
            except urllib.error.URLError as exc:
                if attempt >= self.retries:
                    raise PFFClientError(f"PFF GET {path} failed: {exc.reason}") from exc
                last_error = exc
                time.sleep(self.retry_sleep * (attempt + 1))
        raise PFFClientError(f"PFF GET {path} failed after retries: {last_error}")


def _decode_error_body(exc: urllib.error.HTTPError) -> Any:
    raw = exc.read()
    try:
        return json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return {"non_json_body_length": len(raw)}


def _safe_error_body(body: Any) -> str:
    if not isinstance(body, dict):
        return type(body).__name__
    safe = {key: body[key] for key in sorted(body) if "key" not in key.lower() and "token" not in key.lower()}
    return json.dumps(safe, sort_keys=True)[:500]


def _retry_delay(exc: urllib.error.HTTPError, default_sleep: float, attempt: int) -> float:
    retry_after = exc.headers.get("Retry-After")
    if retry_after:
        try:
            return min(float(retry_after), 10.0)
        except ValueError:
            pass
    return default_sleep * (attempt + 1)
