from __future__ import annotations

from copy import deepcopy
import json
import math
import random
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd


# =========================
# PATHS
# =========================

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
CLEAN_DATA_DIR = DATA_DIR / "clean"
OUTCOMES_DATA_DIR = DATA_DIR / "outcomes"
OUTPUT_DIR = BASE_DIR / "output"
MODELS_DIR = BASE_DIR / "models"
RUNS_DIR = OUTPUT_DIR / "runs"
EXPERIMENTS_DIR = OUTPUT_DIR / "experiments"

BIG_BOARD_PATH = DATA_DIR / "consensus_big_board.csv"
TEAM_NEEDS_PATH = DATA_DIR / "team_needs.csv"
DRAFT_ORDER_PATH = DATA_DIR / "draft_order.csv"
PLAYER_OVERRIDES_PATH = DATA_DIR / "player_overrides.csv"
MARKET_CLEAN_PATH = CLEAN_DATA_DIR / "market_dk_clean.csv"
NFL_IQ_CLEAN_PATH = CLEAN_DATA_DIR / "nfl_iq_rankings.csv"
ACTUAL_DRAFT_RESULTS_PATH = OUTCOMES_DATA_DIR / "actual_draft_results.csv"

OUTPUT_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)
EXPERIMENTS_DIR.mkdir(parents=True, exist_ok=True)


# =========================
# MODEL CONSTANTS
# =========================

CONFIG = {
    "MODEL_VERSION": "v1",
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

    "FALL_PENALTY": {
        "enabled": True,
        "grace_window": 2,
        "power": 1.0,
        "min_multiplier": 0.35,
    },

    "NFL_IQ_SIGNAL": {
        "enabled": True,
        "board_delta_strength": 0.35,
        "pick_fit_strength": 0.60,
        "pick_fit_width": 24.0,
        "min_multiplier": 0.65,
        "max_multiplier": 2.25,
    },
}

RUN_EXPERIMENTS = False

EXPERIMENTS: list[dict] = [
    {
        "experiment_name": "baseline",
        "overrides": {},
    },
    {
        "experiment_name": "score_1_40",
        "overrides": {
            "EXPONENTS": {
                "score": 1.40,
            },
        },
    },
    {
        "experiment_name": "score_1_30",
        "overrides": {
            "EXPONENTS": {
                "score": 1.30,
            },
        },
    },
    {
        "experiment_name": "fall_tighter",
        "overrides": {
            "FALL_PENALTY": {
                "grace_window": 1,
                "power": 1.15,
                "min_multiplier": 0.30,
            },
        },
    },
    {
        "experiment_name": "score_1_40_fall_tighter",
        "overrides": {
            "EXPONENTS": {
                "score": 1.40,
            },
            "FALL_PENALTY": {
                "grace_window": 1,
                "power": 1.15,
                "min_multiplier": 0.30,
            },
        },
    },
    {
        "experiment_name": "score_1_30_need_0_65",
        "overrides": {
            "EXPONENTS": {
                "score": 1.30,
                "need": 0.65,
            },
        },
    },
]

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


def normalize_player_name(player: str) -> str:
    return str(player).strip()


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


def make_json_safe(value):
    if isinstance(value, dict):
        safe_dict = {}
        for key, item in value.items():
            if isinstance(key, tuple):
                safe_key = " | ".join(str(part) for part in key)
            else:
                safe_key = str(key)
            safe_dict[safe_key] = make_json_safe(item)
        return safe_dict

    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]

    if isinstance(value, Path):
        return str(value)

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    return value


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(make_json_safe(payload), f, indent=2)


def read_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def deep_update_dict(base: dict, overrides: dict) -> dict:
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            deep_update_dict(base[key], value)
        else:
            base[key] = value
    return base


def build_experiment_config(base_config: dict, overrides: dict, experiment_name: str) -> dict:
    config = deepcopy(base_config)
    deep_update_dict(config, overrides)
    config["EXPERIMENT_NAME"] = experiment_name
    return config


def get_model_version(config: dict) -> str:
    return str(config.get("MODEL_VERSION", "v1"))


def build_run_paths(model_version: str, timestamp: datetime | None = None) -> dict[str, Path]:
    run_timestamp = timestamp or datetime.now()
    timestamp_str = run_timestamp.strftime("%Y-%m-%d_%H%M%S")
    run_dir = RUNS_DIR / f"{timestamp_str}_{model_version}"

    return {
        "run_dir": run_dir,
        "model_config": MODELS_DIR / f"{model_version}_config.json",
        "run_config": run_dir / "config.json",
        "metadata": run_dir / "metadata.json",
        "run_summary": run_dir / "run_summary.json",
        "preview": run_dir / "single_mock_preview.csv",
        "simulated_picks": run_dir / "simulated_picks.csv",
        "player_by_pick_moneyline": run_dir / "player_by_pick_moneyline.csv",
        "player_ou_lines": run_dir / "player_ou_lines.csv",
        "pick_depth_summary": run_dir / "pick_depth_summary.csv",
        "position_by_team_moneyline": run_dir / "position_by_team_moneyline.csv",
        "player_by_team_moneyline": run_dir / "player_by_team_moneyline.csv",
        "position_totals": run_dir / "position_totals.csv",
        "position_total_ou_lines": run_dir / "position_total_ou_lines.csv",
        "player_by_pick_probs": run_dir / "player_by_pick_probs.csv",
        "player_by_team_probs": run_dir / "player_by_team_probs.csv",
        "position_by_team_probs": run_dir / "position_by_team_probs.csv",
        "player_adp": run_dir / "player_adp.csv",
        "exact_pick_probs": run_dir / "exact_pick_probs.csv",
        "team_player_probs": run_dir / "team_player_probs.csv",
        "model_vs_market_exact_pick": run_dir / "model_vs_market_exact_pick.csv",
        "model_vs_market_summary": run_dir / "model_vs_market_summary.json",
        "model_vs_actual_exact_pick": run_dir / "model_vs_actual_exact_pick.csv",
        "model_vs_actual_summary": run_dir / "model_vs_actual_summary.json",
        "calibration_exact_pick": run_dir / "calibration_exact_pick.csv",
        "edge_vs_actual_exact_pick": run_dir / "edge_vs_actual_exact_pick.csv",
        "diff_exact_pick_probs": run_dir / "diff_exact_pick_probs.csv",
        "diff_team_player_probs": run_dir / "diff_team_player_probs.csv",
        "diff_summary": run_dir / "diff_summary.json",
    }


def build_run_metadata(
    *,
    model_version: str,
    timestamp: datetime,
    config: dict,
) -> dict:
    return {
        "model_version": model_version,
        "timestamp": timestamp.isoformat(timespec="seconds"),
        "n_sims": config["SIM"]["n_sims"],
        "random_seed": config["SIM"]["random_seed"],
        "input_file_paths": {
            "big_board": str(BIG_BOARD_PATH),
            "team_needs": str(TEAM_NEEDS_PATH),
            "draft_order": str(DRAFT_ORDER_PATH),
            "player_overrides": str(PLAYER_OVERRIDES_PATH),
            "nfl_iq": str(NFL_IQ_CLEAN_PATH),
        },
    }

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


