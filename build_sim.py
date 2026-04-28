from __future__ import annotations

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
DATA_DIR = Path(r"C:\Users\brady\OneDrive\Desktop\nfl_tools\draft\data")
OUTPUT_DIR = BASE_DIR / "output"
MODELS_DIR = BASE_DIR / "models"
RUNS_DIR = OUTPUT_DIR / "runs"

BIG_BOARD_PATH = DATA_DIR / "consensus_big_board.csv"
TEAM_NEEDS_PATH = DATA_DIR / "team_needs.csv"
DRAFT_ORDER_PATH = DATA_DIR / "draft_order.csv"
PLAYER_OVERRIDES_PATH = DATA_DIR / "player_overrides.csv"

OUTPUT_DIR.mkdir(exist_ok=True)
MODELS_DIR.mkdir(exist_ok=True)
RUNS_DIR.mkdir(parents=True, exist_ok=True)


# =========================
# CONFIG
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
        "S": 0.97,
        "LB": 0.95,
        "IOL": 0.90,
        "TE": 0.88,
        "RB": 0.85,
    },
    "MARKET_PLAYER_BOOSTS": {
        # temporary manual boosts
        "Jeremiyah Love": 1.5,
    },
    "MARKET_TEAM_POSITION_BOOSTS": {
        # examples if you want them later
        # ("TEN", "RB"): 1.10,
    },
    "BOARD_EXPONENT": 0.70,
    "NEED_EXPONENT": 1.25,
    "DEFAULT_NEED_WEIGHT": 0.05,
    "DEFAULT_POSITION_VALUE": 1.00,
    "N_SIMS": 5000,
    "RANDOM_SEED": 42,
}

MODEL_VERSION = CONFIG["MODEL_VERSION"]
POSITION_VALUE = CONFIG["POSITION_VALUE"]
MARKET_PLAYER_BOOSTS = CONFIG["MARKET_PLAYER_BOOSTS"]
MARKET_TEAM_POSITION_BOOSTS = CONFIG["MARKET_TEAM_POSITION_BOOSTS"]
BOARD_EXPONENT = CONFIG["BOARD_EXPONENT"]
NEED_EXPONENT = CONFIG["NEED_EXPONENT"]
DEFAULT_NEED_WEIGHT = CONFIG["DEFAULT_NEED_WEIGHT"]
DEFAULT_POSITION_VALUE = CONFIG["DEFAULT_POSITION_VALUE"]
N_SIMS = CONFIG["N_SIMS"]
RANDOM_SEED = CONFIG["RANDOM_SEED"]


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

def get_market_player_boost(player: str, pick: int, team: str) -> float:
    return MARKET_PLAYER_BOOSTS.get(player, 1.0)


def get_market_team_position_boost(team: str, position: str, pick: int) -> float:
    return MARKET_TEAM_POSITION_BOOSTS.get((team, position), 1.0)


def candidate_pool_size_for_pick(pick: int) -> int:
    if pick <= 10:
        return 15
    if pick <= 20:
        return 20
    if pick <= 32:
        return 25
    return 35


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


def board_score_from_rank(rank: int) -> float:
    return 1.0 / (rank ** BOARD_EXPONENT)


def get_position_value_multiplier(position: str, pick: int) -> float:
    base = POSITION_VALUE.get(position, DEFAULT_POSITION_VALUE)

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
) -> float:
    if position != "QB":
        return score

    # elite QB can always survive
    if player_rank <= 3:
        return score

    if qb_need_weight >= 0.6:
        return score

    if qb_need_weight >= 0.3:
        return score * 0.65

    if pick <= 10:
        return score * 0.20
    if pick <= 32:
        return score * 0.35
    return score * 0.50


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

    return value


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(make_json_safe(payload), f, indent=2)


def build_run_paths(model_version: str, timestamp: datetime | None = None) -> dict[str, Path]:
    run_timestamp = timestamp or datetime.now()
    timestamp_str = run_timestamp.strftime("%Y-%m-%d_%H%M%S")
    run_dir = RUNS_DIR / f"{timestamp_str}_{model_version}"

    return {
        "run_dir": run_dir,
        "model_config": MODELS_DIR / f"{model_version}_config.json",
        "run_config": run_dir / "config.json",
        "metadata": run_dir / "metadata.json",
        "preview": run_dir / "single_mock_preview.csv",
        "simulated_picks": run_dir / "simulated_picks.csv",
        "player_by_pick": run_dir / "player_by_pick_probs.csv",
        "player_by_team": run_dir / "player_by_team_probs.csv",
        "position_by_team": run_dir / "position_by_team_probs.csv",
        "adp": run_dir / "adp_summary.csv",
    }


def build_run_metadata(
    *,
    model_version: str,
    timestamp: datetime,
    n_sims: int,
    random_seed: int,
) -> dict:
    return {
        "model_version": model_version,
        "timestamp": timestamp.isoformat(timespec="seconds"),
        "n_sims": n_sims,
        "random_seed": random_seed,
        "input_file_paths": {
            "big_board": str(BIG_BOARD_PATH),
            "team_needs": str(TEAM_NEEDS_PATH),
            "draft_order": str(DRAFT_ORDER_PATH),
            "player_overrides": str(PLAYER_OVERRIDES_PATH),
        },
    }


# =========================
# LOADERS
# =========================

