from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from projection_adapters.common import (
    CANONICAL_MARKETS,
    SnapshotMetadata,
    build_output_row,
    normalize_player_name,
    normalize_team,
)

ADAPTER_VERSION = "fantasypros_adapter_v1"

EXPECTED_QB_COLUMNS = ["Player", "Team", "ATT", "CMP", "YDS", "TDS", "INTS", "ATT.1", "YDS.1", "TDS.1", "FL", "FPTS"]
EXPECTED_FLEX_COLUMNS = ["Player", "Team", "POS", "ATT", "YDS", "TDS", "REC", "YDS.1", "TDS.1", "FL", "FPTS"]

QB_MARKETS = [
    ("player_pass_yds", "YDS", "pass_yds"),
    ("player_rush_yds", "YDS.1", "rush_yds"),
]

FLEX_MARKETS = [
    ("player_rush_yds", "YDS", "rush_yds"),
    ("player_receptions", "REC", "receptions"),
    ("player_reception_yds", "YDS.1", "receiving_yds"),
]

API_MARKETS = [
    ("player_pass_yds", "pass_yds"),
    ("player_rush_yds", "rush_yds"),
    ("player_receptions", "rec_rec"),
    ("player_reception_yds", "rec_yds"),
]


def identify_source_file_type(path: Path | str) -> str:
    name = Path(path).name.upper()
    if Path(path).suffix.lower() == ".json":
        return "api"
    if re.search(r"(^|_)QB(\.|_|$)", name):
        return "qb"
    if re.search(r"(^|_)FLX(\.|_|$)", name) or re.search(r"(^|_)FLEX(\.|_|$)", name):
        return "flex"
    raise ValueError(f"Could not identify FantasyPros source file type from filename: {path}")


def _validate_layout(frame: pd.DataFrame, *, source_file_type: str) -> None:
    expected = EXPECTED_QB_COLUMNS if source_file_type == "qb" else EXPECTED_FLEX_COLUMNS
    actual = list(frame.columns)
    if actual != expected:
        raise ValueError(
            f"Unexpected FantasyPros {source_file_type.upper()} duplicate-header layout. "
            f"Expected {expected}; got {actual}"
        )