def extract_candidate_features(
    *,
    player: str,
    position: str,
    rank: int,
    pick: int,
    ot_side: str,
) -> dict:
    normalized_ot_side = str(ot_side or "").strip().upper()

    return {
        "is_qb": position == "QB",
        "is_round1_qb_candidate": position == "QB" and rank <= 40 and pick <= 32,
        "is_lt": normalized_ot_side == "LT",
        "is_rt": normalized_ot_side == "RT",
        "has_ot_side": bool(normalized_ot_side),
        "is_top_10_player": rank <= 10,
        "is_top_20_player": rank <= 20,
    }


def get_qb_guardrail_multiplier(
    *,
    position: str,
    player_rank: int,
    qb_need_weight: float,
    pick: int,
    config: dict,
) -> float:
    return apply_qb_guardrail(
        score=1.0,
        position=position,
        player_rank=player_rank,
        qb_need_weight=qb_need_weight,
        pick=pick,
        config=config,
    )


def get_elite_player_multiplier(rank: int, pick: int) -> float:
    return apply_elite_player_boost(score=1.0, rank=rank, pick=pick)


def get_reach_penalty_multiplier(rank: int, pick: int) -> float:
    return apply_reach_penalty(score=1.0, rank=rank, pick=pick)


def get_fall_penalty_adjustment(rank: int, pick: int, config: dict) -> dict:
    fall_config = config.get("FALL_PENALTY", {})
    enabled = bool(fall_config.get("enabled", False))
    grace_window = int(fall_config.get("grace_window", 0))
    power = float(fall_config.get("power", 1.0))
    min_multiplier = float(fall_config.get("min_multiplier", 0.35))

    raw_fall_gap = pick - rank
    fall_gap = max(0, raw_fall_gap - grace_window)
    penalty_applied = enabled and fall_gap > 0

    if not penalty_applied:
        fall_penalty_multiplier = 1.0
    else:
        fall_penalty_multiplier = max(
            min_multiplier,
            1.0 / ((1.0 + fall_gap) ** power),
        )

    return {
        "fall_gap_raw": raw_fall_gap,
        "fall_gap": fall_gap,
        "fall_penalty_applied": penalty_applied,
        "fall_penalty_multiplier": fall_penalty_multiplier,
    }


def get_structural_adjustments(
    *,
    team: str,
    position: str,
    rank: int,
    pick: int,
    ot_side: str,
    qb_need_weight: float,
    config: dict,
) -> dict:
    qb_guardrail_multiplier = get_qb_guardrail_multiplier(
        position=position,
        player_rank=rank,
        qb_need_weight=qb_need_weight,
        pick=pick,
        config=config,
    )
    elite_player_multiplier = get_elite_player_multiplier(rank, pick)
    reach_penalty_multiplier = get_reach_penalty_multiplier(rank, pick)
    fall_penalty_adjustment = get_fall_penalty_adjustment(rank, pick, config)
    ot_side_multiplier = get_ot_side_multiplier(team, position, ot_side, config)

    structural_multiplier = (
        qb_guardrail_multiplier
        * elite_player_multiplier
        * reach_penalty_multiplier
        * fall_penalty_adjustment["fall_penalty_multiplier"]
        * ot_side_multiplier
    )

    return {
        "qb_guardrail_multiplier": qb_guardrail_multiplier,
        "elite_player_multiplier": elite_player_multiplier,
        "reach_penalty_multiplier": reach_penalty_multiplier,
        **fall_penalty_adjustment,
        "ot_side_multiplier": ot_side_multiplier,
        "structural_multiplier": structural_multiplier,
    }


def get_market_adjustments(
    *,
    team: str,
    player: str,
    position: str,
    pick: int,
    config: dict,
) -> dict:
    market_player_boost = get_market_player_boost(player, pick, team, config)
    market_team_pos_boost = get_market_team_position_boost(team, position, pick, config)
    market_team_player_boost = get_market_team_player_boost(team, player, pick, config)
    market_multiplier = (
        market_player_boost
        * market_team_pos_boost
        * market_team_player_boost
    )

    return {
        "market_player_boost": market_player_boost,
        "market_team_pos_boost": market_team_pos_boost,
        "market_team_player_boost": market_team_player_boost,
        "market_multiplier": market_multiplier,
    }


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def get_nfl_iq_adjustments(
    *,
    player: str,
    position: str,
    rank: int,
    pick: int,
    nfl_iq_lookup: dict[str, dict],
    config: dict,
) -> dict:
    signal_config = config.get("NFL_IQ_SIGNAL", {})
    signal_row = nfl_iq_lookup.get(player)

    if not signal_config.get("enabled", False) or signal_row is None:
        return {
            "nfl_iq_estimated_pick": None,
            "nfl_iq_rank": None,
            "nfl_iq_position": "",
            "nfl_iq_rd": "",
            "nfl_iq_board_delta": 0.0,
            "nfl_iq_fit_score": 0.0,
            "nfl_iq_multiplier": 1.0,
        }

    estimated_pick = float(signal_row["estimated_pick"])
    nfl_iq_rank = int(signal_row.get("nfl_iq_rank", 0))
    board_delta = float(rank) - estimated_pick

    # Positive delta means NFL IQ is materially more aggressive than our board.
    delta_component = clamp(board_delta / 50.0, -1.0, 1.5)
    board_delta_multiplier = 1.0 + (
        delta_component * float(signal_config.get("board_delta_strength", 0.0))
    )

    pick_fit_width = max(1.0, float(signal_config.get("pick_fit_width", 24.0)))
    fit_score = math.exp(-abs(float(pick) - estimated_pick) / pick_fit_width)
    pick_fit_multiplier = 1.0 + (
        fit_score * float(signal_config.get("pick_fit_strength", 0.0))
    )

    multiplier = board_delta_multiplier * pick_fit_multiplier
    multiplier = clamp(
        multiplier,
        float(signal_config.get("min_multiplier", 0.65)),
        float(signal_config.get("max_multiplier", 2.25)),
    )

    return {
        "nfl_iq_estimated_pick": estimated_pick,
        "nfl_iq_rank": nfl_iq_rank,
        "nfl_iq_position": str(signal_row.get("position", "")),
        "nfl_iq_rd": str(signal_row.get("rd", "")),
        "nfl_iq_board_delta": board_delta,
        "nfl_iq_fit_score": fit_score,
        "nfl_iq_multiplier": multiplier,
    }


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
    df["player"] = df["player"].map(normalize_player_name)
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
    df["player"] = df["player"].map(normalize_player_name)
    df["probability"] = df["probability"].astype(float)

    return df


def load_market_exact_pick_probs(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(
            columns=["pick", "player", "market_prob", "source", "timestamp"]
        )

    df = pd.read_csv(path).copy()
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"pick", "player", "market_prob"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"market_dk_clean missing columns: {missing}")

    df["pick"] = df["pick"].astype(int)
    df["player"] = df["player"].map(normalize_player_name)
    df["market_prob"] = df["market_prob"].astype(float)

    if "source" not in df.columns:
        df["source"] = ""
    else:
        df["source"] = df["source"].fillna("").astype(str).str.strip()

    if "timestamp" not in df.columns:
        df["timestamp"] = ""
    else:
        df["timestamp"] = df["timestamp"].fillna("").astype(str).str.strip()

    return df[["pick", "player", "market_prob", "source", "timestamp"]]


