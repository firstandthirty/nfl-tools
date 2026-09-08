from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from projection_adapters.common import SnapshotMetadata, build_output_row, normalize_player_name, normalize_team

ADAPTER_VERSION = "ftn_adapter_v1"

EXPECTED_COLUMNS = [
    "Player",
    "Position",
    "Team",
    "Opp.",
    "Auction",
    "PaCom",
    "PaAtt",
    "PaYds",
    "PaTD",
    "PaINT",
    "RuAtt",
    "RuYds",
    "RuTD",
    "Fum.",
    "Tar",
    "Rec",
    "ReYds",
    "ReTD",
    "FPTS",
]

FTN_MARKETS = [
    ("player_pass_yds", "PaYds"),
    ("player_rush_yds", "RuYds"),
    ("player_receptions", "Rec"),
    ("player_reception_yds", "ReYds"),
]


def identify_source_file_type(path: Path | str) -> str:
    name = Path(path).name.upper()
    if re.search(r"(^|[_\s])QB(\.|_|\s|$)", name):
        return "qb"
    if re.search(r"(^|[_\s])FLEX(\.|_|\s|$)", name) or re.search(r"(^|[_\s])FLX(\.|_|\s|$)", name):
        return "flex"
    raise ValueError(f"Could not identify FTN source file type from filename: {path}")


def read_ftn_csv(path: Path | str) -> pd.DataFrame:
    frame = pd.read_csv(path, header=1)
    frame.attrs["raw_file"] = str(path)
    return frame


