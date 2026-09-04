from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from .common import (
    CANONICAL_ODDS_COLUMNS,
    ODDS_IDENTITY_COLUMNS,
    OddsSnapshotMetadata,
    isoformat_with_offset,
    normalize_player,
    normalize_side,
    safe_float,
    safe_int,
    to_repo_relative,
)

MARKET_MAPPING = {
    "player_pass_yds": ("player_pass_yds", False, "main"),
    "player_rush_yds": ("player_rush_yds", False, "main"),
    "player_reception_yds": ("player_reception_yds", False, "main"),
    "player_receptions": ("player_receptions", False, "main"),
    "player_pass_yds_alternate": ("player_pass_yds", True, "alternate"),
    "player_rush_yds_alternate": ("player_rush_yds", True, "alternate"),
    "player_reception_yds_alternate": ("player_reception_yds", True, "alternate"),
    "player_receptions_alternate": ("player_receptions", True, "alternate"),
    "alternate_player_pass_yds": ("player_pass_yds", True, "alternate"),
    "alternate_player_rush_yds": ("player_rush_yds", True, "alternate"),
    "alternate_player_reception_yds": ("player_reception_yds", True, "alternate"),
    "alternate_player_receptions": ("player_receptions", True, "alternate"),
}


def load_json_payload(path: Path | str) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _event_list(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return [event for event in payload if isinstance(event, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data", payload)
    if isinstance(data, list):
        return [event for event in data if isinstance(event, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _reject(rejections: list[dict], *, reason: str, metadata: OddsSnapshotMetadata, event_index: int, market_index: int | None, outcome_index: int | None, raw_file: str, market_key: str = "", outcome: dict | None = None) -> None:
    outcome = outcome or {}
    rejections.append({
        "reason": reason,
        "source": metadata.source,
        "season": metadata.season,
        "week": metadata.week,
        "captured_at": isoformat_with_offset(metadata.captured_at),
        "raw_file": raw_file,
        "market_source_key": market_key,
        "outcome_name": outcome.get("name", ""),
        "outcome_description": outcome.get("description", ""),
        "point_raw": outcome.get("point", ""),
        "price_raw": outcome.get("price", ""),
        "source_event_index": event_index,
        "source_market_index": "" if market_index is None else market_index,
        "source_outcome_index": "" if outcome_index is None else outcome_index,
    })


def _source_location(row: dict) -> str:
    return (
        f"event={row.get('source_event_index', '')};"
        f"market={row.get('source_market_index', '')};"
        f"outcome={row.get('source_outcome_index', '')}"
    )


def _lineage_from_row(row: dict) -> dict[str, str | int]:
    keys = str(row.get("contributing_market_source_keys") or row.get("market_source_key") or "")
    prices = str(row.get("contributing_price_raws") or row.get("price_raw") or "")
    alternates = str(row.get("contributing_is_alternate") or row.get("is_alternate") or "")
    locations = str(row.get("contributing_source_locations") or _source_location(row))
    count = row.get("consolidated_duplicate_count", 0)
    try:
        duplicate_count = int(count)
    except (TypeError, ValueError):
        duplicate_count = 0
    return {
        "contributing_market_source_keys": keys,
        "contributing_price_raws": prices,
        "contributing_is_alternate": alternates,
        "contributing_source_locations": locations,
        "consolidated_duplicate_count": duplicate_count,
    }


def _merge_lineage(existing: dict, candidate: dict) -> dict[str, str | int]:
    prior = _lineage_from_row(existing)
    current = _lineage_from_row(candidate)
    return {
        "contributing_market_source_keys": f"{prior['contributing_market_source_keys']}|{current['contributing_market_source_keys']}",
        "contributing_price_raws": f"{prior['contributing_price_raws']}|{current['contributing_price_raws']}",
        "contributing_is_alternate": f"{prior['contributing_is_alternate']}|{current['contributing_is_alternate']}",
        "contributing_source_locations": f"{prior['contributing_source_locations']}|{current['contributing_source_locations']}",
        "consolidated_duplicate_count": int(prior["consolidated_duplicate_count"]) + int(current["consolidated_duplicate_count"]) + 1,
    }


def _candidate_is_better(candidate: dict, existing: dict) -> bool:
    candidate_price = int(candidate["price"])
    existing_price = int(existing["price"])
    if candidate_price != existing_price:
        return candidate_price > existing_price
    if bool(existing.get("is_alternate")) and not bool(candidate.get("is_alternate")):
        return True
    return False


def transform_odds_api_snapshot(payload: Any, *, metadata: OddsSnapshotMetadata, sportsbook_filter: str | None = None, market_filter: str | None = None, project_root: Path | None = None) -> tuple[list[dict], list[dict], list[dict]]:
    project_root = project_root or Path.cwd()
    rows: list[dict] = []
    rejected: list[dict] = []
    conflicts: list[dict] = []
    seen: dict[tuple, int] = {}
    raw_file = to_repo_relative(metadata.raw_file, project_root=project_root)
    captured_at = isoformat_with_offset(metadata.captured_at)

    for event_index, event in enumerate(_event_list(payload)):
        event_id = event.get("id")
        if not event_id:
            _reject(rejected, reason="missing_event_id", metadata=metadata, event_index=event_index, market_index=None, outcome_index=None, raw_file=raw_file)
            continue
        for book in event.get("bookmakers", []) or []:
            bookmaker_key = book.get("key", "")
            sportsbook = str(bookmaker_key or "").strip().lower()
            if sportsbook_filter and sportsbook != sportsbook_filter.lower():
                continue
            for market_index, market in enumerate(book.get("markets", []) or []):
                market_key = str(market.get("key", "")).strip()
                mapped = MARKET_MAPPING.get(market_key)
                if mapped is None:
                    for outcome_index, outcome in enumerate(market.get("outcomes", []) or []):
                        _reject(rejected, reason="missing_market_mapping", metadata=metadata, event_index=event_index, market_index=market_index, outcome_index=outcome_index, raw_file=raw_file, market_key=market_key, outcome=outcome)
                    continue
                canonical_market, is_alternate, _line_type = mapped
                if market_filter and canonical_market != market_filter:
                    continue
                outcomes = market.get("outcomes", []) or []
                if not outcomes:
                    _reject(rejected, reason="malformed_outcomes", metadata=metadata, event_index=event_index, market_index=market_index, outcome_index=None, raw_file=raw_file, market_key=market_key)
                    continue
                for outcome_index, outcome in enumerate(outcomes):
                    player = outcome.get("description") or outcome.get("player") or outcome.get("participant")
                    side = normalize_side(outcome.get("name"))
                    line = safe_float(outcome.get("point"))
                    price = safe_int(outcome.get("price"))
                    if not player:
                        _reject(rejected, reason="missing_player_name", metadata=metadata, event_index=event_index, market_index=market_index, outcome_index=outcome_index, raw_file=raw_file, market_key=market_key, outcome=outcome)
                        continue
                    if side is None:
                        _reject(rejected, reason="unrecognized_side", metadata=metadata, event_index=event_index, market_index=market_index, outcome_index=outcome_index, raw_file=raw_file, market_key=market_key, outcome=outcome)
                        continue
                    if line is None:
                        _reject(rejected, reason="missing_or_nonnumeric_line", metadata=metadata, event_index=event_index, market_index=market_index, outcome_index=outcome_index, raw_file=raw_file, market_key=market_key, outcome=outcome)
                        continue
                    if price is None:
                        _reject(rejected, reason="missing_or_invalid_price", metadata=metadata, event_index=event_index, market_index=market_index, outcome_index=outcome_index, raw_file=raw_file, market_key=market_key, outcome=outcome)
                        continue
                    row = {
                        "sportsbook": sportsbook,
                        "source": metadata.source,
                        "event_id": event_id,
                        "commence_time": event.get("commence_time", ""),
                        "home_team": event.get("home_team", ""),
                        "away_team": event.get("away_team", ""),
                        "player": str(player),
                        "player_normalized": normalize_player(player),
                        "market": canonical_market,
                        "line": float(line),
                        "side": side,
                        "price": int(price),
                        "captured_at": captured_at,
                        "captured_at_source": metadata.captured_at_source,
                        "season": int(metadata.season),
                        "week": int(metadata.week),
                        "is_alternate": bool(is_alternate),
                        "market_source_key": market_key,
                        "outcome_description": outcome.get("description", ""),
                        "raw_file": raw_file,
                        "source_event_index": event_index,
                        "source_market_index": market_index,
                        "source_outcome_index": outcome_index,
                        "bookmaker_key": bookmaker_key,
                        "bookmaker_title": book.get("title", ""),
                        "last_update": book.get("last_update", ""),
                        "market_last_update": market.get("last_update", ""),
                        "point_raw": outcome.get("point", ""),
                        "price_raw": outcome.get("price", ""),
                        "contributing_market_source_keys": market_key,
                        "contributing_price_raws": str(outcome.get("price", "")),
                        "contributing_is_alternate": str(bool(is_alternate)),
                        "contributing_source_locations": "",
                        "consolidated_duplicate_count": 0,
                    }
                    row["contributing_source_locations"] = _source_location(row)
                    identity = tuple(row.get(col) for col in ODDS_IDENTITY_COLUMNS)
                    prior_index = seen.get(identity)
                    if prior_index is not None:
                        prior = rows[prior_index]
                        merged_lineage = _merge_lineage(prior, row)
                        if _candidate_is_better(row, prior):
                            replacement = row
                            replacement.update(merged_lineage)
                            rows[prior_index] = replacement
                            retained_price = row.get("price")
                            discarded_price = prior.get("price")
                        else:
                            prior.update(merged_lineage)
                            retained_price = prior.get("price")
                            discarded_price = row.get("price")
                        conflicts.append({
                            "reason": "consolidated_duplicate_price",
                            "identity": "|".join(map(str, identity)),
                            "existing_price": prior.get("price"),
                            "new_price": row.get("price"),
                            "retained_price": retained_price,
                            "discarded_price": discarded_price,
                            "existing_market_source_key": prior.get("market_source_key"),
                            "new_market_source_key": row.get("market_source_key"),
                        })
                        continue
                    seen[identity] = len(rows)
                    rows.append(row)
    return rows, rejected, conflicts


def build_validation_report(payload: Any, rows: list[dict], rejected: list[dict], conflicts: list[dict]) -> pd.DataFrame:
    events = _event_list(payload)
    raw_bookmakers = [book for event in events for book in (event.get("bookmakers", []) or [])]
    raw_markets = [market for book in raw_bookmakers for market in (book.get("markets", []) or [])]
    raw_outcomes = [outcome for market in raw_markets for outcome in (market.get("outcomes", []) or [])]
    df = pd.DataFrame(rows, columns=CANONICAL_ODDS_COLUMNS)
    rejected_df = pd.DataFrame(rejected)
    metrics: list[dict] = [
        {"metric": "raw_events", "value": len(events)},
        {"metric": "bookmakers", "value": len(raw_bookmakers)},
        {"metric": "raw_markets", "value": len(raw_markets)},
        {"metric": "raw_outcomes", "value": len(raw_outcomes)},
        {"metric": "canonical_rows", "value": len(rows)},
        {"metric": "rejected_rows", "value": len(rejected)},
        {"metric": "unique_events", "value": df["event_id"].nunique() if not df.empty else 0},
        {"metric": "unique_players", "value": df["player_normalized"].nunique() if not df.empty else 0},
        {"metric": "unique_lines", "value": df["line"].nunique() if not df.empty else 0},
        {"metric": "main_line_rows", "value": int((df["is_alternate"] == False).sum()) if not df.empty else 0},
        {"metric": "alternate_line_rows", "value": int((df["is_alternate"] == True).sum()) if not df.empty else 0},
        {"metric": "duplicate_canonical_keys", "value": 0},
        {"metric": "consolidated_duplicate_prices", "value": len(conflicts)},
        {"metric": "missing_player_names", "value": int((rejected_df["reason"] == "missing_player_name").sum()) if not rejected_df.empty else 0},
        {"metric": "missing_market_mappings", "value": int((rejected_df["reason"] == "missing_market_mapping").sum()) if not rejected_df.empty else 0},
        {"metric": "missing_or_nonnumeric_lines", "value": int((rejected_df["reason"] == "missing_or_nonnumeric_line").sum()) if not rejected_df.empty else 0},
        {"metric": "missing_or_invalid_prices", "value": int((rejected_df["reason"] == "missing_or_invalid_price").sum()) if not rejected_df.empty else 0},
        {"metric": "unrecognized_sides", "value": int((rejected_df["reason"] == "unrecognized_side").sum()) if not rejected_df.empty else 0},
        {"metric": "malformed_outcomes", "value": int((rejected_df["reason"] == "malformed_outcomes").sum()) if not rejected_df.empty else 0},
        {"metric": "minimum_price", "value": df["price"].min() if not df.empty else None},
        {"metric": "maximum_price", "value": df["price"].max() if not df.empty else None},
    ]
    warnings: list[str] = []
    if not df.empty:
        odd_prices = df.loc[df["price"].abs() > 5000]
        if not odd_prices.empty:
            warnings.append(f"implausible_price_rows={len(odd_prices)}")
        for column, metric in [("sportsbook", "rows_by_sportsbook"), ("market", "rows_by_canonical_market"), ("market_source_key", "rows_by_raw_market_key"), ("side", "rows_by_side")]:
            for key, count in Counter(df[column].astype(str)).items():
                metrics.append({"metric": metric, "subgroup": key, "value": count})
        for market, grouped in df.groupby("market", sort=True):
            metrics.append({"metric": "minimum_line", "subgroup": market, "value": grouped["line"].min()})
            metrics.append({"metric": "maximum_line", "subgroup": market, "value": grouped["line"].max()})
    metrics.append({"metric": "warnings", "value": " | ".join(warnings)})
    return pd.DataFrame(metrics)
