import ast
import csv
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "data/analysis/diagnostics/player_props_cleanup_inventory.csv"
SCAN_DATA_ROOTS = [
    ROOT / "data/analysis",
    ROOT / "data/processed",
    ROOT / "data/historical_props",
]
DOC_ROOTS = [ROOT / "docs"]

KEEP_ACTIVE = {
    "scripts/00_config/market_config.py": "Active market configuration.",
    "scripts/03_modeling/build_market_projection_engine.py": "Active generalized projection workflow.",
    "scripts/03_modeling/backtest_market_model.py": "Active generalized backtest workflow.",
    "scripts/01_build/backfill_closing_props.py": "Current historical prop acquisition utility.",
    "scripts/01_build/merge_props_with_actuals.py": "Historical props actuals preparation utility.",
    "scripts/01_build/build_game_context_from_nflverse.py": "Historical game-context preparation utility.",
    "scripts/01_build/merge_game_context.py": "Historical props context preparation utility.",
    "scripts/01_build/ingest_fantasypros_weekly_projections_api.py": "Configured FantasyPros projection ingest.",
    "scripts/01_build/ingest_pff.py": "Actual-stat ingestion utility.",
}

KEEP_REFERENCE = {
    "scripts/03_modeling/build_receiving_yds_projection_engine.py": "Receiving-yards parity reference and imported implementation.",
    "scripts/03_modeling/backtest_receiving_yds_model.py": "Receiving-yards backtest parity reference.",
    "scripts/03_modeling/build_rush_yds_projection_engine.py": "Rushing-yards parity reference and imported implementation.",
    "scripts/03_modeling/backtest_rush_yds_model.py": "Rushing-yards backtest parity reference.",
    "scripts/03_modeling/build_receptions_projection_engine.py": "Receptions parity reference and imported implementation.",
    "scripts/03_modeling/build_projection_ensemble_engine.py": "Passing-yards parity reference and imported implementation.",
    "scripts/03_modeling/simulate_pass_yds.py": "Passing-yards backtest parity reference and imported implementation.",
}


def rel(path):
    return path.relative_to(ROOT).as_posix()


def docs_text():
    chunks = []
    for base in DOC_ROOTS:
        if not base.exists():
            continue
        for path in base.rglob("*.md"):
            chunks.append((rel(path), path.read_text(encoding="utf-8", errors="ignore")))
    return chunks


def git_file_sets():
    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    ).stdout.splitlines()
    tracked_set = {p.replace("\\", "/") for p in tracked}
    return tracked_set


def ignored_paths(paths):
    if not paths:
        return set()
    result = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=ROOT,
        text=True,
        input="\n".join(paths),
        capture_output=True,
        check=False,
    )
    return {p.replace("\\", "/") for p in result.stdout.splitlines()}


def script_purpose(path):
    name = path.name.lower()
    parent = path.parent.name.lower()
    if parent == "00_config":
        return "Market configuration"
    if parent == "01_build":
        if name.startswith("ingest_"):
            return "Source data ingestion"
        if name.startswith("backfill_") or name.startswith("archive_"):
            return "Historical/source data collection"
        if name.startswith("merge_") or name.startswith("build_"):
            return "Dataset preparation"
        return "Build-layer utility"
    if parent == "02_features":
        return "Feature construction"
    if parent == "03_modeling":
        if name.startswith("backtest_") or name.startswith("simulate_"):
            return "Model backtest/simulation"
        return "Projection/model construction"
    if parent == "04_analysis":
        return "Read-only analysis/diagnostic"
    if parent == "archive":
        return "Archived experiment/test utility"
    return "Project utility"


def python_import_targets(paths):
    stem_to_paths = {}
    for path in paths:
        stem_to_paths.setdefault(path.stem, []).append(rel(path))
    imported_by = {rel(path): set() for path in paths}
    for caller in paths:
        try:
            tree = ast.parse(caller.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        modules = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[-1] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module.split(".")[-1])
        for module in modules:
            for target in stem_to_paths.get(module, []):
                if target != rel(caller):
                    imported_by[target].add(rel(caller))
    return imported_by


