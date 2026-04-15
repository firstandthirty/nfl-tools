from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd


# =========================
# PATHS
# =========================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"

BIG_BOARD_PATH = DATA_DIR / "consensus_big_board.csv"
TEAM_NEEDS_PATH = DATA_DIR / "team_needs.csv"
DRAFT_ORDER_PATH = DATA_DIR / "draft_order.csv"
PLAYER_OVERRIDES_PATH = DATA_DIR / "player_overrides.csv"

OUTPUT_DIR.mkdir(exist_ok=True)


# =========================
# MODEL CONSTANTS
# =========================

CONFIG = {
    "POSITION_VALUE": {
        "QB": 1.30,
        "EDGE": 1.18,
        "OT": 1.18,
        "WR": 1.18,
        "CB": 1.10,
        "DT": 1.05,
        "S": 0.90,
        "LB": 0.90,
        "IOL": 0.90,
        "TE": 0.90,
        "RB": 0.90,
    },

    "MARKET_PLAYER_BOOST": {
        #"Arvell Reese": 1.25,
    },

    "MARKET_TEAM_POSITION_BOOST": {
        # ("TEN", "RB"): 1.10,
    },

    "MARKET_TEAM_PLAYER_BOOST": {
        # ("CLE", "Monroe Freeling"): 1.10,
    },

    "TEAM_OT_SIDE_NEEDS": {
        ("CLE", "LT"): 1.25,
        ("CLE", "RT"): 0.50,
    },

    "EXPONENTS": {
        "score": 1.6,
        "board": 1.00,
        "need": 0.75,
    },

    "DEFAULTS": {
        "need_weight": 0.05,
        "position_value": 1.00,
    },

    "SIM": {
        "n_sims": 5000,
        "random_seed": 42,
    },

    "CANDIDATE_POOL": {
        "top5": 10,
        "top10": 12,
        "top20": 14,
        "round1": 18,
        "day2plus": 30,
        "qb_extra_round1": 3,
    },

    "QB_GUARDRAIL": {
        "elite_cutoff": 3,
        "round1_cutoff": 40,
        "fringe_cutoff": 60,

        "mid_need": 0.30,
        "high_need": 0.60,

        "elite_multiplier": 1.00,

        "round1_high_need": 1.00,
        "round1_mid_need": 0.65,
        "round1_top10": 0.20,
        "round1_rest": 0.35,
        "round2plus": 0.50,

        "fringe_high_need": 0.60,
        "fringe_mid_need": 0.35,
        "fringe_top10": 0.05,
        "fringe_round1": 0.12,
        "fringe_round2plus": 0.25,

        "deep_high_need": 0.25,
        "deep_mid_need": 0.12,
        "deep_top10": 0.01,
        "deep_round1": 0.04,
        "deep_round2plus": 0.10,
    },
}

# =========================
# HELPERS
# =========================

def normalize_position(pos: str) -> str:
    pos = str(pos).strip().upper()

    mapping = {
        "OG": "IOL",
        "C": "IOL",
        "G": "IOL",
        "OL": "OT",
        "IDL": "DT",
        "DI": "DT",
        "DL": "DT",
        "FS": "S",
        "SS": "S",
    }
    return mapping.get(pos, pos)


def candidate_pool_size_for_pick(pick: int, config: dict) -> int:
    pool = config["CANDIDATE_POOL"]

    if pick <= 5:
        return pool["top5"]
    if pick <= 10:
        return pool["top10"]
    if pick <= 20:
        return pool["top20"]
    if pick <= 32:
        return pool["round1"]
    return pool["day2plus"]


def board_score_from_rank(rank: int, config: dict) -> float:
    board_exp = config["EXPONENTS"]["board"]
    return 1.0 / (rank ** board_exp)


def get_position_value_multiplier(position: str, pick: int, config: dict) -> float:
    base = config["POSITION_VALUE"].get(
        position,
        config["DEFAULTS"]["position_value"],
    )

    if pick <= 10:
        return base
    if pick <= 32:
        return 1.0 + (base - 1.0) * 0.75
    return 1.0 + (base - 1.0) * 0.50


