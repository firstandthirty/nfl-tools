from __future__ import annotations

import pandas as pd

from .qualifiers import QUALIFIERS, add_rank, safe_divide


def build(passing: pd.DataFrame) -> pd.DataFrame:
    df = passing.copy()
    df["pressure_rate_faced"] = safe_divide(df["def_gen_pressures"], df["dropbacks"]) if {"def_gen_pressures", "dropbacks"}.issubset(df.columns) else pd.NA
    df["twp_per_dropback"] = safe_divide(df["turnover_worthy_plays"], df["dropbacks"])
    df["btt_per_dropback"] = safe_divide(df["big_time_throws"], df["dropbacks"])
    df["int_minus_twp"] = pd.to_numeric(df["interceptions"], errors="coerce") - pd.to_numeric(df["turnover_worthy_plays"], errors="coerce")
    df["potential_turnover_fortune"] = (df["turnover_worthy_plays"] >= 2) & (df["interceptions"] == 0)
    df["potential_turnover_misfortune"] = df["interceptions"] > df["turnover_worthy_plays"]
    df["qualified_qb"] = df["dropbacks"] >= QUALIFIERS["qb_min_dropbacks"]
    for metric, ascending in [
        ("pressure_rate_faced", False),
        ("avg_time_to_throw", False),
        ("btt_per_dropback", False),
        ("twp_per_dropback", False),
    ]:
        if metric in df.columns:
            df = add_rank(df, metric, f"{metric}_rank", ascending=ascending, qualified_col="qualified_qb")
    keep = [
        "season", "week", "game_id", "player_id", "player_name", "team", "opponent", "position", "draft_season", "rookie",
        "dropbacks", "attempts", "completions", "yards", "touchdowns", "interceptions", "turnover_worthy_plays",
        "big_time_throws", "avg_depth_of_target", "avg_time_to_throw", "def_gen_pressures", "pressure_rate_faced",
        "pressure_to_sack_rate", "sacks", "twp_per_dropback", "btt_per_dropback", "int_minus_twp",
        "potential_turnover_fortune", "potential_turnover_misfortune", "qualified_qb",
        "pressure_rate_faced_rank", "pressure_rate_faced_rank_qualified_count", "avg_time_to_throw_rank",
        "btt_per_dropback_rank", "twp_per_dropback_rank",
    ]
    return df[[col for col in keep if col in df.columns]].sort_values(["qualified_qb", "pressure_rate_faced"], ascending=[False, False])