def script_category(path_str):
    if path_str in KEEP_ACTIVE:
        return "KEEP_ACTIVE", KEEP_ACTIVE[path_str]
    if path_str in KEEP_REFERENCE:
        return "KEEP_REFERENCE", KEEP_REFERENCE[path_str]
    if path_str.startswith("scripts/04_analysis/"):
        return "KEEP_DIAGNOSTIC", "Analysis output is reproducible; keep script while investigation remains active."
    if path_str.startswith("scripts/archive/"):
        return "ARCHIVE_CANDIDATE", "Already archived; retain only if past experiment provenance matters."
    if path_str == "scripts/cleanup_project_dirs.py":
        return "ARCHIVE_CANDIDATE", "One-time project layout utility."
    return "UNKNOWN_REVIEW_MANUALLY", "No safe deletion conclusion from static inventory."


def script_rows():
    paths = sorted((ROOT / "scripts").rglob("*.py"))
    imported_by = python_import_targets(paths)
    docs = docs_text()
    rows = []
    for path in paths:
        path_str = rel(path)
        category, rationale = script_category(path_str)
        mentions = [doc for doc, text in docs if path.name in text or path_str in text]
        callers = sorted(imported_by.get(path_str, []))
        rows.append(
            {
                "item_type": "script",
                "path": path_str,
                "size_bytes": path.stat().st_size,
                "apparent_purpose": script_purpose(path),
                "imported_by": "; ".join(callers),
                "mentioned_in_docs": "; ".join(mentions),
                "category": category,
                "rationale": rationale,
                "regenerable": "",
                "git_tracked": "",
                "git_ignored": "",
            }
        )
    return rows


def data_category(path_str):
    lower = path_str.lower()
    name = Path(path_str).name.lower()
    if "/raw/" in lower or lower.startswith("data/historical_props/raw/"):
        return "IGNORE_GIT_CANDIDATE", "Raw/cache source artifact; large and reproducible from source requests where available.", "false"
    if "__pycache__" in lower or name.endswith(".pyc"):
        return "DELETE_CANDIDATE", "Interpreter cache; safely regenerable.", "true"
    if "receptions_backtest" in lower:
        return "DELETE_CANDIDATE", "Receptions generalized backtest was intentionally blocked as invalid without stable join keys.", "true"
    if name.startswith("override_"):
        return "ARCHIVE_CANDIDATE", "One-off override experiment output.", "true"
    if lower in {
        "data/processed/fantasypros_weekly_projections_api.csv",
        "data/processed/pff/pff_player_weekly_master.csv",
    }:
        return "KEEP_ACTIVE", "Current configured input to active generalized workflow.", "true"
    if lower.startswith("data/analysis/") and name.endswith("model_bets.csv"):
        return "ARCHIVE_CANDIDATE", "Generated model-candidate output; retain only selected validation evidence.", "true"
    if "parity_" in lower or "validation_after_" in lower or "production_experiment" in lower or "config_filter" in lower:
        return "ARCHIVE_CANDIDATE", "Validation/experiment evidence; retain outside working outputs if provenance is needed.", "true"
    if lower.startswith("data/analysis/diagnostics/"):
        return "KEEP_DIAGNOSTIC", "Analysis evidence; archive later when conclusions are documented.", "true"
    if lower.startswith("data/analysis/plots/"):
        return "ARCHIVE_CANDIDATE", "Generated visualization output.", "true"
    if lower.startswith("data/analysis/backtests/"):
        return "KEEP_ACTIVE", "Current backtest output location; retain latest validated summaries/rows.", "true"
    if "fantasypros_receiving_weekly_projections.csv" in lower:
        return "ARCHIVE_CANDIDATE", "Contains invalid hindsight-roster 2023 receiving projections; do not use for validation.", "true"
    if lower in {
        "data/processed/merged_props_with_rolling.csv",
        "data/processed/merged_props_with_context.csv",
    }:
        return "ARCHIVE_CANDIDATE", "Duplicate generated processed artifact; active config uses the historical_props path.", "true"
    if "merged_props_with_actuals_2023" in lower or "merged_props_with_context_2023" in lower or "game_context_2023" in lower:
        return "KEEP_DIAGNOSTIC", "Current 2023 preparation pilot artifact.", "true"
    if lower.startswith("data/processed/archive/") or lower.startswith("data/processed/eda"):
        return "ARCHIVE_CANDIDATE", "Generated intermediate/EDA output.", "true"
    if lower.startswith("data/historical_props/"):
        return "IGNORE_GIT_CANDIDATE", "Historical input/output material already excluded from version control.", "true"
    if lower.startswith("data/processed/") or lower.startswith("data/analysis/"):
        return "UNKNOWN_REVIEW_MANUALLY", "Processed/generated artifact; confirm dependency before cleanup.", "true"
    return "UNKNOWN_REVIEW_MANUALLY", "Unclassified artifact.", ""