def apply_qb_guardrail(
    score: float,
    position: str,
    player_rank: int,
    qb_need_weight: float,
    pick: int,
    config: dict,
) -> float:
    if position != "QB":
        return score

    qb = config["QB_GUARDRAIL"]

    elite_cutoff = qb["elite_cutoff"]
    round1_cutoff = qb["round1_cutoff"]
    fringe_cutoff = qb["fringe_cutoff"]

    mid_need = qb["mid_need"]
    high_need = qb["high_need"]

    if player_rank <= elite_cutoff:
        return score * qb["elite_multiplier"]

    if player_rank <= round1_cutoff:
        if qb_need_weight >= high_need:
            return score * qb["round1_high_need"]
        if qb_need_weight >= mid_need:
            return score * qb["round1_mid_need"]
        if pick <= 10:
            return score * qb["round1_top10"]
        if pick <= 32:
            return score * qb["round1_rest"]
        return score * qb["round2plus"]

    if player_rank <= fringe_cutoff:
        if qb_need_weight >= high_need:
            return score * qb["fringe_high_need"]
        if qb_need_weight >= mid_need:
            return score * qb["fringe_mid_need"]
        if pick <= 10:
            return score * qb["fringe_top10"]
        if pick <= 32:
            return score * qb["fringe_round1"]
        return score * qb["fringe_round2plus"]

    if qb_need_weight >= high_need:
        return score * qb["deep_high_need"]
    if qb_need_weight >= mid_need:
        return score * qb["deep_mid_need"]
    if pick <= 10:
        return score * qb["deep_top10"]
    if pick <= 32:
        return score * qb["deep_round1"]
    return score * qb["deep_round2plus"]


def weighted_choice(scored_rows: List[dict], rng: random.Random) -> dict:
    total = sum(row["probability"] for row in scored_rows)
    if total <= 0:
        raise ValueError("Total probability must be > 0")

    r = rng.random() * total
    cumulative = 0.0

    for row in scored_rows:
        cumulative += row["probability"]
        if r <= cumulative:
            return row

    return scored_rows[-1]

def get_market_player_boost(player: str, pick: int, team: str, config: dict) -> float:
    return config["MARKET_PLAYER_BOOST"].get(player, 1.0)


def get_market_team_position_boost(team: str, position: str, pick: int, config: dict) -> float:
    return config["MARKET_TEAM_POSITION_BOOST"].get((team, position), 1.0)


def get_market_team_player_boost(team: str, player: str, pick: int, config: dict) -> float:
    return config["MARKET_TEAM_PLAYER_BOOST"].get((team, player), 1.0)


def get_ot_side_multiplier(team: str, position: str, ot_side: str, config: dict) -> float:
    if position != "OT":
        return 1.0

    ot_side = str(ot_side or "").strip().upper()
    if not ot_side:
        return 1.0

    if ot_side == "SWING":
        lt_need = config["TEAM_OT_SIDE_NEEDS"].get((team, "LT"), 1.0)
        rt_need = config["TEAM_OT_SIDE_NEEDS"].get((team, "RT"), 1.0)
        return (lt_need + rt_need) / 2.0

    return config["TEAM_OT_SIDE_NEEDS"].get((team, ot_side), 1.0)

def apply_elite_player_boost(score: float, rank: int, pick: int) -> float:
    # top 3 prospects = massive gravity
    if rank <= 3:
        return score * 1.35

    # top 5 = strong boost
    if rank <= 5:
        return score * 1.20

    # top 10 = slight boost early
    if rank <= 10 and pick <= 10:
        return score * 1.10

    return score

def apply_reach_penalty(score: float, rank: int, pick: int) -> float:
    # positive = player is falling, negative = player is a reach
    delta = pick - rank

    # no penalty if player is ranked at or above the pick
    if delta >= 0:
        return score

    reach = abs(delta)

    # stronger penalty in round 1
    if pick <= 32:
        if reach >= 12:
            return score * 0.10
        if reach >= 9:
            return score * 0.25
        if reach >= 6:
            return score * 0.50
        if reach >= 3:
            return score * 0.75

    return score

