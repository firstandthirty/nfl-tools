from pathlib import Path
import argparse
import sys

import numpy as np
import pandas as pd


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT / "00_config") not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT / "00_config"))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from market_config import MARKET_CONFIG
import build_projection_ensemble_engine as passing_engine
import build_receptions_projection_engine as receptions_engine
import build_receiving_yds_projection_engine as receiving_engine
import build_rush_yds_projection_engine as rush_engine


DEFAULT_MARKET = "player_reception_yds"
SUPPORTED_MARKETS = {
    "player_pass_yds": passing_engine,
    "player_receptions": receptions_engine,
    "player_reception_yds": receiving_engine,
    "player_rush_yds": rush_engine,
}


def run_passing_ensemble(args, config):
    engine_config = config["projection_engine"]
    thresholds = engine_config["recommendation_thresholds"]

    passing_engine.INPUT_FILE = Path(args.projections or engine_config["projections_file"])
    passing_engine.OUT_FILE = Path(args.output or engine_config["output_file"])
    passing_engine.OUT_DIR = passing_engine.OUT_FILE.parent
    passing_engine.OUTCOME_SIGMA = engine_config["outcome_sigma"]
    passing_engine.SOURCE_SIGMA = dict(engine_config["source_sigma"])

    def recommendation(edge_yards, consensus):
        abs_edge = abs(edge_yards)
        if consensus == "elite" and abs_edge >= thresholds["strong_bet_elite_edge"]:
            return "STRONG BET"
        if consensus in ["elite", "strong"] and abs_edge >= thresholds["bet_edge"]:
            return "BET"
        if consensus != "weak" and abs_edge >= thresholds["lean_edge"]:
            return "LEAN"
        return "PASS"

    passing_engine.recommendation = recommendation
    passing_engine.main()


def add_line_bucket(df, config, line_col):
    engine_config = config["projection_engine"]
    df["line_bucket"] = pd.cut(
        df[line_col],
        bins=engine_config.get("line_bins", config["line_bins"]),
        labels=engine_config.get("line_labels", config["line_labels"]),
        right=False,
    )
    return df


def load_history(history_file, config, reference_engine):
    hist = pd.read_csv(history_file)
    line_col = config["line_col"]

    if line_col not in hist.columns:
        raise RuntimeError(f"Historical file missing required {config['label']} line column: {line_col}")

    candidates = ["actual", "actual_market_value", *config["actual_col_candidates"]]
    actual_col = reference_engine.find_col(
        hist,
        candidates,
        required=False,
        label=f"{config['label']} actual column",
    )
    if actual_col is None:
        raise RuntimeError(
            f"Historical file does not contain actual {config['label'].lower()}. "
            f"Looked for: {candidates}. Rerun analyze_market.py first if needed."
        )

    if "position" not in hist.columns:
        raise RuntimeError(
            f"Historical file does not contain position for {config['label'].lower()} variance estimates."
        )

    hist = hist.copy()
    hist["actual"] = pd.to_numeric(hist[actual_col], errors="coerce")
    hist["line"] = pd.to_numeric(hist[line_col], errors="coerce")
    hist["actual_minus_line"] = hist["actual"] - hist["line"]
    hist["position"] = hist["position"].fillna("UNKNOWN").astype(str)
    hist = hist.dropna(subset=["actual", "line"])
    return add_line_bucket(hist, config, "line")


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--market", default=DEFAULT_MARKET)
    parser.add_argument("--projections", type=Path)
    parser.add_argument("--markets", type=Path)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--n-sims", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--min-ev", type=float)
    parser.add_argument("--min-prob", type=float)
    parser.add_argument("--min-line", type=float)
    return parser.parse_args()