def data_rows(tracked, ignored):
    rows = []
    for base in SCAN_DATA_ROOTS:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            path_str = rel(path)
            category, rationale, regenerable = data_category(path_str)
            rows.append(
                {
                    "item_type": "data_file",
                    "path": path_str,
                    "size_bytes": path.stat().st_size,
                    "apparent_purpose": "Generated/output/cache data",
                    "imported_by": "",
                    "mentioned_in_docs": "",
                    "category": category,
                    "rationale": rationale,
                    "regenerable": regenerable,
                    "git_tracked": str(path_str in tracked).lower(),
                    "git_ignored": str(path_str in ignored).lower(),
                }
            )
    return rows


def print_summary(rows):
    categories = [
        "KEEP_ACTIVE",
        "KEEP_REFERENCE",
        "KEEP_DIAGNOSTIC",
        "ARCHIVE_CANDIDATE",
        "DELETE_CANDIDATE",
        "IGNORE_GIT_CANDIDATE",
        "UNKNOWN_REVIEW_MANUALLY",
    ]
    print("===== PLAYER_PROPS CLEANUP INVENTORY =====")
    for category in categories:
        selected = [row for row in rows if row["category"] == category]
        scripts = [row for row in selected if row["item_type"] == "script"]
        data = [row for row in selected if row["item_type"] == "data_file"]
        size_mb = sum(row["size_bytes"] for row in data) / (1024 * 1024)
        print(f"\n{category}: scripts={len(scripts)} data_files={len(data)} data_mb={size_mb:.2f}")
        for row in scripts:
            suffix = f" imported_by={row['imported_by']}" if row["imported_by"] else ""
            print(f"  SCRIPT {row['path']}{suffix}")
        for row in sorted(data, key=lambda item: item["size_bytes"], reverse=True)[:8]:
            print(f"  DATA   {row['path']} ({row['size_bytes'] / (1024 * 1024):.2f} MB)")
        if len(data) > 8:
            print(f"  ... {len(data) - 8} more data files")


def main():
    script_inventory = script_rows()
    data_paths = [
        rel(path)
        for base in SCAN_DATA_ROOTS
        if base.exists()
        for path in base.rglob("*")
        if path.is_file()
    ]
    tracked = git_file_sets()
    ignored = ignored_paths(data_paths)
    rows = script_inventory + data_rows(tracked, ignored)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print_summary(rows)
    print(f"\n[saved] {rel(OUTPUT)}")
    print(f"[inventory] scripts={len(script_inventory)} data_files={len(rows) - len(script_inventory)} total={len(rows)}")


if __name__ == "__main__":
    main()