def probability_to_american_odds(p: float) -> str:
    if p <= 0:
        return ""
    if p >= 1:
        return "-inf"

    if p >= 0.5:
        odds = -round((p / (1 - p)) * 100)
    else:
        odds = round(((1 - p) / p) * 100)

    return f"{odds:+d}"

def summarize_player_ou_lines(results_df: pd.DataFrame) -> pd.DataFrame:
    n_sims = results_df["sim_id"].nunique()
    player_minmax = (
        results_df.groupby("player", as_index=False)["pick"]
        .agg(min_pick="min", max_pick="max")
    )

    rows = []

    for row in player_minmax.itertuples(index=False):
        player = row.player
        min_pick = int(row.min_pick)
        max_pick = int(row.max_pick)

        player_picks = results_df.loc[results_df["player"] == player, "pick"]

        best_line = None
        best_diff = float("inf")

        for line in range(min_pick, max_pick):
            # "Under X.5" means drafted at pick <= X
            under_prob = (player_picks <= line).sum() / n_sims
            over_prob = 1 - under_prob

            under_ml = probability_to_american_odds(under_prob)
            over_ml = probability_to_american_odds(over_prob)

            # closest to even money / coin flip
            diff = abs(under_prob - 0.5)

            if diff < best_diff:
                best_diff = diff
                best_line = {
                    "player": player,
                    "line": f"{line}.5",
                    "under_probability": under_prob,
                    "under_moneyline": under_ml,
                    "over_probability": over_prob,
                    "over_moneyline": over_ml,
                    "avg_pick": float(player_picks.mean()),
                }

        if best_line is not None:
            rows.append(best_line)

    return pd.DataFrame(rows).sort_values("avg_pick")

def summarize_player_by_pick_moneyline(results_df: pd.DataFrame) -> pd.DataFrame:
    out = summarize_player_by_pick(results_df).copy()
    out["moneyline"] = out["probability"].apply(probability_to_american_odds)
    return out

#Reduce weight after each pick, making it less likely that teams double up at a position if they have multiple first round picks
def reduce_need_weight(current_weight: float) -> float:
    return max(current_weight * 0.15, 0.05)

def apply_pick_to_need_map(
    need_map: Dict[Tuple[str, str], float],
    team: str,
    position: str,
    config: dict,
) -> None:
    key = (team, position)
    default_need_weight = config["DEFAULTS"]["need_weight"]
    current_weight = need_map.get(key, default_need_weight)
    new_weight = reduce_need_weight(current_weight)
    need_map[key] = new_weight

def summarize_pick_depth(player_by_pick_df: pd.DataFrame) -> pd.DataFrame:
    rows = []

    for pick, group in player_by_pick_df.groupby("pick"):
        rows.append({
            "pick": pick,
            "players_total": len(group),
            "players_ge_1pct": (group["probability"] >= 0.01).sum(),
            "players_ge_2pct": (group["probability"] >= 0.02).sum(),
            "players_ge_5pct": (group["probability"] >= 0.05).sum(),
        })

    return pd.DataFrame(rows).sort_values("pick")

#moneyline for position_by_team_probs
def summarize_position_by_team_moneyline(results_df: pd.DataFrame) -> pd.DataFrame:
    out = summarize_position_by_team(results_df).copy()
    out["moneyline"] = out["probability"].apply(probability_to_american_odds)
    return out

#player drafted by team probs
def summarize_player_by_team_moneyline(results_df: pd.DataFrame) -> pd.DataFrame:
    out = summarize_player_by_team(results_df).copy()
    out["moneyline"] = out["probability"].apply(probability_to_american_odds)
    return out

#draft position by team
def summarize_position_totals(results_df: pd.DataFrame) -> pd.DataFrame:
    n_sims = results_df["sim_id"].nunique()

    counts = (
        results_df.groupby(["sim_id", "position"])
        .size()
        .reset_index(name="count")
    )

    summary = (
        counts.groupby("position")["count"]
        .agg(["mean", "min", "max"])
        .reset_index()
        .rename(columns={"mean": "avg_taken_round1"})
    )

    return summary.sort_values("avg_taken_round1", ascending=False)

