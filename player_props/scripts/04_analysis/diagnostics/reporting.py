from __future__ import annotations

from pathlib import Path
import math

import pandas as pd


def format_percent(value: object) -> str:
    return "" if value is None or pd.isna(value) else f"{float(value):.2%}"


def format_number(value: object, decimals: int = 2) -> str:
    return "" if value is None or pd.isna(value) else f"{float(value):.{decimals}f}"


def markdown_table(df: pd.DataFrame, max_rows: int = 20) -> str:
    if df.empty:
        return "_No qualifying rows._"
    view = df.head(max_rows).copy()
    percent_cols = {c for c in view.columns if c in {
        "roi", "win_rate", "removed_roi", "remaining_roi", "roi_lift",
        "pct_bets_retained", "actual_win_rate", "calibration_error",
        "absolute_calibration_error", "avg_predicted_probability",
        "roi_ci_95_low", "roi_ci_95_high", "conservative_score",
    }}
    for col in view.columns:
        if col in percent_cols:
            view[col] = view[col].map(format_percent)
        elif pd.api.types.is_float_dtype(view[col]):
            view[col] = view[col].map(format_number)
    lines = ["| " + " | ".join(map(str, view.columns)) + " |", "| " + " | ".join(["---"] * len(view.columns)) + " |"]
    for _, row in view.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(row[c]) else str(row[c]).replace("|", r"\|") for c in view.columns) + " |")
    return "\n".join(lines)


def write_report(
    output_dir: Path,
    input_path: Path,
    market: str,
    overall: pd.DataFrame,
    quality: pd.DataFrame,
    calibration_tables: dict[str, pd.DataFrame],
    slices: dict[str, pd.DataFrame],
    interactions: pd.DataFrame,
    kill_rules: pd.DataFrame,
    metadata: pd.DataFrame,
    warnings: list[str],
) -> None:
    s = overall.iloc[0]
    lines = [
        f"# Market Diagnostics: {market}",
        "",
        f"Input: `{input_path}`",
        "",
        "## Validated baseline",
        "",
        f"- Bets: **{int(s['bets'])}**",
        f"- Record: **{int(s['wins'])}-{int(s['losses'])}-{int(s['pushes'])}**",
        f"- Win rate: **{format_percent(s['win_rate'])}**",
        f"- Profit: **{format_number(s['profit_units'])} units**",
        f"- ROI: **{format_percent(s['roi'])}**",
    ]
    if not pd.isna(s.get("roi_ci_95_low")):
        lines.append(f"- Bootstrap 95% ROI interval: **{format_percent(s['roi_ci_95_low'])} to {format_percent(s['roi_ci_95_high'])}**")
    lines.extend(["", "## Edge and bucket definitions", "", markdown_table(metadata, 30)])
    if warnings:
        lines.extend(["", "## Data-quality findings", ""])
        lines.extend(f"- {w}" for w in warnings)
    lines.extend(["", "## Data quality", "", markdown_table(quality, 80)])

    for label, table in calibration_tables.items():
        if table.empty:
            continue
        lines.extend(["", f"## Calibration: {label}", "", markdown_table(table, 30)])

    worst = interactions.sort_values("conservative_score").head(12) if not interactions.empty else pd.DataFrame()
    best = interactions.sort_values("conservative_score", ascending=False).head(12) if not interactions.empty else pd.DataFrame()
    lines.extend(["", "## Strongest negative exploratory segments", "", markdown_table(worst, 12)])
    lines.extend(["", "## Strongest positive exploratory segments", "", markdown_table(best, 12)])
    lines.extend(["", "## Candidate exclusions", "", markdown_table(kill_rules, 20)])
    lines.extend([
        "",
        "## Warnings and holdout tests",
        "",
        "- Candidate exclusions are exploratory and discovered from many comparisons; none are production-ready.",
        "- Validate any hypothesis on a holdout season, rolling chronological split, or future settled sample before changing policy.",
    ])
    (output_dir / "diagnostics_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

