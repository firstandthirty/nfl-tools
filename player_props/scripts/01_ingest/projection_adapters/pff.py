from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd

from projection_adapters.common import (
    CANONICAL_MARKETS,
    REQUIRED_OUTPUT_COLUMNS,
    REQUIRED_PFF_COLUMNS,
    SnapshotMetadata,
    build_output_row,
    normalize_player_name,
    normalize_team,
    validate_required_columns,
)

PFF_MARKETS = [
    ("player_pass_yds", "passYds"),
    ("player_rush_yds", "rushYds"),
    ("player_reception_yds", "recvYds"),
    ("player_receptions", "recvReceptions"),
]

ADAPTER_VERSION = "pff_adapter_v1"


def _market_is_applicable(position: str, market: str, value: float) -> bool:
    value = float(value)
    if market == "player_pass_yds":
        if position == "qb":
            return True
        return abs(value) > 1e-9
    if market == "player_rush_yds":
        if position in {"qb", "rb"}:
            return True
        return abs(value) > 1e-9
    if market in {"player_reception_yds", "player_receptions"}:
        if position == "qb":
            return abs(value) > 1e-9
        return True
    return False


def _coerce_numeric(value: Any) -> float | None:
    if value is None:
        return None
    if pd.isna(value):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric


def transform_pff_snapshot(raw_frame: pd.DataFrame, *, metadata: SnapshotMetadata, source: str = "pff") -> tuple[list[dict], list[dict]]:
    frame = raw_frame.copy()
    validate_required_columns(frame, REQUIRED_PFF_COLUMNS, "PFF")

    rows: list[dict] = []
    rejected_rows: list[dict] = []
    seen_keys: set[tuple] = set()

    warnings: list[str] = []
    raw_player_names = Counter()
    recognized_positions = {"qb", "rb", "wr", "te", "k", "dst"}
    rows_by_position: Counter[str] = Counter()
    rows_by_market: Counter[str] = Counter()

    for row_number, raw_row in enumerate(frame.to_dict(orient="records"), start=2):
        raw_player_name = str(raw_row.get("playerName", ""))
        raw_player_names[raw_player_name] += 1

        player = raw_player_name
        player_normalized = normalize_player_name(player)
        team, team_raw = normalize_team(raw_row.get("teamName"))
        position = str(raw_row.get("position", "")).strip().lower()
        if position not in recognized_positions:
            warnings.append(f"unrecognized_position={position}")

        for market, source_column in PFF_MARKETS:
            raw_value = raw_row.get(source_column)
            if raw_value is None:
                continue
            numeric_value = _coerce_numeric(raw_value)
            if numeric_value is None:
                rejected_rows.append(
                    {
                        "source_row_number": row_number,
                        "player": player,
                        "position": position,
                        "market": market,
                        "reason": "nonnumeric_projection",
                        "value": raw_value,
                    }
                )
                continue
            if pd.isna(numeric_value):
                rejected_rows.append(
                    {
                        "source_row_number": row_number,
                        "player": player,
                        "position": position,
                        "market": market,
                        "reason": "null_projection",
                        "value": raw_value,
                    }
                )
                continue
            if not _market_is_applicable(position, market, numeric_value):
                rejected_rows.append(
                    {
                        "source_row_number": row_number,
                        "player": player,
                        "position": position,
                        "market": market,
                        "reason": "not_applicable",
                        "value": numeric_value,
                    }
                )
                continue

            row_payload = {
                "player": player,
                "player_normalized": player_normalized,
                "team": team,
                "team_raw": team_raw,
                "position": position.upper(),
                "market": market,
                "projection": float(numeric_value),
                "source_player_id": None,
                "source_row_number": row_number,
                "source_column": source_column,
            }
            key = (
                source,
                metadata.season,
                metadata.week,
                metadata.captured_at.isoformat(),
                player_normalized,
                market,
            )
            if key in seen_keys:
                raise ValueError(f"duplicate canonical projection key encountered: {key}")
            seen_keys.add(key)
            rows.append(build_output_row(row_payload, metadata=metadata, source=source))
            rows_by_position[position.upper()] += 1
            rows_by_market[market] += 1

    return rows, rejected_rows


def build_validation_report(raw_frame: pd.DataFrame, transformed_rows: list[dict], rejected_rows: list[dict], metadata: SnapshotMetadata, warnings: list[str]) -> pd.DataFrame:
    summary_rows = [
        {"metric": "raw_rows", "value": len(raw_frame)},
        {"metric": "transformed_rows", "value": len(transformed_rows)},
        {"metric": "unique_players", "value": len({row["player_normalized"] for row in transformed_rows})},
        {"metric": "null_projections", "value": sum(1 for row in rejected_rows if row["reason"] == "null_projection")},
        {"metric": "nonnumeric_projection_values", "value": sum(1 for row in rejected_rows if row["reason"] == "nonnumeric_projection")},
        {"metric": "duplicate_canonical_keys", "value": 0},
        {"metric": "duplicate_raw_player_names", "value": sum(1 for count in Counter(raw_frame.iloc[:, 0].astype(str)).values() if count > 1)},
        {"metric": "unrecognized_positions", "value": len({str(row["position"]).lower() for row in transformed_rows if str(row["position"]).lower() not in {"QB", "RB", "WR", "TE", "K", "DST"}})},
        {"metric": "unrecognized_teams", "value": 0},
        {"metric": "timestamp_parser_used", "value": metadata.captured_at_source},
        {"metric": "warnings", "value": " | ".join(warnings) if warnings else ""},
    ]

    for position, count in sorted(Counter(row["position"] for row in transformed_rows).items()):
        summary_rows.append({"metric": "rows_by_position", "subgroup": position, "value": count})
    for market, count in sorted(Counter(row["market"] for row in transformed_rows).items()):
        summary_rows.append({"metric": "rows_by_market", "subgroup": market, "value": count})

    for market in sorted(CANONICAL_MARKETS.values()):
        market_values = [row["projection"] for row in transformed_rows if row["market"] == market]
        if not market_values:
            continue
        summary_rows.append({"metric": "min_projection", "subgroup": market, "value": min(market_values)})
        summary_rows.append({"metric": "median_projection", "subgroup": market, "value": pd.Series(market_values).median()})
        summary_rows.append({"metric": "mean_projection", "subgroup": market, "value": pd.Series(market_values).mean()})
        summary_rows.append({"metric": "max_projection", "subgroup": market, "value": max(market_values)})

    return pd.DataFrame(summary_rows)
