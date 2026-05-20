from pathlib import Path
import argparse
import shutil


ROOT = Path(__file__).resolve().parents[1]

MOVES = {
    # Model / engine scripts
    "scripts/04_analysis/build_projection_ensemble_engine.py": "scripts/03_modeling/build_projection_ensemble_engine.py",
    "scripts/04_analysis/build_receptions_projection_engine.py": "scripts/03_modeling/build_receptions_projection_engine.py",
    "scripts/04_analysis/build_fp_debiased_projection.py": "scripts/03_modeling/build_fp_debiased_projection.py",
    "scripts/04_analysis/build_pass_yds_sigma_model.py": "scripts/03_modeling/build_pass_yds_sigma_model.py",

    # API probes / tests
    "scripts/01_build/probe_historical_pass_yds_cost.py": "scripts/archive/probe_historical_pass_yds_cost.py",
    "scripts/01_build/test_fantasypoints_request.py": "scripts/archive/test_fantasypoints_request.py",
    "scripts/01_build/test_fantasypros_api.py": "scripts/archive/test_fantasypros_api.py",
    "scripts/01_build/test_fantasypros_request.py": "scripts/archive/test_fantasypros_request.py",
    "scripts/01_build/test_odds_api_usage.py": "scripts/archive/test_odds_api_usage.py",
    "scripts/04_analysis/test_historical_h2h.py": "scripts/archive/test_historical_h2h.py",
    "scripts/04_analysis/test_historical_props.py": "scripts/archive/test_historical_props.py",

    # Old pass-yards research / replaced by analyze_market.py
    "scripts/04_analysis/calibrate_pass_yds_distribution.py": "scripts/archive/calibrate_pass_yds_distribution.py",
    "scripts/04_analysis/pass_yds_ev_thresholds.py": "scripts/archive/pass_yds_ev_thresholds.py",
    "scripts/04_analysis/pass_yds_projection_error_penalty.py": "scripts/archive/pass_yds_projection_error_penalty.py",
}


def move_file(src_rel: str, dst_rel: str, apply: bool) -> None:
    src = ROOT / src_rel
    dst = ROOT / dst_rel

    if not src.exists():
        print(f"[skip missing] {src_rel}")
        return

    if dst.exists():
        print(f"[skip exists] {dst_rel}")
        return

    print(f"[move] {src_rel} -> {dst_rel}")

    if apply:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    print("===== PLAYER PROPS DIRECTORY CLEANUP =====")
    print(f"mode: {'APPLY' if args.apply else 'DRY RUN'}")

    for folder in ["scripts/archive", "scripts/03_modeling"]:
        path = ROOT / folder
        print(f"[mkdir] {folder}")
        if args.apply:
            path.mkdir(parents=True, exist_ok=True)

    for src, dst in MOVES.items():
        move_file(src, dst, apply=args.apply)

    print("\nDone.")
    if not args.apply:
        print("Dry run only. Run again with --apply to move files.")


if __name__ == "__main__":
    main()