def _coerce_numeric(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _is_blank(value: Any) -> bool:
    if value is None or pd.isna(value):
        return True
    return str(value).strip() == ""


def _clean_text(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).replace("\xa0", " ").strip()


def _clean_position(value: Any) -> str:
    return _clean_text(value).upper()


def _has_player(value: Any) -> bool:
    return bool(_clean_text(value))


def _market_is_applicable(position: str, market: str, value: float) -> bool:
    position = position.upper()
    if market == "player_pass_yds":
        return position == "QB" or abs(value) > 1e-9
    if market == "player_rush_yds":
        return position in {"QB", "RB"} or abs(value) > 1e-9
    if market in {"player_receptions", "player_reception_yds"}:
        return position in {"RB", "WR", "TE"} or abs(value) > 1e-9
    return False


def _validate_layout(frame: pd.DataFrame, *, source_file_type: str) -> None:
    actual = list(frame.columns)
    if actual != EXPECTED_COLUMNS:
        raise ValueError(
            f"Unexpected FTN {source_file_type.upper()} two-row-header layout. "
            f"Expected {EXPECTED_COLUMNS}; got {actual}"
        )


def transform_ftn_file(
    raw_frame: pd.DataFrame,
    *,
    raw_file: Path | str,
    metadata: SnapshotMetadata,
    source: str = "ftn",
    seen_keys: set[tuple] | None = None,
) -> tuple[list[dict], list[dict]]:
    raw_path = Path(raw_file)
    source_file_type = identify_source_file_type(raw_path)
    _validate_layout(raw_frame, source_file_type=source_file_type)
    seen_keys = seen_keys if seen_keys is not None else set()
    rows: list[dict] = []
    rejected_rows: list[dict] = []

    for row_number, raw_row in enumerate(raw_frame.to_dict(orient="records"), start=3):
        raw_player = raw_row.get("Player")
        if not _has_player(raw_player):
            rejected_rows.append(
                {
                    "source_file_type": source_file_type,
                    "raw_file": str(raw_path),
                    "source_row_number": row_number,
                    "player": _clean_text(raw_player),
                    "position": "",
                    "market": "",
                    "source_column": "Player",
                    "reason": "missing_player",
                    "value": raw_player,
                }
            )
            continue

        player = _clean_text(raw_player)
        position = _clean_position(raw_row.get("Position"))
        for market, source_column in FTN_MARKETS:
            value = raw_row.get(source_column)
            numeric_value = _coerce_numeric(value)
            if numeric_value is None:
                if _is_blank(value):
                    continue
                rejected_rows.append(
                    {
                        "source_file_type": source_file_type,
                        "raw_file": str(raw_path),
                        "source_row_number": row_number,
                        "player": player,
                        "position": position,
                        "market": market,
                        "source_column": source_column,
                        "reason": "nonnumeric_projection",
                        "value": value,
                    }
                )
                continue
            if not _market_is_applicable(position, market, numeric_value):
                rejected_rows.append(
                    {
                        "source_file_type": source_file_type,
                        "raw_file": str(raw_path),
                        "source_row_number": row_number,
                        "player": player,
                        "position": position,
                        "market": market,
                        "source_column": source_column,
                        "reason": "not_applicable",
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
                        "source_file_type": source_file_type,
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
            opponent, opponent_raw = normalize_team(raw_row.get("Opp."))
            row_payload = {
                "player": player,
                "player_normalized": player_normalized,
                "team": team,
                "team_raw": team_raw,
                "position": position,
                "market": market,
                "projection": numeric_value,
                "source_player_id": None,
                "source_row_number": row_number,
                "source_column": source_column,
                "raw_file": raw_path,
            }
            output_row = build_output_row(row_payload, metadata=metadata, source=source)
            output_row["source_file_type"] = source_file_type
            output_row["source_format"] = "csv"
            output_row["opponent"] = opponent
            output_row["opponent_raw"] = opponent_raw
            rows.append(output_row)

    return rows, rejected_rows


def transform_ftn_snapshot(raw_frames: dict[str, pd.DataFrame], *, metadata: SnapshotMetadata, source: str = "ftn") -> tuple[list[dict], list[dict]]:
    expected = {"qb", "flex"}
    actual = set(raw_frames)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        pieces = []
        if missing:
            pieces.append(f"missing components: {', '.join(missing)}")
        if extra:
            pieces.append(f"unexpected components: {', '.join(extra)}")
        raise ValueError(f"Incomplete FTN logical snapshot ({'; '.join(pieces)})")

    rows: list[dict] = []
    rejected_rows: list[dict] = []
    seen_keys: set[tuple] = set()
    for source_file_type in ["qb", "flex"]:
        frame = raw_frames[source_file_type]
        raw_path = Path(frame.attrs.get("raw_file", f"{source_file_type}.csv"))
        file_rows, file_rejected = transform_ftn_file(
            frame,
            raw_file=raw_path,
            metadata=metadata,
            source=source,
            seen_keys=seen_keys,
        )
        rows.extend(file_rows)
        rejected_rows.extend(file_rejected)
    return rows, rejected_rows


def build_validation_report(raw_frames: dict[str, pd.DataFrame], transformed_rows: list[dict], rejected_rows: list[dict], metadata: SnapshotMetadata, warnings: list[str]) -> pd.DataFrame:
    summary_rows = [
        {"metric": "raw_rows", "value": sum(len(frame) for frame in raw_frames.values())},
        {"metric": "raw_rows", "subgroup": "qb", "value": len(raw_frames.get("qb", []))},
        {"metric": "raw_rows", "subgroup": "flex", "value": len(raw_frames.get("flex", []))},
        {"metric": "source_format", "value": "csv"},
        {"metric": "transformed_rows", "value": len(transformed_rows)},
        {"metric": "unique_players", "value": len({row["player_normalized"] for row in transformed_rows})},
        {"metric": "duplicate_canonical_keys", "value": 0},
        {"metric": "timestamp_parser_used", "value": metadata.captured_at_source},
        {"metric": "warnings", "value": " | ".join(warnings) if warnings else ""},
    ]
    for reason, count in sorted(Counter(row.get("reason", "") for row in rejected_rows).items()):
        summary_rows.append({"metric": "rejected_rows", "subgroup": reason, "value": count})
    skipped_empty_fields = 0
    for frame in raw_frames.values():
        for _, source_column in FTN_MARKETS:
            skipped_empty_fields += int(frame[source_column].isna().sum() + frame[source_column].astype(str).str.strip().eq("").sum())
    if skipped_empty_fields:
        summary_rows.append({"metric": "skipped_fields", "subgroup": "blank_optional_projection_cell", "value": skipped_empty_fields})
    for source_file_type, count in sorted(Counter(row.get("source_file_type", "") for row in transformed_rows).items()):
        summary_rows.append({"metric": "rows_by_source_file_type", "subgroup": source_file_type, "value": count})
    for position, count in sorted(Counter(row["position"] for row in transformed_rows).items()):
        summary_rows.append({"metric": "rows_by_position", "subgroup": position, "value": count})
    for market, count in sorted(Counter(row["market"] for row in transformed_rows).items()):
        summary_rows.append({"metric": "rows_by_market", "subgroup": market, "value": count})
    return pd.DataFrame(summary_rows)


def build_sanity_warnings(rows: list[dict]) -> list[str]:
    warnings: list[str] = []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return ["empty_ftn_snapshot"]
    for market in [market for market, _ in FTN_MARKETS]:
        market_rows = frame.loc[frame["market"] == market, "projection"]
        if not market_rows.empty and (market_rows < 0).any():
            warnings.append(f"negative_projection:{market}")
    return warnings
