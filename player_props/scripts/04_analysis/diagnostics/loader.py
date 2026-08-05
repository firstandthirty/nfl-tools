from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import clean_side, decimal_profit, numeric, to_bool


@dataclass(frozen=True)
class LoadResult:
    raw: pd.DataFrame
    df: pd.DataFrame
    column_map: dict[str, str]
    warnings: list[str]
    edge_metadata: list[dict[str, object]]


ALIASES: dict[str, list[str]] = {
    "market": ["market_key", "market", "prop_market", "stat_market"],
    "side": ["recommended_side", "side", "bet_side", "pick", "direction", "model_side"],
    "line": ["line", "point", "prop_line", "sportsbook_line", "book_line"],
    "odds": ["bet_odds", "odds", "american_odds", "price", "sportsbook_odds"],
    "projection": ["projection", "projected_stat", "model_projection", "proj", "weighted_projection"],
    "predicted_probability": ["recommended_prob", "pred_prob", "predicted_probability", "model_prob", "p_win"],
    "ev_percent": ["recommended_ev_percent", "ev_percent", "ev_pct"],
    "profit": ["profit_1u", "profit_units", "profit", "net_profit", "units", "pnl"],
    "actual": ["actual", "actual_stat", "result_value", "observed"],
    "player": ["player", "player_name", "name"],
    "team": ["team", "player_team", "team_abbr", "posteam"],
    "opponent": ["opponent", "opp", "opponent_team", "defteam"],
    "season": ["season", "year"],
    "week": ["week", "game_week"],
    "position": ["position", "pos", "player_position"],
    "book": ["book", "bookmaker", "sportsbook"],
}


def _resolve(columns: list[str], aliases: list[str]) -> str | None:
    lower = {col.lower(): col for col in columns}
    for alias in aliases:
        if alias in columns:
            return alias
        if alias.lower() in lower:
            return lower[alias.lower()]
    return None


def resolve_columns(raw: pd.DataFrame) -> dict[str, str]:
    return {
        canonical: resolved
        for canonical, aliases in ALIASES.items()
        if (resolved := _resolve(list(raw.columns), aliases)) is not None
    }