def load_big_board(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path).copy()

    # expected columns from your earlier screenshot:
    # Rank, Player Name, Position, College
    rename_map = {
        "Rank": "rank",
        "Player Name": "player",
        "Position": "position",
        "College": "school",
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

    required = {"pick", "team"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"draft_order missing columns: {missing}")

    df["pick"] = df["pick"].astype(int)
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
) -> List[dict]:
    pool_size = candidate_pool_size_for_pick(pick)
    candidates = available_df.nsmallest(pool_size, "rank").copy()

    qb_need_weight = need_map.get((team, "QB"), 0.0)
    scored: List[dict] = []

    for row in candidates.itertuples(index=False):
        player = row.player
        position = row.position
        school = row.school
        rank = int(row.rank)

        need_weight = need_map.get((team, position), DEFAULT_NEED_WEIGHT)
        board_component = board_score_from_rank(rank)
        need_component = max(need_weight, DEFAULT_NEED_WEIGHT) ** NEED_EXPONENT
        pos_value_component = get_position_value_multiplier(position, pick)

        score = board_component * need_component * pos_value_component

        score = apply_qb_guardrail(
            score=score,
            position=position,
            player_rank=rank,
            qb_need_weight=qb_need_weight,
            pick=pick,
        )

        score = apply_elite_player_boost(
            score=score,
            rank=rank,
            pick=pick,
        )

        market_player_boost = get_market_player_boost(player, pick, team)

        if player == "Jeremiyah Love":
            print(
                f"DEBUG Love | pick={pick} team={team} rank={rank} "
                f"need={need_weight:.2f} pos_mult={pos_value_component:.2f} "
                f"market_boost={market_player_boost:.2f} score={score:.6f}"
            )
        market_team_pos_boost = get_market_team_position_boost(team, position, pick)

        score *= market_player_boost
        score *= market_team_pos_boost

        scored.append({
            "player": player,
            "position": position,
            "school": school,
            "rank": rank,
            "need_weight": need_weight,
            "board_component": board_component,
            "pos_value_component": pos_value_component,
            "score": score,
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
    available_df: pd.DataFrame,
    need_map: Dict[Tuple[str, str], float],
    overrides_df: pd.DataFrame,
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
            override_rows["probability"] = 1.0 / len(override_rows)
        else:
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
    rng: random.Random,
    sim_id: int | None = None,
) -> pd.DataFrame:
    available_df = big_board_df.copy()
    picks = []

    for row in draft_order_df.itertuples(index=False):
        result, _ = make_pick(
            team=row.team,
            pick=int(row.pick),
            round_num=1,
            available_df=available_df,
            need_map=need_map,
            overrides_df=overrides_df,
            rng=rng,
        )

        if sim_id is not None:
            result["sim_id"] = sim_id

        picks.append(result)
        available_df = available_df[available_df["player"] != result["player"]].copy()

    return pd.DataFrame(picks)


def run_simulations(
    n_sims: int,
    draft_order_df: pd.DataFrame,
    big_board_df: pd.DataFrame,
    need_map: Dict[Tuple[str, str], float],
    overrides_df: pd.DataFrame,
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
    run_timestamp = datetime.now()
    run_paths = build_run_paths(MODEL_VERSION, run_timestamp)
    run_paths["run_dir"].mkdir(parents=True, exist_ok=False)

    write_json(run_paths["model_config"], CONFIG)
    write_json(run_paths["run_config"], CONFIG)
    write_json(
        run_paths["metadata"],
        build_run_metadata(
            model_version=MODEL_VERSION,
            timestamp=run_timestamp,
            n_sims=N_SIMS,
            random_seed=RANDOM_SEED,
        ),
    )

    print("Loading data...")
    big_board_df = load_big_board(BIG_BOARD_PATH)
    need_map = load_team_needs(TEAM_NEEDS_PATH)
    draft_order_df = load_draft_order(DRAFT_ORDER_PATH)
    overrides_df = load_player_overrides(PLAYER_OVERRIDES_PATH)

    print("\nRunning one mock draft preview...")
    preview_rng = random.Random(RANDOM_SEED)
    preview_df = run_single_mock(
        draft_order_df=draft_order_df,
        big_board_df=big_board_df,
        need_map=need_map,
        overrides_df=overrides_df,
        rng=preview_rng,
    )
    print(preview_df.head(20).to_string(index=False))

    preview_path = run_paths["preview"]
    preview_df.to_csv(preview_path, index=False)
    print(f"\nWrote {preview_path}")

    print(f"\nRunning {N_SIMS} simulations...")
    results_df = run_simulations(
        n_sims=N_SIMS,
        draft_order_df=draft_order_df,
        big_board_df=big_board_df,
        need_map=need_map,
        overrides_df=overrides_df,
        seed=RANDOM_SEED,
    )

    simulated_picks_path = run_paths["simulated_picks"]
    results_df.to_csv(simulated_picks_path, index=False)
    print(f"Wrote {simulated_picks_path}")

    player_by_pick_df = summarize_player_by_pick(results_df)
    player_by_team_df = summarize_player_by_team(results_df)
    position_by_team_df = summarize_position_by_team(results_df)
    adp_df = summarize_adp(results_df)

    player_by_pick_path = run_paths["player_by_pick"]
    player_by_team_path = run_paths["player_by_team"]
    position_by_team_path = run_paths["position_by_team"]
    adp_path = run_paths["adp"]

    player_by_pick_df.to_csv(player_by_pick_path, index=False)
    player_by_team_df.to_csv(player_by_team_path, index=False)
    position_by_team_df.to_csv(position_by_team_path, index=False)
    adp_df.to_csv(adp_path, index=False)

    print(f"Wrote {run_paths['model_config']}")
    print(f"Wrote {run_paths['run_config']}")
    print(f"Wrote {run_paths['metadata']}")
    print(f"Wrote {player_by_pick_path}")
    print(f"Wrote {player_by_team_path}")
    print(f"Wrote {position_by_team_path}")
    print(f"Wrote {adp_path}")
    print("\nDone.")


if __name__ == "__main__":
    main()
