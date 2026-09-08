from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from projection_adapters.common import SnapshotMetadata, build_output_row, normalize_player_name, normalize_team

ADAPTER_VERSION = "fourforfour_adapter_v1"
SOURCE = "4for4"

EXPECTED_COLUMNS = [
    "Season",
    "Week",
    "PID",
    "Player",
    "Pos",
    "Team",
    "Opp",
    "aFPA",
    "aFPA Rk",
    "FFPts",
    "Comp",
    "Pass Att",
    "Pass Yds",
    "Pass TD",
    "INT",
    "Rush Att",
    "Rush Yds",
    "Rush TD",
    "Rec",
    "Rec Yds",
    "Rec TD",
    "Pa1D",
    "Ru1D",
    "Rec1D",
    "Fum",
    "XP",
    "FG",
    "Grade",
]

MARKET_COLUMNS = [
    ("player_pass_yds", "Pass Yds"),
    ("player_rush_yds", "Rush Yds"),
    ("player_receptions", "Rec"),
    ("player_reception_yds", "Rec Yds"),
]


def _clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).replace("\xa0", " ").strip()


def _coerce_numeric(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _validate_layout(frame: pd.DataFrame) -> None:
    actual = list(frame.columns)
    if actual != EXPECTED_COLUMNS:
        raise ValueError(f"Unexpected 4for4 CSV layout. Expected {EXPECTED_COLUMNS}; got {actual}")


def transform_fourforfour_snapshot(raw_frame: pd.DataFrame, *, raw_file: Path | str, metadata: SnapshotMetadata, source: str = SOURCE) -> tuple[list[dict], list[dict], list[dict]]:
    _validate_layout(raw_frame)
    raw_path = Path(raw_file)
    rows: list[dict] = []
    rejected_rows: list[dict] = []
    skipped_fields: list[dict] = []
    seen_keys: set[tuple] = set()

    for row_number, raw_row in enumerate(raw_frame.to_dict(orient="records"), start=2):
        player = _clean_text(raw_row.get("Player"))
        position = _clean_text(raw_row.get("Pos")).upper()
        if not player:
            rejected_rows.append(
                {
                    "raw_file": str(raw_path),
                    "source_row_number": row_number,
                    "player": player,
                    "position": position,
                    "market": "",
                    "source_column": "Player",
                    "reason": "missing_player",
                    "value": raw_row.get("Player"),
                }
            )
            continue

        for market, source_column in MARKET_COLUMNS:
            value = raw_row.get(source_column)
            numeric_value = _coerce_numeric(value)
            if numeric_value is None:
                rejected_rows.append(
                    {
                        "raw_file": str(raw_path),
                        "source_row_number": row_number,
                        "player": player,
                        "position": position,
                        "market": market,
                        "source_column": source_column,
                        "reason": "malformed_numeric_projection",
                        "value": value,
                    }
                )
                continue
            # 4for4 exports structural zeros for non-applicable stat categories.
            # Keep this provider-local so PFF/FantasyPros/FTN zero behavior is unchanged.
            if numeric_value <= 0:
                skipped_fields.append(
                    {
                        "raw_file": str(raw_path),
                        "source_row_number": row_number,
                        "player": player,
                        "position": position,
                        "market": market,
                        "source_column": source_column,
                        "reason": "zero_placeholder",
                        "value": numeric_value,
                    }
                )
                continue

            player_normalized = normalize_player_name(player)
            key = (
                source,
                metadata.season,
                metadata.week,
                metadata.captured_at.isoformat(),
                player_normalized,
                market,
            )
            if key in seen_keys:
                rejected_rows.append(
                    {
                        "raw_file": str(raw_path),
                        "source_row_number": row_number,
                        "player": player,
                        "position": position,
                        "market": market,
                        "source_column": source_column,
                        "reason": "duplicate_logical_projection",
                        "value": numeric_value,
                    }
                )
                continue
            seen_keys.add(key)

            team, team_raw = normalize_team(raw_row.get("Team"))
            opponent, opponent_raw = normalize_team(str(raw_row.get("Opp", "")).replace("@", ""))
            output_row = build_output_row(
                {
                    "player": player,
                    "player_normalized": player_normalized,
                    "team": team,
                    "team_raw": team_raw,
                    "position": position,
                    "market": market,
                    "projection": numeric_value,
                    "source_player_id": _clean_text(raw_row.get("PID")) or None,
                    "source_row_number": row_number,
                    "source_column": source_column,
                    "raw_file": raw_path,
                },
                metadata=metadata,
                source=source,
            )
            output_row["source_format"] = "csv"
            output_row["opponent"] = opponent
            output_row["opponent_raw"] = opponent_raw
            rows.append(output_row)

    return rows, rejected_rows, skipped_fields


def build_validation_report(raw_frame: pd.DataFrame, transformed_rows: list[dict], rejected_rows: list[dict], skipped_fields: list[dict], metadata: SnapshotMetadata, warnings: list[str]) -> pd.DataFrame:
    summary_rows = [
        {"metric": "raw_rows", "value": len(raw_frame)},
        {"metric": "source_format", "value": "csv"},
        {"metric": "transformed_rows", "value": len(transformed_rows)},
        {"metric": "unique_players", "value": len({row["player_normalized"] for row in transformed_rows})},
        {"metric": "duplicate_canonical_keys", "value": 0},
        {"metric": "timestamp_parser_used", "value": metadata.captured_at_source},
        {"metric": "warnings", "value": " | ".join(warnings) if warnings else ""},
    ]
    for reason, count in sorted(Counter(row.get("reason", "") for row in rejected_rows).items()):
        summary_rows.append({"metric": "rejected_rows", "subgroup": reason, "value": count})
    for market, count in sorted(Counter(row["market"] for row in skipped_fields).items()):
        summary_rows.append({"metric": "skipped_fields", "subgroup": f"zero_placeholder:{market}", "value": count})
    for position, count in sorted(Counter(row["position"] for row in transformed_rows).items()):
        summary_rows.append({"metric": "rows_by_position", "subgroup": position, "value": count})
    for market, count in sorted(Counter(row["market"] for row in transformed_rows).items()):
        summary_rows.append({"metric": "rows_by_market", "subgroup": market, "value": count})
    return pd.DataFrame(summary_rows)


def build_sanity_warnings(rows: list[dict]) -> list[str]:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return ["empty_4for4_snapshot"]
    warnings: list[str] = []
    if any(str(row.get("source")) != SOURCE for row in rows):
        warnings.append("source_key_not_4for4")
    return warnings
