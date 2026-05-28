from pathlib import Path
import subprocess
import sys

import pandas as pd


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = SCRIPT_ROOT.parent
if str(SCRIPT_ROOT / "00_config") not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT / "00_config"))

from market_config import MARKET_CONFIG


OUT_FILE = Path("data/analysis/player_props_cleanup_inventory.csv")

AUDIT_ROOTS = [
    Path("scripts/00_config"),
    Path("scripts/01_build"),
    Path("scripts/02_processing"),
    Path("scripts/03_modeling"),
    Path("scripts/04_analysis"),
    Path("data/analysis"),
    Path("data/analysis/backtests"),
    Path("data/processed"),
]

ACTIVE_EXPLICIT = {
    "scripts/00_config/market_config.py",
    "scripts/03_modeling/backtest_market_model.py",
    "scripts/03_modeling/build_market_projection_engine.py",
    "scripts/03_modeling/build_projection_ensemble_engine.py",
    "scripts/03_modeling/build_receptions_projection_engine.py",
    "scripts/03_modeling/build_receiving_yds_projection_engine.py",
    "scripts/03_modeling/build_rush_yds_projection_engine.py",
    "scripts/04_analysis/validate_safe_outputs.py",
    "scripts/04_analysis/audit_pass_yds_source_lineage.py",
    "scripts/04_analysis/build_pass_yds_backtest_safe_sidecar.py",
    "scripts/04_analysis/build_cleanup_inventory.py",
}

ACTIVE_NAME_PATTERNS = [
    "_backtest_safe.csv",
    "missing_actuals_audit.csv",
    "safe_output_validation_summary",
    "pass_yds_source_lineage_audit.csv",
    "pass_yds_safe_sidecar_validation.csv",
]

REFERENCE_NAME_PATTERNS = [
    "parity",
    "archive",
    "baseline",
    "simulate_pass_yds",
]

DELETE_NAME_PATTERNS = [
    "__pycache__",
    ".pyc",
    ".tmp",
    "~",
]

ARCHIVE_NAME_PATTERNS = [
    "test_",
    "diagnose_",
    "debug",
    "calibration",
    "residual",
    "eda_",
    "plot",
    "audit_",
    "validate_",
]


def norm_path(path):
    return path.as_posix()


def git_tracked_paths():
    try:
        result = subprocess.run(
            ["git", "ls-files"],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return set()
    return {line.strip().replace("\\", "/") for line in result.stdout.splitlines() if line.strip()}


def collect_config_paths():
    paths = set()
    for config in MARKET_CONFIG.values():
        for key in ["history_file", "analysis_rows_file", "primary_actuals_file", "fallback_actuals_file"]:
            value = config.get(key)
            if value is not None:
                paths.add(norm_path(Path(value)))
        engine_config = config.get("projection_engine", {})
        for value in engine_config.values():
            if isinstance(value, Path):
                paths.add(norm_path(value))
        backtest_config = config.get("backtest", {})
        for value in backtest_config.values():
            if isinstance(value, Path):
                paths.add(norm_path(value))
    return paths


def is_binary_or_large(path):
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".pdf", ".pkl", ".parquet"} or path.stat().st_size > 5_000_000


def detect_callers(target_path):
    if target_path.suffix != ".py":
        return ""
    token = target_path.stem
    callers = []
    for script_dir in [Path("scripts/01_build"), Path("scripts/02_processing"), Path("scripts/03_modeling"), Path("scripts/04_analysis")]:
        if not script_dir.exists():
            continue
        for path in script_dir.rglob("*.py"):
            if path == target_path:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if token in text:
                callers.append(norm_path(path))
    return "; ".join(sorted(callers)[:8])


def classify(path, config_paths, tracked):
    path_str = norm_path(path)
    name = path.name
    lower_path = path_str.lower()
    callers = detect_callers(path)

    if path_str in ACTIVE_EXPLICIT:
        return "keep_active", "explicitly active in cleanup instructions/current workflow", callers, "no"
    if path_str in config_paths:
        return "keep_active", "referenced by MARKET_CONFIG", callers, "no"
    if any(pattern in name for pattern in ACTIVE_NAME_PATTERNS):
        return "keep_active", "safe-output, audit, or validation artifact from current workflow", callers, "no"
    if path.suffix == ".py" and callers:
        return "keep_active", "imported or referenced by another script", callers, "no"
    if any(pattern in lower_path for pattern in DELETE_NAME_PATTERNS):
        return "delete_candidate", "generated cache/temp artifact", callers, "yes"
    if any(pattern in lower_path for pattern in REFERENCE_NAME_PATTERNS):
        return "keep_reference", "reference/baseline/parity/archive artifact", callers, "no"
    if path.suffix.lower() in {".png", ".jpg", ".jpeg"}:
        return "archive_candidate", "generated plot/image output; likely archival analysis artifact", callers, "no"
    if any(pattern in lower_path for pattern in ARCHIVE_NAME_PATTERNS):
        return "archive_candidate", "diagnostic/audit/validation/calibration-style artifact", callers, "no"
    if path.suffix.lower() == ".csv" and path_str.startswith("data/analysis/backtests/"):
        return "keep_reference", "backtest output artifact; useful for comparison/history", callers, "no"
    if path.suffix.lower() == ".csv" and path_str.startswith("data/analysis/"):
        return "unknown_review_needed", "analysis CSV not directly classified; review usage before archiving", callers, "no"
    if path.suffix.lower() == ".csv" and path_str.startswith("data/processed/"):
        return "unknown_review_needed", "processed dataset may be upstream input; review lineage before archiving", callers, "no"
    if path.suffix.lower() == ".py":
        return "unknown_review_needed", "script not detected as active; review manually before archiving", callers, "no"

    tracked_status = "yes" if path_str in tracked else "no"
    return "unknown_review_needed", f"unclassified {path.suffix or 'file'}; git_tracked={tracked_status}", callers, "no"


def file_type(path):
    if path.suffix:
        return path.suffix.lower().lstrip(".")
    return "file"


def main():
    tracked = git_tracked_paths()
    config_paths = collect_config_paths()
    files = []
    seen = set()
    for root in AUDIT_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            path_str = norm_path(path)
            if path_str in seen:
                continue
            seen.add(path_str)
            files.append(path)

    rows = []
    for path in sorted(files, key=lambda p: norm_path(p)):
        category, reason, callers, safe_to_delete = classify(path, config_paths, tracked)
        rows.append(
            {
                "file_path": norm_path(path),
                "file_type": file_type(path),
                "category": category,
                "reason": reason,
                "imports_or_called_by": callers,
                "git_tracked": "yes" if norm_path(path) in tracked else "no",
                "last_modified": pd.Timestamp(path.stat().st_mtime, unit="s").isoformat(),
                "safe_to_delete_now": safe_to_delete,
            }
        )

    inventory = pd.DataFrame(rows)
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    inventory.to_csv(OUT_FILE, index=False)

    print("===== CLEANUP INVENTORY SUMMARY =====")
    print(inventory["category"].value_counts().to_string())

    print("\n===== TOP DELETE CANDIDATES =====")
    delete_cols = ["file_path", "category", "reason", "safe_to_delete_now"]
    print(
        inventory[inventory["category"].eq("delete_candidate")]
        .head(25)[delete_cols]
        .to_string(index=False)
    )

    print("\n===== TOP ARCHIVE CANDIDATES =====")
    print(
        inventory[inventory["category"].eq("archive_candidate")]
        .head(25)[delete_cols]
        .to_string(index=False)
    )

    print(f"\n[output] {OUT_FILE}")


if __name__ == "__main__":
    main()
