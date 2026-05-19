from pathlib import Path
import shutil

MOVES = {
    "data/historical_props/pass_yds_baseline_predictions.csv": "outputs/simulations/pass_yds_baseline_predictions.csv",
    "data/historical_props/pass_yds_sim_results.csv": "outputs/simulations/pass_yds_sim_results.csv",
    "data/historical_props/pass_yds_baseline_model_meta.json": "models/pass_yds_baseline_model_meta.json",

    "data/historical_props/market_results_summary.csv": "outputs/reports/market_results_summary.csv",

    "data/historical_props/game_context.csv": "data/processed/game_context.csv",
    "data/historical_props/merged_props_with_context.csv": "data/processed/merged_props_with_context.csv",
    "data/historical_props/merged_props_with_rolling.csv": "data/processed/merged_props_with_rolling.csv",
}

DIRS = [
    "data/raw",
    "data/interim",
    "data/processed",
    "outputs/context",
    "outputs/simulations",
    "outputs/reports",
    "models",
    "scripts/archive",
]


def main():
    for d in DIRS:
        Path(d).mkdir(parents=True, exist_ok=True)

    for src, dst in MOVES.items():
        src_path = Path(src)
        dst_path = Path(dst)

        if not src_path.exists():
            print(f"[skip] missing: {src}")
            continue

        dst_path.parent.mkdir(parents=True, exist_ok=True)

        if dst_path.exists():
            print(f"[skip] already exists: {dst}")
            continue

        shutil.copy2(src_path, dst_path)
        print(f"[copy] {src} -> {dst}")

    print("\nDone. I copied files instead of moving them.")
    print("Once everything works, you can manually delete old duplicates.")


if __name__ == "__main__":
    main()