from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "scripts" / "02_processing") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "02_processing"))

from projection_consensus.loader import load_snapshot_registry


VALID_SNAPSHOT_STATUSES = {"passed", "passed_with_warnings", ""}


def _infer_source_format(row: pd.Series) -> str:
    source_format = str(row.get("source_format", "")).strip().lower()
    if source_format:
        return source_format
    raw_file = str(row.get("raw_file", "")).strip().lower()
    raw_file_name = str(row.get("raw_file_name", "")).strip().lower()
    component_files = str(row.get("component_raw_files", "")).strip().lower()
    if raw_file.endswith(".json") or raw_file_name.endswith(".json") or ".json" in component_files:
        return "api"
    return "csv"


def _is_usable_snapshot(row: pd.Series, *, project_root: Path) -> bool:
    status = str(row.get("validation_status", "")).strip().lower()
    if status not in VALID_SNAPSHOT_STATUSES:
        return False
    try:
        canonical_rows = int(row.get("canonical_rows", 0) or 0)
    except (TypeError, ValueError):
        canonical_rows = 0
    if canonical_rows <= 0:
        return False
    processed_file = str(row.get("processed_long_file", "")).strip()
    if not processed_file:
        return False
    processed_path = Path(processed_file)
    if not processed_path.is_absolute():
        processed_path = project_root / processed_path
    return processed_path.exists()


def _latest_snapshot_by_format(rows: pd.DataFrame, *, source_format: str) -> pd.Series | None:
    format_rows = rows.loc[rows["audit_source_format"] == source_format].copy()
    if format_rows.empty:
        return None
    return format_rows.sort_values(["captured_at_dt", "raw_file"], ascending=[True, True]).iloc[-1]


def _read_long(project_root: Path, registry_row: pd.Series) -> pd.DataFrame:
    path = project_root / str(registry_row["processed_long_file"])
    frame = pd.read_csv(path)
    frame["snapshot_captured_at"] = registry_row["captured_at"]
    frame["snapshot_source_format"] = registry_row.get("source_format", "")
    return frame


def build_fantasypros_snapshot_audit(*, project_root: Path, season: int, week: int) -> dict[str, pd.DataFrame]:
    registry_path = project_root / "data" / "processed" / "projections" / "snapshot_registry.csv"
    registry = load_snapshot_registry(registry_path, project_root=project_root)
    rows = registry.loc[
        (registry["source"].astype(str) == "fantasypros")
        & (registry["season"].astype(int) == int(season))
        & (registry["week"].astype(int) == int(week))
    ].copy()
    if rows.empty:
        return {"selected_snapshots": pd.DataFrame(), "overlap": pd.DataFrame(), "market_coverage": pd.DataFrame(), "team_position_changes": pd.DataFrame()}

    rows["audit_source_format"] = rows.apply(_infer_source_format, axis=1)
    rows["audit_usable"] = rows.apply(lambda row: _is_usable_snapshot(row, project_root=project_root), axis=1)
    rows = rows.loc[rows["audit_usable"]].copy()
    csv_snapshot = _latest_snapshot_by_format(rows, source_format="csv")
    api_snapshot = _latest_snapshot_by_format(rows, source_format="api")
    selected = [row for row in [csv_snapshot, api_snapshot] if row is not None]
    selected_df = pd.DataFrame([row.to_dict() for row in selected])
    if not selected:
        return {"selected_snapshots": selected_df, "overlap": pd.DataFrame(), "market_coverage": pd.DataFrame(), "team_position_changes": pd.DataFrame()}

    frames = [_read_long(project_root, row) for row in selected]
    labeled = list(zip(rows.to_dict(orient="records"), frames))
    labeled = list(zip([row.to_dict() for row in selected], frames))
    comparison_rows: list[dict] = []
    team_position_rows: list[dict] = []
    coverage_rows: list[dict] = []

    for meta, frame in labeled:
        for market, market_rows in frame.groupby("market"):
            coverage_rows.append(
                {
                    "source": "fantasypros",
                    "source_format": meta.get("source_format", ""),
                    "captured_at": meta["captured_at"],
                    "market": market,
                    "rows": len(market_rows),
                    "unique_players": market_rows["player_normalized"].nunique(),
                }
            )

    if csv_snapshot is not None and api_snapshot is not None:
        prior_meta, prior_df = labeled[0]
        current_meta, current_df = labeled[1]
        merged = prior_df.merge(
            current_df,
            on=["player_normalized", "market"],
            suffixes=("_prior", "_current"),
            how="inner",
        )
        for _, row in merged.iterrows():
            prior_projection = float(row["projection_prior"])
            current_projection = float(row["projection_current"])
            comparison_rows.append(
                {
                    "source": "fantasypros",
                    "prior_source_format": prior_meta.get("source_format", ""),
                    "current_source_format": current_meta.get("source_format", ""),
                    "prior_captured_at": prior_meta["captured_at"],
                    "current_captured_at": current_meta["captured_at"],
                    "player": row.get("player_current") or row.get("player_prior"),
                    "player_normalized": row["player_normalized"],
                    "market": row["market"],
                    "prior_projection": prior_projection,
                    "current_projection": current_projection,
                    "signed_change": current_projection - prior_projection,
                    "absolute_change": abs(current_projection - prior_projection),
                }
            )
            if row.get("team_prior") != row.get("team_current") or row.get("position_prior") != row.get("position_current"):
                team_position_rows.append(
                    {
                        "player": row.get("player_current") or row.get("player_prior"),
                        "player_normalized": row["player_normalized"],
                        "market": row["market"],
                        "prior_team": row.get("team_prior"),
                        "current_team": row.get("team_current"),
                        "prior_position": row.get("position_prior"),
                        "current_position": row.get("position_current"),
                        "prior_captured_at": prior_meta["captured_at"],
                        "current_captured_at": current_meta["captured_at"],
                    }
                )

    return {
        "selected_snapshots": selected_df,
        "overlap": pd.DataFrame(comparison_rows),
        "market_coverage": pd.DataFrame(coverage_rows),
        "team_position_changes": pd.DataFrame(team_position_rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit FantasyPros API-vs-CSV snapshot changes")
    parser.add_argument("--season", required=True, type=int)
    parser.add_argument("--week", required=True, type=int)
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()

    outputs = build_fantasypros_snapshot_audit(project_root=PROJECT_ROOT, season=args.season, week=args.week)
    output_dir = args.output_root / "data" / "analysis" / "projection_audits" / "fantasypros" / str(args.season) / f"week_{args.week:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in outputs.items():
        frame.to_csv(output_dir / f"{name}.csv", index=False)

    print(f"output_dir={output_dir}")
    selected = outputs["selected_snapshots"]
    if selected.empty:
        print("csv_snapshot=")
        print("api_snapshot=")
    else:
        for source_format in ["csv", "api"]:
            format_rows = selected.loc[selected["audit_source_format"] == source_format]
            if format_rows.empty:
                print(f"{source_format}_snapshot=")
            else:
                row = format_rows.iloc[0]
                print(f"{source_format}_snapshot={row['captured_at']} | {row['processed_long_file']}")
    print(f"overlap_rows={len(outputs['overlap'])}")
    print(f"market_coverage_rows={len(outputs['market_coverage'])}")
    print(f"team_position_change_rows={len(outputs['team_position_changes'])}")
    if not outputs["overlap"].empty:
        print("largest_changes:")
        print(outputs["overlap"].sort_values("absolute_change", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()