def main():
    args = parse_args()
    market_key = args.market
    if market_key not in SUPPORTED_MARKETS:
        raise RuntimeError(
            f"Market {market_key!r} is configured but is not migrated to the generalized projection engine yet. "
            f"Currently supported: {', '.join(sorted(SUPPORTED_MARKETS))}"
        )

    config = MARKET_CONFIG[market_key]
    engine_config = config["projection_engine"]
    reference_engine = SUPPORTED_MARKETS[market_key]
    if engine_config.get("reference_engine") == "passing_ensemble":
        run_passing_ensemble(args, config)
        return
    if config["distribution"] not in {"normal", "negative_binomial"}:
        raise RuntimeError(
            f"{config['label']} is configured for distribution={config['distribution']!r}; "
            "the generalized projection engine does not implement that simulation."
        )
    if config["line_col"] != "line":
        raise RuntimeError(
            f"The parity implementation expects canonical line_col='line', got {config['line_col']!r}."
        )

    reference_engine.MARKET = market_key
    reference_engine.HISTORY_FILE = Path(engine_config["history_file"])
    reference_engine.OUT_FILE = Path(engine_config["output_file"])
    reference_engine.N_SIMS_DEFAULT = engine_config["n_sims"]
    reference_engine.RANDOM_SEED_DEFAULT = engine_config["random_seed"]
    reference_engine.PROJECTION_COL_CANDIDATES = [
        config["projection_col"],
        *engine_config["projection_col_fallback_candidates"],
    ]
    reference_engine.add_line_bucket = lambda df, line_col="line": add_line_bucket(df, config, line_col)
    reference_engine.load_history = lambda history_file: load_history(history_file, config, reference_engine)
    if config["distribution"] == "normal":
        reference_engine.STD_INFLATION_FACTOR = engine_config["std_inflation_factor"]
        reference_engine.simulate_normal_yards = lambda mean, std, n_sims, rng, max_clip=None: np.clip(
            rng.normal(loc=max(float(mean), 0.0), scale=max(float(std), 1.0), size=n_sims),
            0,
            engine_config["max_sim_value"],
        )
    else:
        def simulate_negative_binomial(mean, variance, n_sims, rng):
            mean = max(float(mean), 0.01)
            variance = max(float(variance), mean + 0.01)
            p = min(max(mean / variance, 1e-6), 0.999999)
            r = mean * mean / max(variance - mean, 1e-6)
            sims = rng.negative_binomial(r, p, size=n_sims)
            return np.clip(sims, 0, engine_config["max_sim_value"])

        reference_engine.simulate_negative_binomial = simulate_negative_binomial

    resolved_args = {
        "--projections": args.projections or engine_config["projections_file"],
        "--markets": args.markets or engine_config["markets_file"],
        "--history": args.history or engine_config["history_file"],
        "--output": args.output or engine_config["output_file"],
        "--n-sims": args.n_sims if args.n_sims is not None else engine_config["n_sims"],
        "--seed": args.seed if args.seed is not None else engine_config["random_seed"],
        "--min-ev": args.min_ev if args.min_ev is not None else engine_config["min_ev"],
        "--min-prob": args.min_prob if args.min_prob is not None else engine_config["min_prob"],
    }
    if engine_config.get("passes_min_line", True):
        resolved_args["--min-line"] = (
            args.min_line if args.min_line is not None else config["min_line"]
        )
    if market_key == "player_reception_yds":
        reference_engine.MARKET_CONFIG[market_key]["min_line"] = resolved_args["--min-line"]
    forwarded_args = [
        value
        for option, option_value in resolved_args.items()
        if not (
            option == "--min-line"
            and args.min_line is None
            and market_key == "player_rush_yds"
        )
        for value in (option, str(option_value))
    ]

    original_argv = sys.argv
    original_add_argument = argparse.ArgumentParser.add_argument
    if market_key == "player_receptions":
        # Python 3.14 validates argparse help strings; escape only the legacy literal percent sign.
        def add_argument_with_safe_help(parser, *option_strings, **kwargs):
            if "help" in kwargs:
                kwargs["help"] = kwargs["help"].replace("%", "%%")
            return original_add_argument(parser, *option_strings, **kwargs)

        argparse.ArgumentParser.add_argument = add_argument_with_safe_help
    sys.argv = [original_argv[0], *forwarded_args]
    try:
        reference_engine.main()
    finally:
        sys.argv = original_argv
        argparse.ArgumentParser.add_argument = original_add_argument


if __name__ == "__main__":
    main()
