from __future__ import annotations

import pandas as pd


def join_projections_to_odds(projections: pd.DataFrame, odds: pd.DataFrame) -> dict[str, pd.DataFrame]:
    projection_keys = ["season", "week", "player_normalized", "market"]
    odds_keys = ["season", "week", "player_normalized", "market"]
    projections = projections.copy()
    odds = odds.copy()
    joined = projections.merge(odds, left_on=projection_keys, right_on=odds_keys, how="inner", suffixes=("_projection", "_odds"))
    if not joined.empty:
        joined["projection_match_status"] = "matched"
        joined["player_match_status"] = "matched"
        joined["market_match_status"] = "matched"
        if "team_projection" in joined.columns and "team_odds" in joined.columns:
            joined["team_conflict"] = (joined["team_projection"].astype(str) != joined["team_odds"].astype(str)) & joined["team_projection"].notna() & joined["team_odds"].notna()
        else:
            joined["team_conflict"] = False

    odds_key_df = odds[odds_keys].drop_duplicates() if not odds.empty else pd.DataFrame(columns=odds_keys)
    proj_key_df = projections[projection_keys].drop_duplicates() if not projections.empty else pd.DataFrame(columns=projection_keys)
    unmatched_projection = projections.merge(odds_key_df, on=projection_keys, how="left", indicator=True)
    unmatched_projection = unmatched_projection.loc[unmatched_projection["_merge"] == "left_only"].drop(columns=["_merge"])
    if not unmatched_projection.empty:
        player_keys = odds[["season", "week", "player_normalized"]].drop_duplicates() if not odds.empty else pd.DataFrame(columns=["season", "week", "player_normalized"])
        market_keys = odds[["season", "week", "market"]].drop_duplicates() if not odds.empty else pd.DataFrame(columns=["season", "week", "market"])
        unmatched_projection["unmatched_projection"] = True
        unmatched_projection["player_match_status"] = unmatched_projection.merge(player_keys, on=["season", "week", "player_normalized"], how="left", indicator=True)["_merge"].map({"both": "matched", "left_only": "unmatched"}).values
        unmatched_projection["market_match_status"] = unmatched_projection.merge(market_keys, on=["season", "week", "market"], how="left", indicator=True)["_merge"].map({"both": "matched", "left_only": "unmatched"}).values
        unmatched_projection["projection_match_status"] = "unmatched"

    unmatched_odds = odds.merge(proj_key_df, left_on=odds_keys, right_on=projection_keys, how="left", indicator=True)
    unmatched_odds = unmatched_odds.loc[unmatched_odds["_merge"] == "left_only"].drop(columns=["_merge"])
    if not unmatched_odds.empty:
        unmatched_odds["unmatched_odds"] = True
    return {"joined": joined, "unmatched_projection": unmatched_projection, "unmatched_odds": unmatched_odds}