#draft position by team o/u
def summarize_position_total_ou_lines(results_df: pd.DataFrame) -> pd.DataFrame:
    n_sims = results_df["sim_id"].nunique()

    counts = (
        results_df.groupby(["sim_id", "position"])
        .size()
        .reset_index(name="count")
    )

    rows = []

    for position in sorted(counts["position"].unique()):
        pos_counts = counts.loc[counts["position"] == position, "count"]

        min_count = int(pos_counts.min())
        max_count = int(pos_counts.max())

        best_line = None
        best_diff = float("inf")

        for line in range(min_count, max_count + 1):
            # line = X.5
            under_prob = (pos_counts <= line).sum() / n_sims
            over_prob = 1 - under_prob

            diff = abs(under_prob - 0.5)

            if diff < best_diff:
                best_diff = diff
                best_line = {
                    "position": position,
                    "line": f"{line}.5",
                    "under_probability": under_prob,
                    "under_moneyline": probability_to_american_odds(under_prob),
                    "over_probability": over_prob,
                    "over_moneyline": probability_to_american_odds(over_prob),
                    "avg_taken_round1": float(pos_counts.mean()),
                }

        if best_line is not None:
            rows.append(best_line)

    return pd.DataFrame(rows).sort_values("avg_taken_round1", ascending=False)

#first selected by position
def summarize_first_selected_by_position(results_df: pd.DataFrame) -> pd.DataFrame:
    n_sims = results_df["sim_id"].nunique()
    rows = []

    for sim_id, sim_group in results_df.groupby("sim_id"):
        for position, pos_group in sim_group.groupby("position"):
            first_row = pos_group.sort_values("pick").iloc[0]
            rows.append({
                "sim_id": sim_id,
                "position": position,
                "player": first_row["player"],
                "pick": int(first_row["pick"]),
                "team": first_row["team"],
            })

    out = (
        pd.DataFrame(rows)
        .groupby(["position", "player"], as_index=False)
        .size()
        .rename(columns={"size": "count"})
    )

    out["probability"] = out["count"] / n_sims
    out["moneyline"] = out["probability"].apply(probability_to_american_odds)

    return out.sort_values(["position", "probability"], ascending=[True, False])

# =========================
# LOADERS
# =========================

def load_big_board(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path).copy()

    rename_map = {
        "Rank": "rank",
        "Player Name": "player",
        "Position": "position",
        "College": "school",
        "OT Side": "ot_side",
    }
    df = df.rename(columns=rename_map)

    required = {"rank", "player", "position"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Big board missing columns: {missing}")

    df["rank"] = df["rank"].astype(int)
    df["player"] = df["player"].astype(str).str.strip()
    df["position"] = df["position"].map(normalize_position)

    if "school" not in df.columns:
        df["school"] = ""
    else:
        df["school"] = df["school"].fillna("").astype(str).str.strip()

    if "ot_side" not in df.columns:
        df["ot_side"] = ""
    else:
        df["ot_side"] = df["ot_side"].fillna("").astype(str).str.strip().str.upper()

    df = df.sort_values("rank").reset_index(drop=True)
    return df

def load_team_needs(path: Path) -> Dict[Tuple[str, str], float]:
    df = pd.read_csv(path).copy()
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"team", "position", "weight"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"team_needs missing columns: {missing}")

    df["team"] = df["team"].astype(str).str.strip().str.upper()
    df["position"] = df["position"].map(normalize_position)
    df["weight"] = df["weight"].astype(float)

    return {
        (row.team, row.position): row.weight
        for row in df.itertuples(index=False)
    }


def load_draft_order(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path).copy()
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"pick", "round", "team"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"draft_order missing columns: {missing}")

    df["pick"] = df["pick"].astype(int)
    df["round"] = df["round"].astype(int)
    df["team"] = df["team"].astype(str).str.strip().str.upper()

    return df.sort_values("pick").reset_index(drop=True)


def load_player_overrides(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["pick", "team", "player", "probability"])

    df = pd.read_csv(path).copy()
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"pick", "team", "player", "probability"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"player_overrides missing columns: {missing}")

    df["pick"] = df["pick"].astype(int)
    df["team"] = df["team"].astype(str).str.strip().str.upper()
    df["player"] = df["player"].astype(str).str.strip()
    df["probability"] = df["probability"].astype(float)

    return df


