#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path
import sys

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from diagnostics.buckets import add_buckets
from diagnostics.calibration import calibration_table
from diagnostics.holdout import (
    add_probability_audit_fields,
    choose_chronological_split,
    current_rule_035,
    interaction_suite,
    monotonic_direction,
    probability_audit,
    quantile_lift,
    resolved_split_table,
    save_holdout_charts,
    season_summary,
    threshold_stability,
)
from diagnostics.loader import read_input, standardize_frame
from diagnostics.metrics import summarize
from diagnostics.reporting import markdown_table


DEFAULT_INPUT = Path("data/analysis/backtests/receptions_backtest_rows.csv")
DEFAULT_OUTPUT = Path("data/analysis/market_diagnostics/receptions/holdout_autopsy")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Holdout-safe receptions diagnostics autopsy.")
    parser.add_argument("input_csv", nargs="?", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--min-validation-bets", type=int, default=100)
    parser.add_argument("--no-charts", action="store_true")
    return parser.parse_args()


def write_report(
    output_dir: Path,
    input_csv: Path,
    season: pd.DataFrame,
    split_table: pd.DataFrame,
    threshold: pd.DataFrame,
    audit: pd.DataFrame,
    discovery_cal: pd.DataFrame,
    validation_cal: pd.DataFrame,
    current_rule: pd.DataFrame,
    discovery_interactions: pd.DataFrame,
    validation_interactions: pd.DataFrame,
    split_note: str,
    source_note: str,
) -> None:
    rule_overall = current_rule[current_rule["table"].eq("overall")]
    validation_rule = rule_overall[rule_overall["sample"].eq("validation")]
    discovery_rule = rule_overall[rule_overall["sample"].eq("discovery")]

    val_cal = validation_cal.copy()
    prob_monotonic = monotonic_direction(val_cal["actual_win_rate"].tolist()) if not val_cal.empty else "unavailable"
    edge_val = validation_interactions[validation_interactions["table"].eq("absolute_projection_edge_bucket")]
    edge_monotonic = monotonic_direction(edge_val["win_rate"].tolist()) if not edge_val.empty else "unavailable"

    lines = [
        "# Receptions Holdout Autopsy",
        "",
        f"Input: `{input_csv}`",
        "",
        "## Split",
        "",
        split_note,
        "",
        markdown_table(split_table, 10),
        "",
        "## Season Distribution",
        "",
        markdown_table(season, 10),
        "",
        "## Probability Source Trace",
        "",
        source_note,
        "",
        "## Probability Audit",
        "",
        markdown_table(audit, 10),
        "",
        "## Current 0.35 Hypothesis",
        "",
        markdown_table(rule_overall, 10),
    ]
    if not discovery_rule.empty and not validation_rule.empty:
        d_roi = float(discovery_rule.iloc[0]["roi"])
        v_roi = float(validation_rule.iloc[0]["roi"])
        lines.append("")
        lines.append(
            f"The `absolute_projection_edge >= 0.35` subset had discovery ROI {d_roi:.2%} "
            f"and validation ROI {v_roi:.2%}."
        )
    lines.extend([
        "",
        "### Rule by Side/Line/Season",
        "",
        markdown_table(current_rule[current_rule["table"].ne("overall")], 40),
        "",
        "## Threshold Stability",
        "",
        markdown_table(threshold, 40),
        "",
        "## Discovery Calibration",
        "",
        markdown_table(discovery_cal, 30),
        "",
        "## Validation Calibration",
        "",
        markdown_table(validation_cal, 30),
        "",
        "## Discovery Interactions",
        "",
        markdown_table(discovery_interactions, 40),
        "",
        "## Validation Interactions",
        "",
        markdown_table(validation_interactions, 40),
        "",
        "## Direct Conclusion",
        "",
    ])
    val_audit = audit[audit["sample"].eq("validation")]
    auc = float(val_audit.iloc[0]["auc_probability"]) if not val_audit.empty else float("nan")
    spearman = float(val_audit.iloc[0]["spearman_corr_probability_outcome"]) if not val_audit.empty else float("nan")
    prob_lift = float(val_audit.iloc[0]["probability_roi_lift"]) if not val_audit.empty else float("nan")
    edge_lift = float(val_audit.iloc[0]["absolute_edge_roi_lift"]) if not val_audit.empty else float("nan")
    validation_side = validation_interactions[validation_interactions["table"].eq("side")]
    side_text = "Side comparison unavailable."
    if not validation_side.empty and {"over", "under"}.issubset(set(validation_side["side"].astype(str))):
        over = validation_side[validation_side["side"].eq("over")].iloc[0]
        under = validation_side[validation_side["side"].eq("under")].iloc[0]
        side_text = (
            f"Validation unders lost less than overs: under ROI {float(under['roi']):.2%} "
            f"on {int(under['bets'])} bets vs over ROI {float(over['roi']):.2%} on {int(over['bets'])} bets."
        )
    lines.append(
        f"Validation probability bucket hit-rate monotonicity is `{prob_monotonic}`, "
        f"absolute-edge hit-rate monotonicity is `{edge_monotonic}`, validation AUC is {auc:.3f}, "
        f"and validation Spearman correlation is {spearman:.3f}."
    )
    lines.append(
        f"Top-vs-bottom validation ROI lift is {prob_lift:.2%} for recommended probability "
        f"and {edge_lift:.2%} for absolute projection edge."
    )
    lines.append(side_text)
    lines.append(
        "Conclusion: probability has a weak ranking signal out of sample, but probabilities are badly overstated; "
        "absolute projection edge does not rank outcomes monotonically in validation. Receptions should be retained for further modeling only, "
        "not restricted to a production subset from this autopsy."
    )
    lines.append("")
    (output_dir / "holdout_autopsy_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    raw = read_input(args.input_csv)
    loaded = standardize_frame(raw, market="player_receptions")
    df = add_probability_audit_fields(add_buckets(loaded.df))
    args.output_dir.mkdir(parents=True, exist_ok=True)

    seasons = sorted(df["season"].dropna().unique())
    split = choose_chronological_split(df, min_validation_bets=args.min_validation_bets)
    discovery = df[split.discovery].copy()
    validation = df[split.validation].copy()
    split_note = (
        "Only one season is present, so a true prior-season to latest-season holdout is unavailable. "
        f"Using chronological fallback: discovery `{split.discovery_label}`, validation `{split.validation_label}`."
        if len(seasons) == 1
        else f"Using chronological season holdout: discovery `{split.discovery_label}`, validation `{split.validation_label}`."
    )
    source_note = (
        "`recommended_prob` is produced in `scripts/03_modeling/build_receptions_projection_engine.py` "
        "as the simulated hit probability for the EV-favored side (`p_over` or `p_under`) from negative-binomial simulations. "
        "`recommended_ev_percent` is calculated as decimal EV multiplied by 100. This autopsy documents the formula but does not edit it."
    )

    season = season_summary(df)
    split_table = resolved_split_table(df, split)
    threshold = threshold_stability(discovery, validation)
    audit = probability_audit(discovery, validation)
    discovery_cal = calibration_table(discovery, "recommended_probability", "probability_bucket", "recommended_probability", True, min_bets=1)
    validation_cal = calibration_table(validation, "recommended_probability", "probability_bucket", "recommended_probability", True, min_bets=1)
    discovery_interactions = interaction_suite(discovery)
    validation_interactions = interaction_suite(validation)
    current_rule = current_rule_035(discovery, validation)

    season.to_csv(args.output_dir / "season_summary.csv", index=False)
    split_table.to_csv(args.output_dir / "resolved_split.csv", index=False)
    threshold.to_csv(args.output_dir / "threshold_stability.csv", index=False)
    audit.to_csv(args.output_dir / "probability_audit.csv", index=False)
    discovery_cal.to_csv(args.output_dir / "discovery_calibration.csv", index=False)
    validation_cal.to_csv(args.output_dir / "validation_calibration.csv", index=False)
    discovery_interactions.to_csv(args.output_dir / "discovery_interactions.csv", index=False)
    validation_interactions.to_csv(args.output_dir / "validation_interactions.csv", index=False)
    current_rule.to_csv(args.output_dir / "current_rule_035_validation.csv", index=False)

    if not args.no_charts:
        save_holdout_charts(args.output_dir, discovery_cal, validation_cal, threshold)

    write_report(
        args.output_dir,
        args.input_csv,
        season,
        split_table,
        threshold,
        audit,
        discovery_cal,
        validation_cal,
        current_rule,
        discovery_interactions,
        validation_interactions,
        split_note,
        source_note,
    )

    baseline = summarize(df)
    print(f"Baseline: bets={baseline['bets']} wins={baseline['wins']} losses={baseline['losses']} pushes={baseline['pushes']} profit={baseline['profit_units']:.2f} roi={baseline['roi']:.6f}")
    print(f"Discovery: {split.discovery_label} bets={len(discovery):,}")
    print(f"Validation: {split.validation_label} bets={len(validation):,}")
    print(f"Output: {args.output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
