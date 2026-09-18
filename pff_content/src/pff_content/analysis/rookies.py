from __future__ import annotations

from typing import Iterable

import pandas as pd


ROOKIE_METRICS = {
    "qbs": [("pressure_rate_faced", "pressure_rate_faced_rank"), ("twp_per_dropback", "twp_per_dropback_rank"), ("btt_per_dropback", "btt_per_dropback_rank")],
    "receiving": [("targets", "targets_rank"), ("targets_per_route_run", "targets_per_route_run_rank"), ("yprr", "yprr_rank")],
    "rushing": [("yards", "yards_rank"), ("yards_after_contact_per_attempt", "yards_after_contact_per_attempt_rank")],
    "pass_blocking": [("pressures_allowed", "pressures_allowed_rank"), ("pass_blocking_efficiency", "pass_blocking_efficiency_rank")],
    "pass_rush": [("total_pressures", "total_pressures_rank"), ("pressure_rate", "pressure_rate_rank"), ("pass_rush_win_rate", "pass_rush_win_rate_rank")],
    "run_defense": [("stops", "stops_rank"), ("run_stop_rate", "run_stop_rate_rank")],
    "coverage": [("passer_rating_when_targeted", "passer_rating_when_targeted_rank"), ("forced_incompletion_rate", "forced_incompletion_rate_rank")],
}


def build(tables: dict[str, pd.DataFrame], *, top_rank: int = 10) -> pd.DataFrame:
    rows = []
    for category, pairs in ROOKIE_METRICS.items():
        df = tables.get(category)
        if df is None or "rookie" not in df.columns:
            continue
        rookies = df[df["rookie"].fillna(False)]
        for metric, rank_col in pairs:
            if metric not in rookies.columns or rank_col not in rookies.columns:
                continue
            ranks = pd.to_numeric(rookies[rank_col], errors="coerce")
            for row in rookies[ranks.notna() & (ranks <= top_rank)].to_dict("records"):
                rows.append(
                    {
                        "player": row.get("player_name"),
                        "team": row.get("team"),
                        "opponent": row.get("opponent"),
                        "position": row.get("position"),
                        "category": category,
                        "metric": metric,
                        "value": row.get(metric),
                        "rank": row.get(rank_col),
                        "qualifier_context": _qualifier_context(row),
                    }
                )
    return pd.DataFrame(rows).sort_values(["category", "rank", "player"]) if rows else pd.DataFrame(columns=["player", "team", "position", "category", "metric", "value", "rank", "qualifier_context"])


def _qualifier_context(row: dict) -> str:
    parts = []
    for col in ["dropbacks", "routes", "attempts", "pass_block_snaps", "pass_rush_snaps", "run_defense_snaps", "coverage_snaps", "targets"]:
        if col in row and pd.notna(row[col]):
            parts.append(f"{col}={row[col]}")
    return "; ".join(parts)