# =========================
# CORE SCORING
# =========================

def get_override_rows(
    pick: int,
    team: str,
    available_df: pd.DataFrame,
    overrides_df: pd.DataFrame,
) -> pd.DataFrame:
    if overrides_df.empty:
        return overrides_df.copy()

    rows = overrides_df[
        (overrides_df["pick"] == pick) &
        (overrides_df["team"] == team)
    ].copy()

    if rows.empty:
        return rows

    available_players = set(available_df["player"])
    rows = rows[rows["player"].isin(available_players)].copy()
    return rows


def score_candidates(
    team: str,
    pick: int,
    available_df: pd.DataFrame,
    need_map: Dict[Tuple[str, str], float],
    config: dict,
) -> List[dict]:
    pool_size = candidate_pool_size_for_pick(pick, config)
    base_candidates = available_df.nsmallest(pool_size, "rank").copy()

    if pick <= 32:
        qb_extra_n = config["CANDIDATE_POOL"]["qb_extra_round1"]
        qb_extra = available_df[available_df["position"] == "QB"].nsmallest(qb_extra_n, "rank")
        candidates = (
            pd.concat([base_candidates, qb_extra], ignore_index=True)
            .drop_duplicates(subset=["player"])
            .copy()
        )
    else:
        candidates = base_candidates

    qb_need_weight = need_map.get((team, "QB"), 0.0)
    default_need_weight = config["DEFAULTS"]["need_weight"]
    need_exp = config["EXPONENTS"]["need"]
    score_exp = config["EXPONENTS"]["score"]

    scored: List[dict] = []

    for row in candidates.itertuples(index=False):
        player = row.player
        position = row.position
        school = row.school
        rank = int(row.rank)
        ot_side = getattr(row, "ot_side", "")

        need_weight = need_map.get((team, position), default_need_weight)
        board_component = board_score_from_rank(rank, config)
        need_component = max(need_weight, default_need_weight) ** need_exp
        pos_value_component = get_position_value_multiplier(position, pick, config)

        score = board_component * need_component * pos_value_component

        score = apply_qb_guardrail(
            score=score,
            position=position,
            player_rank=rank,
            qb_need_weight=qb_need_weight,
            pick=pick,
            config=config,
        )

        score = apply_elite_player_boost(
            score=score,
            rank=rank,
            pick=pick,
        )

        score = apply_reach_penalty(
            score=score,
            rank=rank,
            pick=pick,
        )

        ot_side_multiplier = get_ot_side_multiplier(team, position, ot_side, config)
        score *= ot_side_multiplier

        market_player_boost = get_market_player_boost(player, pick, team, config)
        market_team_pos_boost = get_market_team_position_boost(team, position, pick, config)
        market_team_player_boost = get_market_team_player_boost(team, player, pick, config)

        score *= market_player_boost
        score *= market_team_pos_boost
        score *= market_team_player_boost

        scored.append({
            "player": player,
            "position": position,
            "school": school,
            "rank": rank,
            "ot_side": ot_side,
            "need_weight": need_weight,
            "board_component": board_component,
            "pos_value_component": pos_value_component,
            "ot_side_multiplier": ot_side_multiplier,
            "score": score,
            "market_player_boost": market_player_boost,
            "market_team_pos_boost": market_team_pos_boost,
            "market_team_player_boost": market_team_player_boost,
        })

    for x in scored:
        x["score"] = x["score"] ** score_exp

    total_score = sum(x["score"] for x in scored)

    if total_score <= 0:
        uniform = 1.0 / len(scored)
        for x in scored:
            x["probability"] = uniform
        return sorted(scored, key=lambda x: x["probability"], reverse=True)

    for x in scored:
        x["probability"] = x["score"] / total_score

    return sorted(scored, key=lambda x: x["probability"], reverse=True)