def load_nfl_iq_rankings(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(
            columns=[
                "nfl_iq_rank",
                "rd",
                "position",
                "player",
                "estimated_pick",
                "source",
                "scraped_at",
            ]
        )

    df = pd.read_csv(path).copy()
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"player", "estimated_pick"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"nfl_iq_rankings missing columns: {missing}")

    df["player"] = df["player"].map(normalize_player_name)
    df["estimated_pick"] = pd.to_numeric(df["estimated_pick"], errors="coerce")
    df = df.loc[df["player"].ne("") & df["estimated_pick"].notna()].copy()

    if "nfl_iq_rank" not in df.columns:
        df["nfl_iq_rank"] = range(1, len(df) + 1)
    else:
        df["nfl_iq_rank"] = pd.to_numeric(df["nfl_iq_rank"], errors="coerce").fillna(0).astype(int)

    for column in ["rd", "position", "source", "scraped_at"]:
        if column not in df.columns:
            df[column] = ""
        else:
            df[column] = df[column].fillna("").astype(str).str.strip()

    return df[
        [
            "nfl_iq_rank",
            "rd",
            "position",
            "player",
            "estimated_pick",
            "source",
            "scraped_at",
        ]
    ]


def load_actual_draft_results(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["pick", "team", "player", "position"])

    df = pd.read_csv(path).copy()
    df.columns = [c.strip().lower() for c in df.columns]

    required = {"pick", "team", "player", "position"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"actual_draft_results missing columns: {missing}")

    df["pick"] = df["pick"].astype(int)
    df["team"] = df["team"].astype(str).str.strip().str.upper()
    df["player"] = df["player"].map(normalize_player_name)
    df["position"] = df["position"].map(normalize_position)

    return df[["pick", "team", "player", "position"]]


# =========================
# CORE SCORING
# =========================

def build_nfl_iq_lookup(nfl_iq_df: pd.DataFrame) -> dict[str, dict]:
    if nfl_iq_df.empty:
        return {}

    rows = {}
    ranked_df = nfl_iq_df.sort_values(["estimated_pick", "nfl_iq_rank", "player"])
    for row in ranked_df.itertuples(index=False):
        if row.player in rows:
            continue
        rows[row.player] = {
            "nfl_iq_rank": int(row.nfl_iq_rank),
            "rd": row.rd,
            "position": normalize_position(row.position),
            "estimated_pick": float(row.estimated_pick),
            "source": row.source,
            "scraped_at": row.scraped_at,
        }
    return rows


def build_simulation_context(
    big_board_df: pd.DataFrame,
    overrides_df: pd.DataFrame,
    nfl_iq_df: pd.DataFrame | None = None,
) -> dict:
    sorted_players = []
    player_lookup = {}

    for row in big_board_df.sort_values("rank").itertuples(index=False):
        player_record = {
            "player": row.player,
            "position": row.position,
            "school": row.school,
            "rank": int(row.rank),
            "ot_side": getattr(row, "ot_side", ""),
        }
        sorted_players.append(player_record)
        player_lookup[row.player] = player_record

    qb_sorted_players = [player for player in sorted_players if player["position"] == "QB"]

    override_lookup: dict[tuple[int, str], list[dict]] = {}
    if not overrides_df.empty:
        for row in overrides_df.itertuples(index=False):
            key = (int(row.pick), str(row.team))
            override_lookup.setdefault(key, []).append({
                "pick": int(row.pick),
                "team": str(row.team),
                "player": row.player,
                "probability": float(row.probability),
            })

    return {
        "sorted_players": sorted_players,
        "qb_sorted_players": qb_sorted_players,
        "player_lookup": player_lookup,
        "override_lookup": override_lookup,
        "nfl_iq_lookup": build_nfl_iq_lookup(
            pd.DataFrame() if nfl_iq_df is None else nfl_iq_df
        ),
    }


def get_override_rows(
    pick: int,
    team: str,
    available_players: set[str],
    override_lookup: dict[tuple[int, str], list[dict]],
) -> list[dict]:
    rows = override_lookup.get((pick, team), [])
    if not rows:
        return []

    return [row for row in rows if row["player"] in available_players]


def get_available_candidates(
    pick: int,
    available_players: set[str],
    sorted_players: list[dict],
    qb_sorted_players: list[dict],
    config: dict,
) -> list[dict]:
    pool_size = candidate_pool_size_for_pick(pick, config)
    candidates = []
    candidate_names = set()

    for player in sorted_players:
        if player["player"] not in available_players:
            continue
        candidates.append(player)
        candidate_names.add(player["player"])
        if len(candidates) >= pool_size:
            break

    if pick <= 32:
        qb_extra_n = config["CANDIDATE_POOL"]["qb_extra_round1"]
        qb_added = 0
        for player in qb_sorted_players:
            if player["player"] not in available_players:
                continue
            if player["player"] in candidate_names:
                continue
            candidates.append(player)
            candidate_names.add(player["player"])
            qb_added += 1
            if qb_added >= qb_extra_n:
                break

    return candidates


