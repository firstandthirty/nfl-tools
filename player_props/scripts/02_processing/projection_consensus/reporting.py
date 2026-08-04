from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


def _write_csv(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame.empty:
        frame.to_csv(path, index=False)
    else:
        frame.to_csv(path, index=False)


def build_consensus_outputs(selected_result: dict[str, Any], *, output_dir: Path | str | None = None, overwrite: bool = False) -> dict[str, Any]:
    consensus_rows = selected_result.get("consensus_rows")
    selected_source_df = selected_result.get("selected_source_projections")
    selected_snapshots_df = selected_result.get("selected_snapshots")
    pairwise_df = selected_result.get("pairwise_differences")
    coverage_df = selected_result.get("coverage_rows")
    overlap_df = selected_result.get("source_overlap")
    metadata = selected_result.get("metadata", {})
    warnings = selected_result.get("warnings", [])

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        if not overwrite and any((output_dir / name).exists() for name in ["selected_snapshots.csv", "selected_source_projections.csv", "consensus_long.csv", "source_pair_differences.csv", "consensus_coverage.csv", "source_overlap.csv", "consensus_run_metadata.csv", "consensus_report.md"]):
            raise FileExistsError(f"Consensus output directory already exists: {output_dir}")
        _write_csv(output_dir / "selected_snapshots.csv", selected_snapshots_df)
        _write_csv(output_dir / "selected_source_projections.csv", selected_source_df)
        _write_csv(output_dir / "consensus_long.csv", consensus_rows)
        _write_csv(output_dir / "source_pair_differences.csv", pairwise_df)
        _write_csv(output_dir / "consensus_coverage.csv", coverage_df)
        _write_csv(output_dir / "source_overlap.csv", overlap_df)
        metadata_df = pd.DataFrame([metadata])
        _write_csv(output_dir / "consensus_run_metadata.csv", metadata_df)
        report_lines = [
            "# Projection consensus report",
            "",
            f"- Requested as-of: {metadata.get('requested_as_of', '')}",
            f"- Selected sources: {metadata.get('selected_sources', '')}",
            f"- Unavailable sources: {metadata.get('unavailable_sources', '')}",
            f"- Selected snapshot count: {metadata.get('selected_snapshot_count', 0)}",
            f"- Selected projection rows: {metadata.get('selected_projection_rows', 0)}",
            f"- Consensus rows: {metadata.get('consensus_rows', 0)}",
            f"- Eligible consensus rows: {metadata.get('eligible_consensus_rows', 0)}",
            f"- Markets covered: {metadata.get('markets_covered', '')}",
            f"- Warnings: {metadata.get('warnings', '')}",
            "",
            "This output is a source-agnostic projection consensus layer. Single-source rows are recorded as ineligible multi-source consensus rows and are not presented as true consensus.",
        ]
        (output_dir / "consensus_report.md").write_text("\n".join(report_lines), encoding="utf-8")

    return {
        "consensus_rows": consensus_rows,
        "selected_source_projections": selected_source_df,
        "selected_snapshots": selected_snapshots_df,
        "pairwise_differences": pairwise_df,
        "coverage_rows": coverage_df,
        "source_overlap": overlap_df,
        "metadata": metadata,
        "warnings": warnings,
    }