def make_pick(
    team: str,
    pick: int,
    round_num: int,
    available_df: pd.DataFrame,
    need_map: Dict[Tuple[str, str], float],
    overrides_df: pd.DataFrame,
    config: dict,
    rng: random.Random,
) -> Tuple[dict, List[dict]]:
    # 1. player overrides
    override_rows = get_override_rows(
        pick=pick,
        team=team,
        available_df=available_df,
        overrides_df=overrides_df,
    )

    if not override_rows.empty:
        rows = []
        total = override_rows["probability"].sum()

        if total <= 0:
            override_rows = override_rows.copy()
            override_rows["probability"] = 1.0 / len(override_rows)
        else:
            override_rows = override_rows.copy()
            override_rows["probability"] = override_rows["probability"] / total

        for row in override_rows.itertuples(index=False):
            player_row = available_df.loc[available_df["player"] == row.player].iloc[0]
            rows.append({
                "player": player_row["player"],
                "position": player_row["position"],
                "school": player_row["school"],
                "rank": int(player_row["rank"]),
                "probability": float(row.probability),
                "selection_source": "override",
            })

        chosen = weighted_choice(rows, rng)
        result = {
            "pick": pick,
            "round": round_num,
            "team": team,
            "player": chosen["player"],
            "position": chosen["position"],
            "school": chosen["school"],
            "rank": chosen["rank"],
            "selection_source": "override",
        }
        return result, rows

    # 2. model scoring
    scored = score_candidates(
        team=team,
        pick=pick,
        available_df=available_df,
        need_map=need_map,
        config=config,
    )
    chosen = weighted_choice(scored, rng)

    result = {
        "pick": pick,
        "round": round_num,
        "team": team,
        "player": chosen["player"],
        "position": chosen["position"],
        "school": chosen["school"],
        "rank": chosen["rank"],
        "selection_source": "model",
    }
    return result, scored


# =========================
# SIMULATION
# =========================
def run_single_mock(
    draft_order_df: pd.DataFrame,
    big_board_df: pd.DataFrame,
    need_map: Dict[Tuple[str, str], float],
    overrides_df: pd.DataFrame,
    config: dict,
    rng: random.Random,
    sim_id: int | None = None,
) -> pd.DataFrame:

    sim_need_map = dict(need_map)

    available_df = big_board_df.copy()
    picks = []

    for row in draft_order_df.itertuples(index=False):
        result, _ = make_pick(
            team=row.team,
            pick=int(row.pick),
            round_num=1,
            available_df=available_df,
            need_map=sim_need_map,
            overrides_df=overrides_df,
            config=config,
            rng=rng,
        )

        if sim_id is not None:
            result["sim_id"] = sim_id

        picks.append(result)
        available_df = available_df[available_df["player"] != result["player"]].copy()

        apply_pick_to_need_map(
            need_map=sim_need_map,
            team=result["team"],
            position=result["position"],
            config=config,
        )

    return pd.DataFrame(picks)

def run_simulations(
    n_sims: int,
    draft_order_df: pd.DataFrame,
    big_board_df: pd.DataFrame,
    need_map: Dict[Tuple[str, str], float],
    overrides_df: pd.DataFrame,
    config: dict,
    seed: int = 42,
) -> pd.DataFrame:
    rng = random.Random(seed)
    all_results = []

    for sim_id in range(1, n_sims + 1):
        mock_df = run_single_mock(
            draft_order_df=draft_order_df,
            big_board_df=big_board_df,
            need_map=need_map,
            overrides_df=overrides_df,
            config=config,
            rng=rng,
            sim_id=sim_id,
        )
        all_results.append(mock_df)

    return pd.concat(all_results, ignore_index=True)

# =========================
# AGGREGATION
# =========================

def summarize_player_by_pick(results_df: pd.DataFrame) -> pd.DataFrame:
    n_sims = results_df["sim_id"].nunique()
    out = (
        results_df.groupby(["pick", "player", "position"], as_index=False)
        .size()
        .rename(columns={"size": "count"})
    )
    out["probability"] = out["count"] / n_sims
    return out.sort_values(["pick", "probability"], ascending=[True, False])


def summarize_player_by_team(results_df: pd.DataFrame) -> pd.DataFrame:
    n_sims = results_df["sim_id"].nunique()
    out = (
        results_df.groupby(["team", "player", "position"], as_index=False)
        .size()
        .rename(columns={"size": "count"})
    )
    out["probability"] = out["count"] / n_sims
    return out.sort_values(["team", "probability"], ascending=[True, False])


