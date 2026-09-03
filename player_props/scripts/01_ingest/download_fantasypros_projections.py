from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "scripts" / "01_ingest") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "01_ingest"))

from ingest_projection_snapshots import ingest_fantasypros_api_snapshot


BASE_URL = "https://api.fantasypros.com/public/v2/json/nfl/{season}/projections"
DEFAULT_POSITIONS = "QB:RB:WR:TE"
DEFAULT_SCORING = "STD"
SAFE_RATE_LIMIT_HEADERS = [
    "x-ratelimit-limit",
    "x-ratelimit-remaining",
    "x-ratelimit-reset",
    "x-rate-limit-limit",
    "x-rate-limit-remaining",
    "x-rate-limit-reset",
]


def _load_env_value(name: str) -> str | None:
    value = os.getenv(name)
    if value:
        return value
    candidates = [PROJECT_ROOT / ".env", PROJECT_ROOT.parent / ".env"]
    for env_path in candidates:
        if not env_path.exists():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, raw_value = stripped.split("=", 1)
            if key.strip() == name:
                return raw_value.strip().strip('"').strip("'")
    return None


def _safe_rate_limit_headers(headers: requests.structures.CaseInsensitiveDict[str]) -> dict[str, str]:
    output: dict[str, str] = {}
    for header in SAFE_RATE_LIMIT_HEADERS:
        value = headers.get(header)
        if value is not None:
            output[header.lower()] = str(value)
    return output


def _raw_snapshot_path(*, season: int, week: int, captured_at: datetime) -> Path:
    week_dir = PROJECT_ROOT / "data" / "raw" / "projections" / "fantasypros" / str(season) / f"week_{week:02d}" / "snapshots"
    week_dir.mkdir(parents=True, exist_ok=True)
    timestamp = captured_at.strftime("%m_%d_%y_%H%M")
    return week_dir / f"{timestamp}_api_projections.json"


def _metadata_path(raw_path: Path) -> Path:
    return raw_path.with_suffix(raw_path.suffix + ".metadata.json")


def fetch_fantasypros_projections(*, api_key: str, season: int, week: int, positions: str, scoring: str, timeout: int) -> tuple[bytes, dict[str, Any]]:
    url = BASE_URL.format(season=season)
    params = {
        "week": week,
        "positions": positions,
        "scoring": scoring,
    }
    response = requests.get(url, headers={"x-api-key": api_key}, params=params, timeout=timeout)
    endpoint_path = f"/public/v2/json/nfl/{season}/projections?{urlencode(params)}"
    metadata = {
        "endpoint_path": endpoint_path,
        "status_code": response.status_code,
        "rate_limit_headers": _safe_rate_limit_headers(response.headers),
    }

    if response.status_code in {401, 403}:
        raise RuntimeError(f"FantasyPros API authorization failed with HTTP {response.status_code}. Check FANTASYPROS_API_KEY.")
    if response.status_code == 404:
        raise RuntimeError(f"FantasyPros API returned HTTP 404 for {endpoint_path}.")
    if response.status_code == 429:
        raise RuntimeError("FantasyPros API returned HTTP 429 rate limit.")
    if 500 <= response.status_code <= 599:
        raise RuntimeError(f"FantasyPros API server error HTTP {response.status_code}.")
    if response.status_code != 200:
        raise RuntimeError(f"FantasyPros API returned HTTP {response.status_code}.")

    try:
        json.loads(response.content.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("FantasyPros API returned malformed JSON.") from exc
    return response.content, metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and ingest FantasyPros NFL projection API snapshots")
    parser.add_argument("--season", required=True, type=int)
    parser.add_argument("--week", required=True, type=int)
    parser.add_argument("--positions", default=DEFAULT_POSITIONS)
    parser.add_argument("--scoring", default=DEFAULT_SCORING)
    parser.add_argument("--timeout", default=30, type=int)
    parser.add_argument("--skip-registry-update", action="store_true")
    args = parser.parse_args()

    api_key = _load_env_value("FANTASYPROS_API_KEY")
    if not api_key:
        raise RuntimeError("Missing FANTASYPROS_API_KEY. Set it in the environment or .env.")

    captured_at = datetime.now(ZoneInfo("America/New_York"))
    content, request_metadata = fetch_fantasypros_projections(
        api_key=api_key,
        season=args.season,
        week=args.week,
        positions=args.positions,
        scoring=args.scoring,
        timeout=args.timeout,
    )
    payload = json.loads(content.decode("utf-8"))
    players = payload.get("players") or []
    if not players:
        raise RuntimeError("FantasyPros API returned an empty projections payload.")

    raw_path = _raw_snapshot_path(season=args.season, week=args.week, captured_at=captured_at)
    raw_path.write_bytes(content)

    sidecar_payload = {
        "source": "fantasypros",
        "source_format": "api",
        "season": args.season,
        "week": args.week,
        "captured_at": captured_at.isoformat(),
        "captured_at_source": "api_request",
        "endpoint_path": request_metadata["endpoint_path"],
        "status_code": request_metadata["status_code"],
        "component_files": [str(raw_path.relative_to(PROJECT_ROOT)).replace("\\", "/")],
        "rate_limit_headers": request_metadata["rate_limit_headers"],
    }
    sidecar_path = _metadata_path(raw_path)
    sidecar_path.write_text(json.dumps(sidecar_payload, indent=2, sort_keys=True), encoding="utf-8")

    result = ingest_fantasypros_api_snapshot(
        raw_path,
        season=args.season,
        week=args.week,
        captured_at=captured_at,
        output_root=PROJECT_ROOT,
        skip_registry_update=args.skip_registry_update,
        endpoint_path=request_metadata["endpoint_path"],
        response_status=request_metadata["status_code"],
        metadata_file=sidecar_path,
    )

    print("FantasyPros API projections downloaded")
    print(f"endpoint_path={request_metadata['endpoint_path']}")
    print(f"http_status={request_metadata['status_code']}")
    print(f"captured_at={captured_at.isoformat()}")
    print(f"raw_file={raw_path}")
    print(f"metadata_file={sidecar_path}")
    print(f"api_raw_players={len(players)}")
    print(f"canonical_rows={result['rows_written']}")
    print(f"long_file={result['output_paths'].get('long')}")
    print(f"rejected_file={result['output_paths'].get('rejected')}")
    print(f"validation_file={result['output_paths'].get('validation')}")
    print(f"weekly_file={result['output_paths'].get('weekly')}")
    if result.get("warnings"):
        print(f"warnings={result['warnings']}")


if __name__ == "__main__":
    main()