def score_candidates(
    team: str,
    pick: int,
    available_players: set[str],
    sorted_players: list[dict],
    qb_sorted_players: list[dict],
    need_map: Dict[Tuple[str, str], float],
    nfl_iq_lookup: dict[str, dict],
    config: dict,
) -> List[dict]:
    candidates = get_available_candidates(
        pick=pick,
        available_players=available_players,
        sorted_players=sorted_players,
        qb_sorted_players=qb_sorted_players,
        config=config,
    )

    qb_need_weight = need_map.get((team, "QB"), 0.0)
    default_need_weight = config["DEFAULTS"]["need_weight"]
    need_exp = config["EXPONENTS"]["need"]
    score_exp = config["EXPONENTS"]["score"]

    scored: List[dict] = []

    for row in candidates:
        player = row["player"]
        position = row["position"]
        school = row["school"]
        rank = int(row["rank"])
        ot_side = row.get("ot_side", "")
        candidate_features = extract_candidate_features(
            player=player,
            position=position,
            rank=rank,
            pick=pick,
            ot_side=ot_side,
        )

        need_weight = need_map.get((team, position), default_need_weight)
        board_component = board_score_from_rank(rank, config)
        need_component = max(need_weight, default_need_weight) ** need_exp
        position_value_component = get_position_value_multiplier(position, pick, config)

        base_score = board_component * need_component * position_value_component

        structural_adjustments = get_structural_adjustments(
            team=team,
            position=position,
            rank=rank,
            pick=pick,
            ot_side=ot_side,
            qb_need_weight=qb_need_weight,
            config=config,
        )
        market_adjustments = get_market_adjustments(
            team=team,
            player=player,
            position=position,
            pick=pick,
            config=config,
        )
        nfl_iq_adjustments = get_nfl_iq_adjustments(
            player=player,
            position=position,
            rank=rank,
            pick=pick,
            nfl_iq_lookup=nfl_iq_lookup,
            config=config,
        )

        pre_exponent_score = (
            base_score
            * structural_adjustments["structural_multiplier"]
            * market_adjustments["market_multiplier"]
            * nfl_iq_adjustments["nfl_iq_multiplier"]
        )
        final_score = pre_exponent_score ** score_exp

        scored.append({
            "player": player,
            "position": position,
            "school": school,
            "rank": rank,
            "ot_side": ot_side,
            "need_weight": need_weight,
            "board_component": board_component,
            "need_component": need_component,
            "position_value_component": position_value_component,
            "pos_value_component": position_value_component,
            "base_score": base_score,
            "structural_adjustment_component": structural_adjustments["structural_multiplier"],
            "structural_multiplier": structural_adjustments["structural_multiplier"],
            "market_adjustment_component": market_adjustments["market_multiplier"],
            "market_multiplier": market_adjustments["market_multiplier"],
            "nfl_iq_adjustment_component": nfl_iq_adjustments["nfl_iq_multiplier"],
            "nfl_iq_multiplier": nfl_iq_adjustments["nfl_iq_multiplier"],
            "pre_exponent_score": pre_exponent_score,
            "final_score": final_score,
            "score": final_score,
            **candidate_features,
            **structural_adjustments,
            **market_adjustments,
            **nfl_iq_adjustments,
        })

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
    available_players: set[str],
    need_map: Dict[Tuple[str, str], float],
    override_lookup: dict[tuple[int, str], list[dict]],
    sorted_players: list[dict],
    qb_sorted_players: list[dict],
    player_lookup: dict[str, dict],
    nfl_iq_lookup: dict[str, dict],
    config: dict,
    rng: random.Random,
) -> Tuple[dict, List[dict]]:
    # 1. player overrides
    override_rows = get_override_rows(
        pick=pick,
        team=team,
        available_players=available_players,
        override_lookup=override_lookup,
    )

    if override_rows:
        rows = []
        total = sum(row["probability"] for row in override_rows)

        if total <= 0:
            normalized_override_rows = [
                {**row, "probability": 1.0 / len(override_rows)}
                for row in override_rows
            ]
        else:
            normalized_override_rows = [
                {**row, "probability": row["probability"] / total}
                for row in override_rows
            ]

        for row in normalized_override_rows:
            player_row = player_lookup[row["player"]]
            rows.append({
                "player": player_row["player"],
                "position": player_row["position"],
                "school": player_row["school"],
                "rank": int(player_row["rank"]),
                "probability": float(row["probability"]),
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
        available_players=available_players,
        sorted_players=sorted_players,
        qb_sorted_players=qb_sorted_players,
        need_map=need_map,
        nfl_iq_lookup=nfl_iq_lookup,
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
    need_map: Dict[Tuple[str, str], float],
    sim_context: dict,
    config: dict,
    rng: random.Random,
    sim_id: int | None = None,
) -> pd.DataFrame:

    sim_need_map = dict(need_map)

    available_players = set(sim_context["player_lookup"])
    picks = []

    for row in draft_order_df.itertuples(index=False):
        result, _ = make_pick(
            team=row.team,
            pick=int(row.pick),
            round_num=1,
            available_players=available_players,
            need_map=sim_need_map,
            override_lookup=sim_context["override_lookup"],
            sorted_players=sim_context["sorted_players"],
            qb_sorted_players=sim_context["qb_sorted_players"],
            player_lookup=sim_context["player_lookup"],
            nfl_iq_lookup=sim_context["nfl_iq_lookup"],
            config=config,
            rng=rng,
        )

        if sim_id is not None:
            result["sim_id"] = sim_id

        picks.append(result)
        available_players.remove(result["player"])

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
    sim_context: dict | None = None,
) -> pd.DataFrame:
    rng = random.Random(seed)
    if sim_context is None:
        sim_context = build_simulation_context(big_board_df, overrides_df)
    all_results = []

    for sim_id in range(1, n_sims + 1):
        mock_df = run_single_mock(
            draft_order_df=draft_order_df,
            need_map=need_map,
            sim_context=sim_context,
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


def build_exact_pick_probs(results_df: pd.DataFrame, model_version: str) -> pd.DataFrame:
    n_sims = results_df["sim_id"].nunique()
    out = (
        results_df.groupby(["pick", "team", "player"], as_index=False)
        .size()
        .rename(columns={"size": "count"})
    )
    out["probability"] = out["count"] / n_sims
    out["config_version"] = model_version
    return out[["pick", "team", "player", "probability", "config_version"]].sort_values(
        ["pick", "probability", "team", "player"],
        ascending=[True, False, True, True],
    )


def build_team_player_probs(results_df: pd.DataFrame, model_version: str) -> pd.DataFrame:
    n_sims = results_df["sim_id"].nunique()
    out = (
        results_df.groupby(["team", "player"], as_index=False)
        .size()
        .rename(columns={"size": "count"})
    )
    out["probability"] = out["count"] / n_sims
    out["config_version"] = model_version
    return out[["team", "player", "probability", "config_version"]].sort_values(
        ["team", "probability", "player"],
        ascending=[True, False, True],
    )


def build_model_vs_market_exact_pick(
    exact_pick_probs_df: pd.DataFrame,
    market_df: pd.DataFrame,
    *,
    model_version: str,
    run_timestamp: datetime,
) -> tuple[pd.DataFrame, dict]:
    model_df = exact_pick_probs_df[["pick", "player", "probability"]].rename(
        columns={"probability": "model_prob"}
    )
    market_compare_df = market_df[["pick", "player", "market_prob", "source", "timestamp"]].rename(
        columns={"timestamp": "market_timestamp"}
    )

    merged_df = model_df.merge(
        market_compare_df,
        on=["pick", "player"],
        how="outer",
        indicator=True,
    )

    merged_df["model_prob"] = merged_df["model_prob"].fillna(0.0)
    merged_df["market_prob"] = merged_df["market_prob"].fillna(0.0)
    merged_df["source"] = merged_df["source"].fillna("")
    merged_df["market_timestamp"] = merged_df["market_timestamp"].fillna("")
    merged_df["edge"] = merged_df["model_prob"] - merged_df["market_prob"]
    merged_df["abs_edge"] = merged_df["edge"].abs()
    merged_df["model_version"] = model_version
    merged_df["run_timestamp"] = run_timestamp.isoformat(timespec="seconds")

    compare_df = merged_df[
        [
            "pick",
            "player",
            "model_prob",
            "market_prob",
            "edge",
            "abs_edge",
            "model_version",
            "run_timestamp",
            "source",
            "market_timestamp",
        ]
    ].sort_values(
        ["abs_edge", "pick", "player"],
        ascending=[False, True, True],
    ).reset_index(drop=True)

    stats = {
        "matched_rows": int((merged_df["_merge"] == "both").sum()),
        "unmatched_model_rows_count": int((merged_df["_merge"] == "left_only").sum()),
        "unmatched_market_rows_count": int((merged_df["_merge"] == "right_only").sum()),
    }
    return compare_df, stats


def build_model_vs_market_summary(
    *,
    model_version: str,
    run_dir: Path,
    run_timestamp: datetime,
    market_file_used: Path,
    compare_df: pd.DataFrame,
    compare_stats: dict,
) -> dict:
    return {
        "model_version": model_version,
        "run_dir": str(run_dir),
        "timestamp": run_timestamp.isoformat(timespec="seconds"),
        "market_file_used": str(market_file_used),
        "matched_rows": compare_stats["matched_rows"],
        "unmatched_model_rows_count": compare_stats["unmatched_model_rows_count"],
        "unmatched_market_rows_count": compare_stats["unmatched_market_rows_count"],
        "top_20_edges": compare_df.head(20).to_dict(orient="records"),
    }


def print_model_vs_market_console_summary(
    market_found: bool,
    compare_df: pd.DataFrame | None = None,
    compare_stats: dict | None = None,
) -> None:
    if not market_found:
        print(f"\nMarket file not found: {MARKET_CLEAN_PATH}")
        return

    print(f"\nMarket file found: {MARKET_CLEAN_PATH}")

    if compare_stats is not None:
        print(f"Matched rows: {compare_stats['matched_rows']}")

    if compare_df is not None and not compare_df.empty:
        print("\nTop 10 biggest model vs market edges:")
        print(compare_df.head(10).to_string(index=False))


def build_model_vs_actual_exact_pick(
    exact_pick_probs_df: pd.DataFrame,
    actual_df: pd.DataFrame,
    *,
    model_version: str,
    run_timestamp: datetime,
) -> tuple[pd.DataFrame, dict]:
    model_df = exact_pick_probs_df.rename(columns={"team": "team_model", "probability": "model_prob"}).copy()
    actual_compare_df = actual_df.rename(columns={"team": "team_actual"}).copy()
    actual_compare_df["actual_outcome"] = 1
    actual_compare_df["hit"] = 1

    compare_df = model_df.merge(
        actual_compare_df[["pick", "player", "team_actual", "actual_outcome", "hit"]],
        on=["pick", "player"],
        how="left",
    )
    compare_df["team_actual"] = compare_df["team_actual"].fillna("")
    compare_df["actual_outcome"] = compare_df["actual_outcome"].fillna(0).astype(int)
    compare_df["hit"] = compare_df["hit"].fillna(0).astype(int)
    compare_df["model_version"] = model_version
    compare_df["run_timestamp"] = run_timestamp.isoformat(timespec="seconds")
    compare_df["brier_component"] = (compare_df["model_prob"] - compare_df["actual_outcome"]) ** 2

    compare_df = compare_df[
        [
            "pick",
            "team_model",
            "team_actual",
            "player",
            "model_prob",
            "actual_outcome",
            "hit",
            "model_version",
            "run_timestamp",
            "brier_component",
        ]
    ].sort_values(["pick", "model_prob", "player"], ascending=[True, False, True]).reset_index(drop=True)

    actual_hits_df = compare_df[compare_df["actual_outcome"] == 1].copy()
    summary_stats = {
        "number_of_actual_picks": int(len(actual_df)),
        "matched_exact_pick_rows": int(compare_df["hit"].sum()),
        "average_model_prob_on_actual_picks": float(actual_hits_df["model_prob"].mean()) if not actual_hits_df.empty else None,
        "brier_score": float(compare_df["brier_component"].mean()) if not compare_df.empty else None,
    }
    return compare_df, summary_stats


def assign_calibration_bucket(probability: float) -> str:
    if probability < 0.01:
        return "0.00-0.01"
    if probability < 0.02:
        return "0.01-0.02"
    if probability < 0.05:
        return "0.02-0.05"
    if probability < 0.10:
        return "0.05-0.10"
    return "0.10+"


def build_calibration_exact_pick(model_vs_actual_df: pd.DataFrame) -> pd.DataFrame:
    calibration_df = model_vs_actual_df.copy()
    calibration_df["bucket"] = calibration_df["model_prob"].apply(assign_calibration_bucket)

    out = (
        calibration_df.groupby("bucket", as_index=False)
        .agg(
            count=("player", "size"),
            avg_model_prob=("model_prob", "mean"),
            actual_hit_rate=("actual_outcome", "mean"),
            avg_brier_component=("brier_component", "mean"),
        )
    )

    bucket_order = ["0.00-0.01", "0.01-0.02", "0.02-0.05", "0.05-0.10", "0.10+"]
    out["bucket"] = pd.Categorical(out["bucket"], categories=bucket_order, ordered=True)
    return out.sort_values("bucket").reset_index(drop=True)


def build_model_vs_actual_summary(
    *,
    model_version: str,
    run_dir: Path,
    run_timestamp: datetime,
    actual_results_file_used: Path,
    model_vs_actual_df: pd.DataFrame,
    summary_stats: dict,
) -> dict:
    hits_df = model_vs_actual_df[model_vs_actual_df["hit"] == 1].copy()
    misses_df = model_vs_actual_df[model_vs_actual_df["actual_outcome"] == 0].copy()

    return {
        "model_version": model_version,
        "run_dir": str(run_dir),
        "timestamp": run_timestamp.isoformat(timespec="seconds"),
        "actual_results_file_used": str(actual_results_file_used),
        "number_of_actual_picks": summary_stats["number_of_actual_picks"],
        "matched_exact_pick_rows": summary_stats["matched_exact_pick_rows"],
        "average_model_prob_on_actual_picks": summary_stats["average_model_prob_on_actual_picks"],
        "brier_score": summary_stats["brier_score"],
        "top_20_highest_model_probs_that_hit": hits_df.sort_values("model_prob", ascending=False).head(20).to_dict(orient="records"),
        "top_20_highest_model_probs_that_missed": misses_df.sort_values("model_prob", ascending=False).head(20).to_dict(orient="records"),
    }


def build_edge_vs_actual_exact_pick(
    model_vs_market_df: pd.DataFrame,
    actual_df: pd.DataFrame,
) -> pd.DataFrame:
    actual_flags_df = actual_df[["pick", "player"]].copy()
    actual_flags_df["actual_outcome"] = 1

    out = model_vs_market_df.merge(actual_flags_df, on=["pick", "player"], how="left")
    out["actual_outcome"] = out["actual_outcome"].fillna(0).astype(int)
    return out[
        ["pick", "player", "model_prob", "market_prob", "edge", "abs_edge", "actual_outcome"]
    ].sort_values(["abs_edge", "pick", "player"], ascending=[False, True, True]).reset_index(drop=True)


def print_model_vs_actual_console_summary(
    outcomes_found: bool,
    model_vs_actual_df: pd.DataFrame | None = None,
    summary_stats: dict | None = None,
) -> None:
    if not outcomes_found:
        print(f"\nActual outcomes file not found: {ACTUAL_DRAFT_RESULTS_PATH}")
        return

    print(f"\nActual outcomes file found: {ACTUAL_DRAFT_RESULTS_PATH}")

    if summary_stats is not None:
        print(f"Matched exact-pick rows: {summary_stats['matched_exact_pick_rows']}")
        print(f"Brier score: {summary_stats['brier_score']}")

    if model_vs_actual_df is not None and not model_vs_actual_df.empty:
        print("\nTop 10 highest model probabilities that hit:")
        print(
            model_vs_actual_df[model_vs_actual_df["hit"] == 1]
            .sort_values("model_prob", ascending=False)
            .head(10)
            .to_string(index=False)
        )


def build_run_summary(
    *,
    config: dict,
    run_timestamp: datetime,
    run_dir: Path,
    results_df: pd.DataFrame,
    exact_pick_probs_df: pd.DataFrame,
    adp_df: pd.DataFrame,
) -> dict:
    top_exact_pick_outcomes = (
        exact_pick_probs_df.sort_values("probability", ascending=False)
        .head(10)
        .to_dict(orient="records")
    )
    top_adp_players = adp_df.head(10).to_dict(orient="records")

    return {
        "model_version": get_model_version(config),
        "timestamp": run_timestamp.isoformat(timespec="seconds"),
        "n_sims": config["SIM"]["n_sims"],
        "random_seed": config["SIM"]["random_seed"],
        "run_dir": str(run_dir),
        "input_file_paths": {
            "big_board": str(BIG_BOARD_PATH),
            "team_needs": str(TEAM_NEEDS_PATH),
            "draft_order": str(DRAFT_ORDER_PATH),
            "player_overrides": str(PLAYER_OVERRIDES_PATH),
        },
        "config_path": str(run_dir / "config.json"),
        "number_of_picks_simulated": int(len(results_df)),
        "number_of_unique_players_drafted": int(results_df["player"].nunique()),
        "number_of_unique_teams": int(results_df["team"].nunique()),
        "top_10_players_by_average_draft_position": top_adp_players,
        "top_10_most_common_exact_pick_outcomes": top_exact_pick_outcomes,
    }


def get_run_sort_key(run_dir: Path) -> str:
    return run_dir.name


def get_run_model_version(run_dir: Path) -> str | None:
    metadata_path = run_dir / "metadata.json"
    if metadata_path.exists():
        try:
            metadata = read_json(metadata_path)
            return metadata.get("model_version")
        except (OSError, json.JSONDecodeError):
            return None

    config_path = run_dir / "config.json"
    if config_path.exists():
        try:
            config = read_json(config_path)
            return config.get("MODEL_VERSION")
        except (OSError, json.JSONDecodeError):
            return None

    return None


def find_previous_run_dir(current_run_dir: Path, model_version: str) -> Path | None:
    run_dirs = [
        path for path in RUNS_DIR.iterdir()
        if path.is_dir() and path != current_run_dir and get_run_sort_key(path) < get_run_sort_key(current_run_dir)
    ]

    if not run_dirs:
        return None

    run_dirs = sorted(run_dirs, key=get_run_sort_key, reverse=True)
    same_version_runs = [path for path in run_dirs if get_run_model_version(path) == model_version]

    if same_version_runs:
        return same_version_runs[0]

    return run_dirs[0]


def load_probability_table(path: Path, required_columns: list[str]) -> pd.DataFrame | None:
    if not path.exists():
        return None

    df = pd.read_csv(path).copy()
    missing = [column for column in required_columns if column not in df.columns]
    if missing:
        return None

    return df


def build_probability_diff(
    current_df: pd.DataFrame,
    previous_df: pd.DataFrame,
    *,
    keys: list[str],
    current_run: str,
    previous_run: str,
) -> pd.DataFrame:
    previous = previous_df[keys + ["probability"]].rename(columns={"probability": "previous_probability"})
    current = current_df[keys + ["probability"]].rename(columns={"probability": "current_probability"})

    diff_df = previous.merge(current, on=keys, how="outer")
    diff_df["previous_probability"] = diff_df["previous_probability"].fillna(0.0)
    diff_df["current_probability"] = diff_df["current_probability"].fillna(0.0)
    diff_df["diff"] = diff_df["current_probability"] - diff_df["previous_probability"]
    diff_df["abs_diff"] = diff_df["diff"].abs()
    diff_df["previous_run"] = previous_run
    diff_df["current_run"] = current_run

    return diff_df.sort_values(["abs_diff"] + keys, ascending=[False] + [True] * len(keys)).reset_index(drop=True)


def build_adp_diff(current_adp_path: Path, previous_adp_path: Path) -> list[dict]:
    if not current_adp_path.exists() or not previous_adp_path.exists():
        return []

    current_df = pd.read_csv(current_adp_path).copy()
    previous_df = pd.read_csv(previous_adp_path).copy()

    required = {"player", "avg_pick"}
    if not required.issubset(current_df.columns) or not required.issubset(previous_df.columns):
        return []

    diff_df = previous_df[["player", "avg_pick"]].rename(columns={"avg_pick": "previous_avg_pick"}).merge(
        current_df[["player", "avg_pick"]].rename(columns={"avg_pick": "current_avg_pick"}),
        on="player",
        how="outer",
    )
    diff_df["previous_avg_pick"] = diff_df["previous_avg_pick"].fillna(0.0)
    diff_df["current_avg_pick"] = diff_df["current_avg_pick"].fillna(0.0)
    diff_df["diff"] = diff_df["current_avg_pick"] - diff_df["previous_avg_pick"]
    diff_df["abs_diff"] = diff_df["diff"].abs()

    return diff_df.sort_values("abs_diff", ascending=False).head(20).to_dict(orient="records")


def build_diff_summary(
    *,
    current_run_dir: Path,
    previous_run_dir: Path,
    model_version: str,
    diff_exact_pick_df: pd.DataFrame,
    diff_team_player_df: pd.DataFrame,
    current_adp_path: Path,
    previous_adp_path: Path,
) -> dict:
    pick_reshuffling = (
        diff_exact_pick_df.groupby("pick", as_index=False)["abs_diff"]
        .sum()
        .rename(columns={"abs_diff": "total_abs_diff"})
        .sort_values("total_abs_diff", ascending=False)
        .head(20)
    )

    return {
        "previous_run_dir": str(previous_run_dir),
        "current_run_dir": str(current_run_dir),
        "model_version": model_version,
        "largest_exact_pick_changes": diff_exact_pick_df.head(20).to_dict(orient="records"),
        "largest_team_player_changes": diff_team_player_df.head(20).to_dict(orient="records"),
        "largest_adp_changes": build_adp_diff(current_adp_path, previous_adp_path),
        "picks_with_biggest_total_probability_reshuffling": pick_reshuffling.to_dict(orient="records"),
    }


def print_diff_console_summary(
    previous_run_dir: Path | None,
    diff_exact_pick_df: pd.DataFrame | None = None,
    diff_team_player_df: pd.DataFrame | None = None,
) -> None:
    if previous_run_dir is None:
        print("\nNo previous run found. Skipping diff outputs.")
        return

    print(f"\nPrevious run found: {previous_run_dir}")

    if diff_exact_pick_df is not None and not diff_exact_pick_df.empty:
        print("\nBiggest exact-pick changes:")
        print(diff_exact_pick_df.head(5).to_string(index=False))

    if diff_team_player_df is not None and not diff_team_player_df.empty:
        print("\nBiggest team-player changes:")
        print(diff_team_player_df.head(5).to_string(index=False))


def build_experiment_summary_row(
    *,
    experiment_name: str,
    config: dict,
    run_dir: Path,
    model_vs_market_df: pd.DataFrame | None,
    model_vs_actual_stats: dict | None,
) -> dict:
    if model_vs_market_df is None or model_vs_market_df.empty:
        mean_abs_edge = None
        median_abs_edge = None
        max_abs_edge = None
    else:
        mean_abs_edge = float(model_vs_market_df["abs_edge"].mean())
        median_abs_edge = float(model_vs_market_df["abs_edge"].median())
        max_abs_edge = float(model_vs_market_df["abs_edge"].max())

    fall_penalty = config.get("FALL_PENALTY", {})

    return {
        "experiment_name": experiment_name,
        "model_version": get_model_version(config),
        "board_exp": config["EXPONENTS"]["board"],
        "need_exp": config["EXPONENTS"]["need"],
        "score_exp": config["EXPONENTS"]["score"],
        "fall_penalty_enabled": fall_penalty.get("enabled"),
        "fall_penalty_grace_window": fall_penalty.get("grace_window"),
        "fall_penalty_power": fall_penalty.get("power"),
        "fall_penalty_min_multiplier": fall_penalty.get("min_multiplier"),
        "matched_exact_pick_rows": None if model_vs_actual_stats is None else model_vs_actual_stats.get("matched_exact_pick_rows"),
        "mean_abs_edge": mean_abs_edge,
        "median_abs_edge": median_abs_edge,
        "max_abs_edge": max_abs_edge,
        "brier_score": None if model_vs_actual_stats is None else model_vs_actual_stats.get("brier_score"),
        "run_dir": str(run_dir),
    }


def write_experiment_outputs(experiment_rows: list[dict], batch_timestamp: datetime) -> None:
    if not experiment_rows:
        return

    summary_df = pd.DataFrame(experiment_rows)
    ranking_df = summary_df.sort_values(
        ["mean_abs_edge", "brier_score", "experiment_name"],
        ascending=[True, True, True],
        na_position="last",
    ).reset_index(drop=True)

    batch_name = batch_timestamp.strftime("%Y-%m-%d_%H%M%S")
    summary_path = EXPERIMENTS_DIR / f"{batch_name}_experiment_summary.csv"
    ranking_path = EXPERIMENTS_DIR / f"{batch_name}_experiment_ranking.csv"

    summary_df.to_csv(summary_path, index=False)
    ranking_df.to_csv(ranking_path, index=False)

    print(f"\nWrote {summary_path}")
    print(f"Wrote {ranking_path}")


# =========================
# MAIN
# =========================

def run_configured_simulation(config: dict, experiment_name: str | None = None) -> dict:
    model_version = get_model_version(config)
    run_timestamp = datetime.now()
    run_paths = build_run_paths(model_version, run_timestamp)
    run_paths["run_dir"].mkdir(parents=True, exist_ok=False)

    write_json(run_paths["model_config"], config)
    write_json(run_paths["run_config"], config)
    write_json(
        run_paths["metadata"],
        build_run_metadata(
            model_version=model_version,
            timestamp=run_timestamp,
            config=config,
        ),
    )

    print("Loading data...")
    print("Running with config:")
    print(config)
    if experiment_name:
        print(f"Experiment: {experiment_name}")

    big_board_df = load_big_board(BIG_BOARD_PATH)
    need_map = load_team_needs(TEAM_NEEDS_PATH)
    draft_order_df = load_draft_order(DRAFT_ORDER_PATH)
    overrides_df = load_player_overrides(PLAYER_OVERRIDES_PATH)
    nfl_iq_df = load_nfl_iq_rankings(NFL_IQ_CLEAN_PATH)
    if nfl_iq_df.empty:
        print(f"No NFL IQ rankings file found at {NFL_IQ_CLEAN_PATH}. Continuing without NFL IQ signal.")
    else:
        print(f"Loaded {len(nfl_iq_df)} NFL IQ ranking rows from {NFL_IQ_CLEAN_PATH}.")
    sim_context = build_simulation_context(big_board_df, overrides_df, nfl_iq_df)

    print("\nRunning one mock draft preview...")
    preview_rng = random.Random(config["SIM"]["random_seed"])
    preview_df = run_single_mock(
        draft_order_df=draft_order_df,
        need_map=need_map,
        sim_context=sim_context,
        config=config,
        rng=preview_rng,
    )
    print(preview_df.head(20).to_string(index=False))

    preview_path = run_paths["preview"]
    preview_df.to_csv(preview_path, index=False)
    print(f"\nWrote {preview_path}")

    print(f"\nRunning {config['SIM']['n_sims']} simulations...")
    results_df = run_simulations(
        n_sims=config["SIM"]["n_sims"],
        draft_order_df=draft_order_df,
        big_board_df=big_board_df,
        need_map=need_map,
        overrides_df=overrides_df,
        config=config,
        seed=config["SIM"]["random_seed"],
        sim_context=sim_context,
    )

    simulated_picks_path = run_paths["simulated_picks"]
    results_df.to_csv(simulated_picks_path, index=False)
    print(f"Wrote {simulated_picks_path}")

    player_by_pick_ml_df = summarize_player_by_pick_moneyline(results_df)
    player_by_pick_ml_path = run_paths["player_by_pick_moneyline"]
    player_by_pick_ml_df.to_csv(player_by_pick_ml_path, index=False)
    print(f"Wrote {player_by_pick_ml_path}")

    player_ou_df = summarize_player_ou_lines(results_df)
    player_ou_path = run_paths["player_ou_lines"]
    player_ou_df.to_csv(player_ou_path, index=False)
    print(f"Wrote {player_ou_path}")

    player_by_pick_df = summarize_player_by_pick(results_df)
    player_by_team_df = summarize_player_by_team(results_df)
    position_by_team_df = summarize_position_by_team(results_df)
    adp_df = summarize_adp(results_df)
    exact_pick_probs_df = build_exact_pick_probs(results_df, model_version)
    team_player_probs_df = build_team_player_probs(results_df, model_version)

    pick_depth_df = summarize_pick_depth(player_by_pick_df)
    pick_depth_path = run_paths["pick_depth_summary"]
    pick_depth_df.to_csv(pick_depth_path, index=False)
    print(f"Wrote {pick_depth_path}")

    position_by_team_ml_df = summarize_position_by_team_moneyline(results_df)
    position_by_team_ml_path = run_paths["position_by_team_moneyline"]
    position_by_team_ml_df.to_csv(position_by_team_ml_path, index=False)
    print(f"Wrote {position_by_team_ml_path}")

    player_by_team_ml_df = summarize_player_by_team_moneyline(results_df)
    player_by_team_ml_path = run_paths["player_by_team_moneyline"]
    player_by_team_ml_df.to_csv(player_by_team_ml_path, index=False)
    print(f"Wrote {player_by_team_ml_path}")

    position_totals_df = summarize_position_totals(results_df)
    position_totals_path = run_paths["position_totals"]
    position_totals_df.to_csv(position_totals_path, index=False)
    print(f"Wrote {position_totals_path}")

    position_total_ou_df = summarize_position_total_ou_lines(results_df)
    position_total_ou_path = run_paths["position_total_ou_lines"]
    position_total_ou_df.to_csv(position_total_ou_path, index=False)
    print(f"Wrote {position_total_ou_path}")

    player_by_pick_path = run_paths["player_by_pick_probs"]
    player_by_team_path = run_paths["player_by_team_probs"]
    position_by_team_path = run_paths["position_by_team_probs"]
    adp_path = run_paths["player_adp"]
    exact_pick_probs_path = run_paths["exact_pick_probs"]
    team_player_probs_path = run_paths["team_player_probs"]

    player_by_pick_df.to_csv(player_by_pick_path, index=False)
    player_by_team_df.to_csv(player_by_team_path, index=False)
    position_by_team_df.to_csv(position_by_team_path, index=False)
    adp_df.to_csv(adp_path, index=False)
    exact_pick_probs_df.to_csv(exact_pick_probs_path, index=False)
    team_player_probs_df.to_csv(team_player_probs_path, index=False)

    print(f"Wrote {player_by_pick_path}")
    print(f"Wrote {player_by_team_path}")
    print(f"Wrote {position_by_team_path}")
    print(f"Wrote {adp_path}")
    print(f"Wrote {exact_pick_probs_path}")
    print(f"Wrote {team_player_probs_path}")

    market_df = load_market_exact_pick_probs(MARKET_CLEAN_PATH)
    model_vs_market_df = None
    model_vs_actual_stats = None
    if market_df.empty and not MARKET_CLEAN_PATH.exists():
        print_model_vs_market_console_summary(market_found=False)
    else:
        model_vs_market_df, model_vs_market_stats = build_model_vs_market_exact_pick(
            exact_pick_probs_df,
            market_df,
            model_version=model_version,
            run_timestamp=run_timestamp,
        )
        model_vs_market_path = run_paths["model_vs_market_exact_pick"]
        model_vs_market_summary_path = run_paths["model_vs_market_summary"]

        model_vs_market_df.to_csv(model_vs_market_path, index=False)
        write_json(
            model_vs_market_summary_path,
            build_model_vs_market_summary(
                model_version=model_version,
                run_dir=run_paths["run_dir"],
                run_timestamp=run_timestamp,
                market_file_used=MARKET_CLEAN_PATH,
                compare_df=model_vs_market_df,
                compare_stats=model_vs_market_stats,
            ),
        )

        print(f"Wrote {model_vs_market_path}")
        print(f"Wrote {model_vs_market_summary_path}")
        print_model_vs_market_console_summary(
            market_found=True,
            compare_df=model_vs_market_df,
            compare_stats=model_vs_market_stats,
        )

    actual_df = load_actual_draft_results(ACTUAL_DRAFT_RESULTS_PATH)
    if actual_df.empty and not ACTUAL_DRAFT_RESULTS_PATH.exists():
        print_model_vs_actual_console_summary(outcomes_found=False)
    else:
        model_vs_actual_df, model_vs_actual_stats = build_model_vs_actual_exact_pick(
            exact_pick_probs_df,
            actual_df,
            model_version=model_version,
            run_timestamp=run_timestamp,
        )
        calibration_exact_pick_df = build_calibration_exact_pick(model_vs_actual_df)

        model_vs_actual_path = run_paths["model_vs_actual_exact_pick"]
        model_vs_actual_summary_path = run_paths["model_vs_actual_summary"]
        calibration_exact_pick_path = run_paths["calibration_exact_pick"]

        model_vs_actual_df.to_csv(model_vs_actual_path, index=False)
        calibration_exact_pick_df.to_csv(calibration_exact_pick_path, index=False)
        write_json(
            model_vs_actual_summary_path,
            build_model_vs_actual_summary(
                model_version=model_version,
                run_dir=run_paths["run_dir"],
                run_timestamp=run_timestamp,
                actual_results_file_used=ACTUAL_DRAFT_RESULTS_PATH,
                model_vs_actual_df=model_vs_actual_df,
                summary_stats=model_vs_actual_stats,
            ),
        )

        print(f"Wrote {model_vs_actual_path}")
        print(f"Wrote {calibration_exact_pick_path}")
        print(f"Wrote {model_vs_actual_summary_path}")
        print_model_vs_actual_console_summary(
            outcomes_found=True,
            model_vs_actual_df=model_vs_actual_df,
            summary_stats=model_vs_actual_stats,
        )

        if model_vs_market_df is not None and not model_vs_market_df.empty:
            edge_vs_actual_df = build_edge_vs_actual_exact_pick(model_vs_market_df, actual_df)
            edge_vs_actual_path = run_paths["edge_vs_actual_exact_pick"]
            edge_vs_actual_df.to_csv(edge_vs_actual_path, index=False)
            print(f"Wrote {edge_vs_actual_path}")

    run_summary = build_run_summary(
        config=config,
        run_timestamp=run_timestamp,
        run_dir=run_paths["run_dir"],
        results_df=results_df,
        exact_pick_probs_df=exact_pick_probs_df,
        adp_df=adp_df,
    )
    write_json(run_paths["run_summary"], run_summary)
    print(f"Wrote {run_paths['model_config']}")
    print(f"Wrote {run_paths['run_config']}")
    print(f"Wrote {run_paths['metadata']}")
    print(f"Wrote {run_paths['run_summary']}")

    previous_run_dir = find_previous_run_dir(run_paths["run_dir"], model_version)
    if previous_run_dir is not None:
        previous_exact_pick_df = load_probability_table(
            previous_run_dir / "exact_pick_probs.csv",
            ["pick", "team", "player", "probability"],
        )
        previous_team_player_df = load_probability_table(
            previous_run_dir / "team_player_probs.csv",
            ["team", "player", "probability"],
        )

        if previous_exact_pick_df is not None and previous_team_player_df is not None:
            diff_exact_pick_df = build_probability_diff(
                exact_pick_probs_df,
                previous_exact_pick_df,
                keys=["pick", "team", "player"],
                current_run=run_paths["run_dir"].name,
                previous_run=previous_run_dir.name,
            )
            diff_team_player_df = build_probability_diff(
                team_player_probs_df,
                previous_team_player_df,
                keys=["team", "player"],
                current_run=run_paths["run_dir"].name,
                previous_run=previous_run_dir.name,
            )

            diff_exact_pick_df.to_csv(run_paths["diff_exact_pick_probs"], index=False)
            diff_team_player_df.to_csv(run_paths["diff_team_player_probs"], index=False)
            write_json(
                run_paths["diff_summary"],
                build_diff_summary(
                    current_run_dir=run_paths["run_dir"],
                    previous_run_dir=previous_run_dir,
                    model_version=model_version,
                    diff_exact_pick_df=diff_exact_pick_df,
                    diff_team_player_df=diff_team_player_df,
                    current_adp_path=adp_path,
                    previous_adp_path=previous_run_dir / "player_adp.csv",
                ),
            )

            print(f"Wrote {run_paths['diff_exact_pick_probs']}")
            print(f"Wrote {run_paths['diff_team_player_probs']}")
            print(f"Wrote {run_paths['diff_summary']}")
            print_diff_console_summary(previous_run_dir, diff_exact_pick_df, diff_team_player_df)
        else:
            print("\nPrevious run found, but comparison files were missing or invalid. Skipping diff outputs.")
    else:
        print_diff_console_summary(previous_run_dir)

    return {
        "experiment_name": experiment_name or "default",
        "config": config,
        "run_dir": run_paths["run_dir"],
        "model_vs_market_df": model_vs_market_df,
        "model_vs_actual_stats": model_vs_actual_stats,
    }


def main() -> None:
    if RUN_EXPERIMENTS and EXPERIMENTS:
        batch_timestamp = datetime.now()
        experiment_rows = []

        for experiment in EXPERIMENTS:
            experiment_name = experiment["experiment_name"]
            overrides = experiment.get("overrides", {})
            experiment_config = build_experiment_config(CONFIG, overrides, experiment_name)
            result = run_configured_simulation(experiment_config, experiment_name=experiment_name)
            experiment_rows.append(
                build_experiment_summary_row(
                    experiment_name=experiment_name,
                    config=experiment_config,
                    run_dir=result["run_dir"],
                    model_vs_market_df=result["model_vs_market_df"],
                    model_vs_actual_stats=result["model_vs_actual_stats"],
                )
            )

        write_experiment_outputs(experiment_rows, batch_timestamp)
        return

    run_configured_simulation(CONFIG)


if __name__ == "__main__":
    main()