def summarize_position_by_team(results_df: pd.DataFrame) -> pd.DataFrame:
    n_sims = results_df["sim_id"].nunique()
    out = (
        results_df.groupby(["team", "position"], as_index=False)
        .size()
        .rename(columns={"size": "count"})
    )
    out["probability"] = out["count"] / n_sims
    return out.sort_values(["team", "probability"], ascending=[True, False])


def summarize_adp(results_df: pd.DataFrame) -> pd.DataFrame:
    out = (
        results_df.groupby(["player", "position"], as_index=False)["pick"]
        .mean()
        .rename(columns={"pick": "avg_pick"})
        .sort_values("avg_pick")
    )
    return out


# =========================
# MAIN
# =========================

def main() -> None:
    print("Loading data...")
    print("Running with config:")
    print(CONFIG)
    big_board_df = load_big_board(BIG_BOARD_PATH)
    need_map = load_team_needs(TEAM_NEEDS_PATH)
    draft_order_df = load_draft_order(DRAFT_ORDER_PATH)
    overrides_df = load_player_overrides(PLAYER_OVERRIDES_PATH)

    print("\nRunning one mock draft preview...")
    preview_rng = random.Random(CONFIG["SIM"]["random_seed"])
    preview_df = run_single_mock(
        draft_order_df=draft_order_df,
        big_board_df=big_board_df,
        need_map=need_map,
        overrides_df=overrides_df,
        config=CONFIG,
        rng=preview_rng,
    )
    print(preview_df.head(20).to_string(index=False))

    preview_path = OUTPUT_DIR / "single_mock_preview.csv"
    preview_df.to_csv(preview_path, index=False)
    print(f"\nWrote {preview_path}")

    print(f"\nRunning {N_SIMS} simulations...")
    results_df = run_simulations(
        n_sims=CONFIG["SIM"]["n_sims"],
        draft_order_df=draft_order_df,
        big_board_df=big_board_df,
        need_map=need_map,
        overrides_df=overrides_df,
        config=CONFIG,
        seed=CONFIG["SIM"]["random_seed"],
    )

    simulated_picks_path = OUTPUT_DIR / "simulated_picks.csv"
    results_df.to_csv(simulated_picks_path, index=False)
    print(f"Wrote {simulated_picks_path}")

    player_by_pick_ml_df = summarize_player_by_pick_moneyline(results_df)
    player_by_pick_ml_path = OUTPUT_DIR / "player_by_pick_moneyline.csv"
    player_by_pick_ml_df.to_csv(player_by_pick_ml_path, index=False)
    print(f"Wrote {player_by_pick_ml_path}")

    player_ou_df = summarize_player_ou_lines(results_df)
    player_ou_path = OUTPUT_DIR / "player_ou_lines.csv"
    player_ou_df.to_csv(player_ou_path, index=False)
    print(f"Wrote {player_ou_path}")

    player_by_pick_df = summarize_player_by_pick(results_df)
    player_by_team_df = summarize_player_by_team(results_df)
    position_by_team_df = summarize_position_by_team(results_df)
    adp_df = summarize_adp(results_df)

    pick_depth_df = summarize_pick_depth(player_by_pick_df)
    pick_depth_path = OUTPUT_DIR / "pick_depth_summary.csv"
    pick_depth_df.to_csv(pick_depth_path, index=False)
    print(f"Wrote {pick_depth_path}")

    position_by_team_ml_df = summarize_position_by_team_moneyline(results_df)
    position_by_team_ml_path = OUTPUT_DIR / "position_by_team_moneyline.csv"
    position_by_team_ml_df.to_csv(position_by_team_ml_path, index=False)
    print(f"Wrote {position_by_team_ml_path}")