def read_input(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise ValueError(f"input file does not exist: {path}")
    raw = pd.read_csv(path, low_memory=False)
    if raw.empty:
        raise ValueError("input CSV has no rows.")
    return raw


def _derive_won(df: pd.DataFrame, warnings: list[str]) -> pd.Series:
    if "bet_won" in df.columns:
        return to_bool(df["bet_won"])
    needed = {"actual_value", "line_value", "side"}
    if needed.issubset(df.columns):
        warnings.append("bet_won missing; inferred wins from actual, line, and side.")
        return pd.Series(
            np.where(
                df["side"].eq("over"),
                df["actual_value"] > df["line_value"],
                df["actual_value"] < df["line_value"],
            ),
            index=df.index,
        )
    return pd.Series(False, index=df.index)


def _derive_pushed(df: pd.DataFrame, warnings: list[str]) -> pd.Series:
    if "bet_pushed" in df.columns:
        return to_bool(df["bet_pushed"])
    if {"actual_value", "line_value"}.issubset(df.columns):
        warnings.append("bet_pushed missing; inferred pushes from actual == line.")
        return df["actual_value"].eq(df["line_value"])
    return pd.Series(False, index=df.index)


def standardize_frame(raw: pd.DataFrame, market: str | None = None) -> LoadResult:
    df = raw.copy()
    warnings: list[str] = []
    column_map = resolve_columns(raw)

    if "market" in column_map:
        df["market"] = df[column_map["market"]].astype("string").str.strip()
    if market:
        if "market" not in df:
            raise ValueError("--market was supplied, but no market column was recognized.")
        mask = df["market"].astype("string").str.lower().eq(str(market).lower())
        df = df[mask].copy()
        if df.empty:
            raise ValueError(f"no rows matched market={market!r}.")

    if "side" in column_map:
        df["side"] = clean_side(df[column_map["side"]])
    if "line" in column_map:
        df["line_value"] = numeric(df[column_map["line"]])
    if "odds" in column_map:
        df["bet_odds_value"] = numeric(df[column_map["odds"]])
    if "projection" in column_map:
        df["projection_value"] = numeric(df[column_map["projection"]])
    if "actual" in column_map:
        df["actual_value"] = numeric(df[column_map["actual"]])
    if "predicted_probability" in column_map:
        df["predicted_probability"] = numeric(df[column_map["predicted_probability"]])
        if not df["predicted_probability"].dropna().between(0, 1, inclusive="both").all():
            warnings.append("recommended probability contains values outside [0, 1]; probability calibration skipped for invalid rows.")
    if "ev_percent" in column_map:
        df["recommended_ev_percent_value"] = numeric(df[column_map["ev_percent"]])
    for canonical in ["player", "team", "opponent", "position", "book"]:
        if canonical in column_map:
            df[canonical] = df[column_map[canonical]].astype("string").str.strip()
    for canonical in ["season", "week"]:
        if canonical in column_map:
            df[canonical] = numeric(df[column_map[canonical]]).astype("Int64")

    if "projection_minus_line" in df.columns:
        df["projection_minus_line_value"] = numeric(df["projection_minus_line"])
    elif {"projection_value", "line_value"}.issubset(df.columns):
        df["projection_minus_line_value"] = df["projection_value"] - df["line_value"]
        warnings.append("projection_minus_line missing; derived as projection - line.")
    if "edge" in df.columns:
        df["raw_edge_signed"] = numeric(df["edge"])
    if "projection_minus_line_value" in df.columns:
        df["projection_edge"] = df["projection_minus_line_value"]
    if "edge_receptions" in df.columns:
        df["absolute_projection_edge"] = numeric(df["edge_receptions"])
    elif "projection_minus_line_value" in df.columns:
        df["absolute_projection_edge"] = df["projection_minus_line_value"].abs()
        warnings.append("edge_receptions missing; derived absolute projection edge from projection_minus_line.")

    df["pushed"] = _derive_pushed(df, warnings).astype(bool)
    df["won"] = _derive_won(df, warnings).astype(bool)
    if "profit" in column_map:
        df["profit_units"] = numeric(df[column_map["profit"]])
    elif "bet_odds_value" in df:
        df["profit_units"] = decimal_profit(df["bet_odds_value"], df["won"], df["pushed"])
        warnings.append("profit_1u missing; derived decimal-odds profit per 1 unit risked.")
    else:
        df["profit_units"] = np.nan

    if df["profit_units"].notna().sum() == 0:
        raise ValueError("no bets could be graded; supply profit_1u or sufficient outcome/odds fields.")

    edge_metadata = [
        {
            "field": "raw_edge_signed",
            "source_column": "edge" if "edge" in raw.columns else "NOT FOUND",
            "interpreted_unit": "receptions, signed; equals projection_minus_line when present",
            "verified": bool("edge" in raw.columns and "projection_minus_line" in raw.columns and np.allclose(numeric(raw["edge"]), numeric(raw["projection_minus_line"]), equal_nan=True)),
        },
        {
            "field": "projection_edge",
            "source_column": "projection_minus_line" if "projection_minus_line" in raw.columns else "derived",
            "interpreted_unit": "receptions, signed projection-minus-line",
            "verified": "projection_minus_line_value" in df.columns,
        },
        {
            "field": "absolute_projection_edge",
            "source_column": "edge_receptions" if "edge_receptions" in raw.columns else "derived",
            "interpreted_unit": "receptions, absolute projection-minus-line",
            "verified": "absolute_projection_edge" in df.columns,
        },
    ]
    return LoadResult(raw=raw, df=df, column_map=column_map, warnings=warnings, edge_metadata=edge_metadata)