def _coerce_numeric(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _clean_position(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip().upper()
    return re.sub(r"\d+$", "", text)


def _has_player(value: Any) -> bool:
    if value is None or pd.isna(value):
        return False
    text = str(value).replace("\xa0", "").strip()
    return bool(text)


def _flex_market_is_applicable(position: str, market: str, value: float) -> bool:
    position = position.upper()
    if market == "player_rush_yds":
        if position == "RB":
            return True
        return abs(value) > 1e-9
    if market in {"player_receptions", "player_reception_yds"}:
        return position in {"RB", "WR", "TE"} or abs(value) > 1e-9
    return False


def _append_projection_row(
    rows: list[dict],
    rejected_rows: list[dict],
    seen_keys: set[tuple],
    *,
    metadata: SnapshotMetadata,
    source: str,
    raw_file: Path,
    source_file_type: str,
    source_row_number: int,
    player: str,
    team_value: Any,
    position: str,
    market: str,
    source_column: str,
    value: Any,
    applicable: bool,
) -> None:
    numeric_value = _coerce_numeric(value)
    if numeric_value is None:
        rejected_rows.append(
            {
                "source_file_type": source_file_type,
                "raw_file": str(raw_file),
                "source_row_number": source_row_number,
                "player": player,
                "position": position,
                "market": market,
                "source_column": source_column,
                "reason": "nonnumeric_projection",
                "value": value,
            }
        )
        return
    if not applicable:
        rejected_rows.append(
            {
                "source_file_type": source_file_type,
                "raw_file": str(raw_file),
                "source_row_number": source_row_number,
                "player": player,
                "position": position,
                "market": market,
                "source_column": source_column,
                "reason": "not_applicable",
                "value": numeric_value,
            }
        )
        return

    player_normalized = normalize_player_name(player)
    team, team_raw = normalize_team(team_value)
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
    row_payload = {
        "player": player,
        "player_normalized": player_normalized,
        "team": team,
        "team_raw": team_raw,
        "position": position,
        "market": market,
        "projection": numeric_value,
        "source_player_id": None,
        "source_row_number": source_row_number,
        "source_column": source_column,
        "source_file_type": source_file_type,
        "raw_file": raw_file,
    }
    output_row = build_output_row(row_payload, metadata=metadata, source=source)
    output_row["source_file_type"] = source_file_type
    rows.append(output_row)


def transform_fantasypros_file(raw_frame: pd.DataFrame, *, raw_file: Path | str, metadata: SnapshotMetadata, source: str = "fantasypros", seen_keys: set[tuple] | None = None) -> tuple[list[dict], list[dict]]:
    raw_path = Path(raw_file)
    source_file_type = identify_source_file_type(raw_path)
    _validate_layout(raw_frame, source_file_type=source_file_type)
    seen_keys = seen_keys if seen_keys is not None else set()
    rows: list[dict] = []
    rejected_rows: list[dict] = []

    for row_number, raw_row in enumerate(raw_frame.to_dict(orient="records"), start=2):
        raw_player = raw_row.get("Player")
        if not _has_player(raw_player):
            rejected_rows.append(
                {
                    "source_file_type": source_file_type,
                    "raw_file": str(raw_path),
                    "source_row_number": row_number,
                    "player": "" if raw_player is None or pd.isna(raw_player) else str(raw_player),
                    "position": "",
                    "market": "",
                    "source_column": "Player",
                    "reason": "missing_player",
                    "value": raw_player,
                }
            )
            continue

        player = str(raw_player).strip()
        if source_file_type == "qb":
            for market, source_column, source_column_label in QB_MARKETS:
                _append_projection_row(
                    rows,
                    rejected_rows,
                    seen_keys,
                    metadata=metadata,
                    source=source,
                    raw_file=raw_path,
                    source_file_type=source_file_type,
                    source_row_number=row_number,
                    player=player,
                    team_value=raw_row.get("Team"),
                    position="QB",
                    market=market,
                    source_column=source_column_label,
                    value=raw_row.get(source_column),
                    applicable=True,
                )
        else:
            position = _clean_position(raw_row.get("POS"))
            for market, source_column, source_column_label in FLEX_MARKETS:
                value = raw_row.get(source_column)
                numeric_value = _coerce_numeric(value)
                applicable = False if numeric_value is None else _flex_market_is_applicable(position, market, numeric_value)
                _append_projection_row(
                    rows,
                    rejected_rows,
                    seen_keys,
                    metadata=metadata,
                    source=source,
                    raw_file=raw_path,
                    source_file_type=source_file_type,
                    source_row_number=row_number,
                    player=player,
                    team_value=raw_row.get("Team"),
                    position=position,
                    market=market,
                    source_column=source_column_label,
                    value=value,
                    applicable=applicable,
                )

    return rows, rejected_rows


def _api_projection_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    players = payload.get("players")
    if isinstance(players, list):
        return [player for player in players if isinstance(player, dict)]
    if isinstance(players, dict):
        return [player for player in players.values() if isinstance(player, dict)]
    raise ValueError("FantasyPros API response does not contain a players list")


def transform_fantasypros_api_snapshot(payload: dict[str, Any], *, raw_file: Path | str, metadata: SnapshotMetadata, source: str = "fantasypros") -> tuple[list[dict], list[dict]]:
    raw_path = Path(raw_file)
    players = _api_projection_items(payload)
    rows: list[dict] = []
    rejected_rows: list[dict] = []
    seen_keys: set[tuple] = set()

    for index, player_row in enumerate(players):
        source_row_number = index + 1
        raw_player = player_row.get("name") or player_row.get("player_name")
        if not _has_player(raw_player):
            rejected_rows.append(
                {
                    "source_format": "api",
                    "source_file_type": "api",
                    "raw_file": str(raw_path),
                    "source_row_number": source_row_number,
                    "source_json_path": f"players[{index}]",
                    "player": "" if raw_player is None or pd.isna(raw_player) else str(raw_player),
                    "position": "",
                    "market": "",
                    "source_column": "name",
                    "reason": "missing_player",
                    "value": raw_player,
                }
            )
            continue

        player = str(raw_player).strip()
        team_value = player_row.get("team_id") or player_row.get("player_team_id") or player_row.get("team")
        position = _clean_position(player_row.get("position_id") or player_row.get("position") or "")
        stats = player_row.get("stats") or {}
        if not isinstance(stats, dict):
            rejected_rows.append(
                {
                    "source_format": "api",
                    "source_file_type": "api",
                    "raw_file": str(raw_path),
                    "source_row_number": source_row_number,
                    "source_json_path": f"players[{index}].stats",
                    "player": player,
                    "position": position,
                    "market": "",
                    "source_column": "stats",
                    "reason": "missing_stats_object",
                    "value": type(stats).__name__,
                }
            )
            continue

        for market, source_column in API_MARKETS:
            numeric_value = _coerce_numeric(stats.get(source_column))
            if numeric_value is None:
                rejected_rows.append(
                    {
                        "source_format": "api",
                        "source_file_type": "api",
                        "raw_file": str(raw_path),
                        "source_row_number": source_row_number,
                        "source_json_path": f"players[{index}].stats.{source_column}",
                        "player": player,
                        "position": position,
                        "market": market,
                        "source_column": source_column,
                        "reason": "missing_or_nonnumeric_projection",
                        "value": stats.get(source_column),
                    }
                )
                continue

            applicable = True
            if market == "player_pass_yds":
                applicable = position == "QB" or abs(numeric_value) > 1e-9
            elif market == "player_rush_yds":
                applicable = position in {"QB", "RB"} or abs(numeric_value) > 1e-9
            elif market in {"player_receptions", "player_reception_yds"}:
                applicable = position in {"RB", "WR", "TE"} or abs(numeric_value) > 1e-9

            if not applicable:
                rejected_rows.append(
                    {
                        "source_format": "api",
                        "source_file_type": "api",
                        "raw_file": str(raw_path),
                        "source_row_number": source_row_number,
                        "source_json_path": f"players[{index}].stats.{source_column}",
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
            team, team_raw = normalize_team(team_value)
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

            row_payload = {
                "player": player,
                "player_normalized": player_normalized,
                "team": team,
                "team_raw": team_raw,
                "position": position,
                "market": market,
                "projection": numeric_value,
                "source_player_id": player_row.get("fpid") or player_row.get("player_id"),
                "source_row_number": source_row_number,
                "source_column": source_column,
                "source_file_type": "api",
                "raw_file": raw_path,
            }
            output_row = build_output_row(row_payload, metadata=metadata, source=source)
            output_row.update(
                {
                    "source_format": "api",
                    "source_file_type": "api",
                    "fantasypros_player_id": player_row.get("fpid") or player_row.get("player_id"),
                    "source_json_path": f"players[{index}].stats.{source_column}",
                    "endpoint_component": "projections",
                }
            )
            rows.append(output_row)

    return rows, rejected_rows


def transform_fantasypros_snapshot(raw_frames: dict[str, pd.DataFrame], *, metadata: SnapshotMetadata, source: str = "fantasypros") -> tuple[list[dict], list[dict]]:
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
        raise ValueError(f"Incomplete FantasyPros logical snapshot ({'; '.join(pieces)})")

    rows: list[dict] = []
    rejected_rows: list[dict] = []
    seen_keys: set[tuple] = set()
    for source_file_type in ["qb", "flex"]:
        frame = raw_frames[source_file_type]
        raw_path = Path(frame.attrs.get("raw_file", f"{source_file_type}.csv"))
        file_rows, file_rejected = transform_fantasypros_file(
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
        {"metric": "transformed_rows", "value": len(transformed_rows)},
        {"metric": "unique_players", "value": len({row["player_normalized"] for row in transformed_rows})},
        {"metric": "duplicate_canonical_keys", "value": 0},
        {"metric": "timestamp_parser_used", "value": metadata.captured_at_source},
        {"metric": "warnings", "value": " | ".join(warnings) if warnings else ""},
    ]

    for reason, count in sorted(Counter(row.get("reason", "") for row in rejected_rows).items()):
        summary_rows.append({"metric": "rejected_rows", "subgroup": reason, "value": count})
    for source_file_type, count in sorted(Counter(row.get("source_file_type", "") for row in transformed_rows).items()):
        summary_rows.append({"metric": "rows_by_source_file_type", "subgroup": source_file_type, "value": count})
    for position, count in sorted(Counter(row["position"] for row in transformed_rows).items()):
        summary_rows.append({"metric": "rows_by_position", "subgroup": position, "value": count})
    for market, count in sorted(Counter(row["market"] for row in transformed_rows).items()):
        summary_rows.append({"metric": "rows_by_market", "subgroup": market, "value": count})
    for market in sorted(CANONICAL_MARKETS.values()):
        values = [row["projection"] for row in transformed_rows if row["market"] == market]
        if values:
            summary_rows.append({"metric": "min_projection", "subgroup": market, "value": min(values)})
            summary_rows.append({"metric": "median_projection", "subgroup": market, "value": pd.Series(values).median()})
            summary_rows.append({"metric": "mean_projection", "subgroup": market, "value": pd.Series(values).mean()})
            summary_rows.append({"metric": "max_projection", "subgroup": market, "value": max(values)})

    return pd.DataFrame(summary_rows)


def build_api_validation_report(payload: dict[str, Any], transformed_rows: list[dict], rejected_rows: list[dict], metadata: SnapshotMetadata, warnings: list[str]) -> pd.DataFrame:
    players = _api_projection_items(payload)
    summary_rows = [
        {"metric": "raw_rows", "value": len(players)},
        {"metric": "source_format", "value": "api"},
        {"metric": "transformed_rows", "value": len(transformed_rows)},
        {"metric": "unique_players", "value": len({row["player_normalized"] for row in transformed_rows})},
        {"metric": "duplicate_canonical_keys", "value": 0},
        {"metric": "timestamp_parser_used", "value": metadata.captured_at_source},
        {"metric": "warnings", "value": " | ".join(warnings) if warnings else ""},
    ]
    for reason, count in sorted(Counter(row.get("reason", "") for row in rejected_rows).items()):
        summary_rows.append({"metric": "rejected_rows", "subgroup": reason, "value": count})
    for position, count in sorted(Counter(row["position"] for row in transformed_rows).items()):
        summary_rows.append({"metric": "rows_by_position", "subgroup": position, "value": count})
    for market, count in sorted(Counter(row["market"] for row in transformed_rows).items()):
        summary_rows.append({"metric": "rows_by_market", "subgroup": market, "value": count})
    for market in sorted(CANONICAL_MARKETS.values()):
        values = [row["projection"] for row in transformed_rows if row["market"] == market]
        if values:
            series = pd.Series(values)
            summary_rows.append({"metric": "min_projection", "subgroup": market, "value": min(values)})
            summary_rows.append({"metric": "median_projection", "subgroup": market, "value": series.median()})
            summary_rows.append({"metric": "mean_projection", "subgroup": market, "value": series.mean()})
            summary_rows.append({"metric": "max_projection", "subgroup": market, "value": max(values)})
    return pd.DataFrame(summary_rows)


def build_sanity_warnings(rows: list[dict]) -> list[str]:
    warnings: list[str] = []
    frame = pd.DataFrame(rows)
    if frame.empty:
        return ["empty_fantasypros_snapshot"]

    qb_pass = frame.loc[(frame["source_file_type"] == "qb") & (frame["market"] == "player_pass_yds"), "projection"]
    qb_rush = frame.loc[(frame["source_file_type"] == "qb") & (frame["market"] == "player_rush_yds"), "projection"]
    if not qb_pass.empty and not qb_rush.empty and qb_pass.median() <= qb_rush.median():
        warnings.append("sanity_qb_pass_yds_not_materially_above_qb_rush_yds")

    flex_rush = frame.loc[(frame["source_file_type"] == "flex") & (frame["market"] == "player_rush_yds"), "projection"]
    flex_recv = frame.loc[(frame["source_file_type"] == "flex") & (frame["market"] == "player_reception_yds"), "projection"]
    if not flex_rush.empty and not flex_recv.empty:
        rb_rush = frame.loc[(frame["source_file_type"] == "flex") & (frame["position"] == "RB") & (frame["market"] == "player_rush_yds"), "projection"]
        wr_recv = frame.loc[(frame["source_file_type"] == "flex") & (frame["position"].isin(["WR", "TE"])) & (frame["market"] == "player_reception_yds"), "projection"]
        if not rb_rush.empty and not wr_recv.empty and rb_rush.median() < 1 and wr_recv.median() < 1:
            warnings.append("sanity_flex_rush_recv_yds_possible_mass_swap")
    return warnings