def main() -> None:
    print("Loading data...")
    print("Running with config:")
    print(CONFIG)

    big_board_df = load_big_board(BIG_BOARD_PATH)
    need_map = load_team_needs(TEAM_NEEDS_PATH)
    draft_order_df = load_draft_order(DRAFT_ORDER_PATH)
    overrides_df = load_player_overrides(PLAYER_OVERRIDES_PATH)

    print("\nRunning one mock draft preview...")
    preview_rng = random.Random(CONFIG["SIM"]["random_seed"])
    preview_df = run_single_mock(
        draft_order_df=draft_order_df,
        big_board_df=big_board_df,
        need_map=need_map,
        overrides_df=overrides_df,
        config=CONFIG,
        rng=preview_rng,
    )
    print(preview_df.head(20).to_string(index=False))

    preview_path = OUTPUT_DIR / "single_mock_preview.csv"
    preview_df.to_csv(preview_path, index=False)
    print(f"\nWrote {preview_path}")

    print(f"\nRunning {CONFIG['SIM']['n_sims']} simulations...")
    results_df = run_simulations(
        n_sims=CONFIG["SIM"]["n_sims"],
        draft_order_df=draft_order_df,
        big_board_df=big_board_df,
        need_map=need_map,
        overrides_df=overrides_df,
        config=CONFIG,
        seed=CONFIG["SIM"]["random_seed"],
    )

    simulated_picks_path = OUTPUT_DIR / "simulated_picks.csv"
    results_df.to_csv(simulated_picks_path, index=False)
    print(f"Wrote {simulated_picks_path}")

    player_by_pick_ml_df = summarize_player_by_pick_moneyline(results_df)
    player_by_pick_ml_path = OUTPUT_DIR / "player_by_pick_moneyline.csv"
    player_by_pick_ml_df.to_csv(player_by_pick_ml_path, index=False)
    print(f"Wrote {player_by_pick_ml_path}")

    player_ou_df = summarize_player_ou_lines(results_df)
    player_ou_path = OUTPUT_DIR / "player_ou_lines.csv"
    player_ou_df.to_csv(player_ou_path, index=False)
    print(f"Wrote {player_ou_path}")

    player_by_pick_df = summarize_player_by_pick(results_df)
    player_by_team_df = summarize_player_by_team(results_df)
    position_by_team_df = summarize_position_by_team(results_df)
    adp_df = summarize_adp(results_df)

    pick_depth_df = summarize_pick_depth(player_by_pick_df)
    pick_depth_path = OUTPUT_DIR / "pick_depth_summary.csv"
    pick_depth_df.to_csv(pick_depth_path, index=False)
    print(f"Wrote {pick_depth_path}")

    position_by_team_ml_df = summarize_position_by_team_moneyline(results_df)
    position_by_team_ml_path = OUTPUT_DIR / "position_by_team_moneyline.csv"
    position_by_team_ml_df.to_csv(position_by_team_ml_path, index=False)
    print(f"Wrote {position_by_team_ml_path}")

    player_by_team_ml_df = summarize_player_by_team_moneyline(results_df)
    player_by_team_ml_path = OUTPUT_DIR / "player_by_team_moneyline.csv"
    player_by_team_ml_df.to_csv(player_by_team_ml_path, index=False)
    print(f"Wrote {player_by_team_ml_path}")

    position_totals_df = summarize_position_totals(results_df)
    position_totals_path = OUTPUT_DIR / "position_totals.csv"
    position_totals_df.to_csv(position_totals_path, index=False)
    print(f"Wrote {position_totals_path}")

    position_total_ou_df = summarize_position_total_ou_lines(results_df)
    position_total_ou_path = OUTPUT_DIR / "position_total_ou_lines.csv"
    position_total_ou_df.to_csv(position_total_ou_path, index=False)
    print(f"Wrote {position_total_ou_path}")

    player_by_pick_path = OUTPUT_DIR / "player_by_pick_probs.csv"
    player_by_team_path = OUTPUT_DIR / "player_by_team_probs.csv"
    position_by_team_path = OUTPUT_DIR / "position_by_team_probs.csv"
    adp_path = OUTPUT_DIR / "player_adp.csv"

    player_by_pick_df.to_csv(player_by_pick_path, index=False)
    player_by_team_df.to_csv(player_by_team_path, index=False)
    position_by_team_df.to_csv(position_by_team_path, index=False)
    adp_df.to_csv(adp_path, index=False)

    print(f"Wrote {player_by_pick_path}")
    print(f"Wrote {player_by_team_path}")
    print(f"Wrote {position_by_team_path}")
    print(f"Wrote {adp_path}")


if __name__ == "__main__":
    main()