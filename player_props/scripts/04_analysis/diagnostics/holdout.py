from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math

import numpy as np
import pandas as pd

from .calibration import calibration_table
from .metrics import summarize
from .slicing import slice_table


@dataclass(frozen=True)
class Split:
    discovery: pd.Series
    validation: pd.Series
    method: str
    discovery_label: str
    validation_label: str


def decimal_to_american(decimal_odds: float) -> float:
    if pd.isna(decimal_odds) or decimal_odds <= 1:
        return math.nan
    return (decimal_odds - 1.0) * 100.0 if decimal_odds >= 2 else -100.0 / (decimal_odds - 1.0)


def implied_probability_from_american(odds: float) -> float:
    if pd.isna(odds) or odds == 0:
        return math.nan
    return 100.0 / (odds + 100.0) if odds > 0 else abs(odds) / (abs(odds) + 100.0)


def raw_implied_probability_from_decimal(odds: pd.Series) -> pd.Series:
    odds = pd.to_numeric(odds, errors="coerce")
    return 1.0 / odds.where(odds > 1)


def no_vig_side_probability(df: pd.DataFrame) -> pd.Series:
    if not {"over_price", "under_price", "side"}.issubset(df.columns):
        return pd.Series(np.nan, index=df.index, dtype="float64")
    over_raw = raw_implied_probability_from_decimal(df["over_price"])
    under_raw = raw_implied_probability_from_decimal(df["under_price"])
    denom = over_raw + under_raw
    over_no_vig = over_raw / denom
    under_no_vig = under_raw / denom
    return pd.Series(np.where(df["side"].eq("over"), over_no_vig, under_no_vig), index=df.index, dtype="float64")


def add_probability_audit_fields(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["recommended_probability"] = out["predicted_probability"]
    out["raw_implied_probability"] = raw_implied_probability_from_decimal(out["bet_odds_value"])
    out["no_vig_implied_probability"] = no_vig_side_probability(out)
    out["probability_edge_vs_raw_market"] = out["recommended_probability"] - out["raw_implied_probability"]
    out["probability_edge_vs_no_vig_market"] = out["recommended_probability"] - out["no_vig_implied_probability"]
    return out


def choose_chronological_split(df: pd.DataFrame, min_validation_bets: int = 100) -> Split:
    if "season" not in df:
        raise ValueError("season is required for chronological split selection.")
    seasons = sorted(int(x) for x in df["season"].dropna().unique())
    if len(seasons) >= 2:
        latest = seasons[-1]
        validation = df["season"].eq(latest)
        discovery = df["season"].lt(latest)
        if int(validation.sum()) >= min_validation_bets and int(discovery.sum()) >= min_validation_bets:
            return Split(discovery, validation, "season_holdout", f"seasons < {latest}", f"season {latest}")
    if "week" not in df:
        raise ValueError("only one season is present and week is unavailable for fallback chronological split.")
    weeks = sorted(int(x) for x in df["week"].dropna().unique())
    if len(weeks) < 2:
        raise ValueError("not enough chronological periods for holdout analysis.")
    validation_weeks: list[int] = []
    for week in reversed(weeks):
        validation_weeks.insert(0, week)
        if int(df["week"].isin(validation_weeks).sum()) >= min_validation_bets:
            break
    validation = df["week"].isin(validation_weeks)
    discovery = ~validation
    if int(discovery.sum()) == 0 or int(validation.sum()) == 0:
        raise ValueError("chronological split produced an empty discovery or validation sample.")
    return Split(
        discovery,
        validation,
        "single_season_late_week_holdout",
        f"2024 weeks <= {min(validation_weeks) - 1}",
        f"2024 weeks {min(validation_weeks)}-{max(validation_weeks)}",
    )


def season_summary(df: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for season, group in df.groupby("season", observed=True):
        stats = summarize(group)
        row = {"season": season, **stats}
        for side, count in group["side"].value_counts(dropna=False).items():
            row[f"side_{side}_bets"] = int(count)
        for line, count in group["line_value"].value_counts(dropna=False).sort_index().items():
            row[f"line_{line:g}_bets"] = int(count)
        for prefix, col in [
            ("recommended_probability", "recommended_probability"),
            ("absolute_projection_edge", "absolute_projection_edge"),
        ]:
            desc = group[col].describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9])
            for key in ["mean", "std", "min", "10%", "25%", "50%", "75%", "90%", "max"]:
                row[f"{prefix}_{key}"] = float(desc[key])
        rows.append(row)
    return pd.DataFrame(rows)


def resolved_split_table(df: pd.DataFrame, split: Split) -> pd.DataFrame:
    rows = []
    for label, mask in [("discovery", split.discovery), ("validation", split.validation)]:
        part = df[mask]
        stats = summarize(part)
        rows.append({
            "sample": label,
            "method": split.method,
            "label": split.discovery_label if label == "discovery" else split.validation_label,
            "seasons": ", ".join(map(str, sorted(part["season"].dropna().unique()))),
            "weeks": ", ".join(map(str, sorted(part["week"].dropna().unique()))) if "week" in part else "",
            **stats,
        })
    return pd.DataFrame(rows)


SUMMARY_COLUMNS = [
    "bets", "wins", "losses", "pushes", "win_rate", "profit_units", "roi",
    "avg_bet_odds", "avg_recommended_probability", "avg_absolute_projection_edge",
]


def grouped_table(df: pd.DataFrame, dimensions: list[str], table_name: str, min_bets: int = 1) -> pd.DataFrame:
    missing = [d for d in dimensions if d not in df]
    if missing:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    work = df.copy()
    for dim in dimensions:
        work[dim] = work[dim].astype(object).where(work[dim].notna(), "missing")
    for values, group in work.groupby(dimensions, observed=True, dropna=False):
        stats = summarize(group)
        if stats["bets"] < min_bets:
            continue
        values = values if isinstance(values, tuple) else (values,)
        row = {"table": table_name}
        row.update({dim: value for dim, value in zip(dimensions, values)})
        row.update({col: stats.get(col, math.nan) for col in SUMMARY_COLUMNS})
        rows.append(row)
    return pd.DataFrame(rows)


def interaction_suite(df: pd.DataFrame) -> pd.DataFrame:
    specs = [
        ("recommended_probability_bucket", ["probability_bucket"]),
        ("recommended_ev_percent_bucket", ["ev_bucket"]),
        ("absolute_projection_edge_bucket", ["verified_edge_bucket"]),
        ("signed_projection_edge_bucket", ["projection_minus_line_bucket"]),
        ("line_bucket", ["line_bucket"]),
        ("side", ["side"]),
        ("side_x_line_bucket", ["side", "line_bucket"]),
        ("side_x_absolute_projection_edge_bucket", ["side", "verified_edge_bucket"]),
        ("side_x_recommended_probability_bucket", ["side", "probability_bucket"]),
        ("line_bucket_x_absolute_projection_edge_bucket", ["line_bucket", "verified_edge_bucket"]),
    ]
    tables = [grouped_table(df, dims, name) for name, dims in specs]
    tables = [t for t in tables if not t.empty]
    return pd.concat(tables, ignore_index=True, sort=False) if tables else pd.DataFrame()


def threshold_stability(discovery: pd.DataFrame, validation: pd.DataFrame) -> pd.DataFrame:
    grids = {
        "absolute_projection_edge": [0.25, 0.35, 0.50, 0.75, 1.00],
        "recommended_ev_percent_value": [2.0, 3.0, 5.0, 7.5],
        "recommended_probability": [0.50, 0.525, 0.55, 0.575, 0.60, 0.625, 0.65],
    }
    rows: list[dict[str, object]] = []
    baseline_d = summarize(discovery)
    baseline_v = summarize(validation)
    for col, thresholds in grids.items():
        if col not in discovery or col not in validation:
            continue
        for threshold in thresholds:
            d = discovery[discovery[col].ge(threshold)]
            v = validation[validation[col].ge(threshold)]
            if d.empty or v.empty:
                continue
            ds = summarize(d)
            vs = summarize(v)
            roi_agree = np.sign(ds["roi"] - baseline_d["roi"]) == np.sign(vs["roi"] - baseline_v["roi"])
            hit_agree = np.sign(ds["win_rate"] - baseline_d["win_rate"]) == np.sign(vs["win_rate"] - baseline_v["win_rate"])
            if ds["bets"] < 50 or vs["bets"] < 30:
                evidence = "insufficient sample"
            elif roi_agree and hit_agree and vs["roi"] > baseline_v["roi"] and vs["roi"] > 0:
                evidence = "hypothesis worth holdout testing"
            elif roi_agree and hit_agree and vs["roi"] > baseline_v["roi"]:
                evidence = "weak holdout-consistent loss reduction"
            elif roi_agree or hit_agree:
                evidence = "weak exploratory signal"
            else:
                evidence = "does not generalize"
            rows.append({
                "signal": col,
                "rule": f"{col} >= {threshold:g}",
                "threshold": threshold,
                "discovery_bets": ds["bets"],
                "discovery_roi": ds["roi"],
                "discovery_profit_units": ds["profit_units"],
                "validation_bets": vs["bets"],
                "validation_roi": vs["roi"],
                "validation_profit_units": vs["profit_units"],
                "discovery_retention_pct": ds["bets"] / baseline_d["bets"],
                "validation_retention_pct": vs["bets"] / baseline_v["bets"],
                "roi_direction_agrees": bool(roi_agree),
                "hit_rate_direction_agrees": bool(hit_agree),
                "evidence_class": evidence,
            })
    return pd.DataFrame(rows)


def auc_score(y_true: pd.Series, score: pd.Series) -> float:
    valid = pd.DataFrame({"y": y_true.astype(float), "score": score}).dropna()
    if valid["y"].nunique() < 2:
        return math.nan
    ranks = valid["score"].rank(method="average")
    n_pos = float(valid["y"].sum())
    n_neg = float(len(valid) - n_pos)
    rank_sum_pos = float(ranks[valid["y"].eq(1)].sum())
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg)


def ece_by_bucket(df: pd.DataFrame, prob_col: str = "recommended_probability", bucket_col: str = "probability_bucket") -> float:
    valid = df[df[prob_col].between(0, 1, inclusive="both") & ~df["pushed"] & df[bucket_col].notna()]
    if valid.empty:
        return math.nan
    total = len(valid)
    ece = 0.0
    for _, group in valid.groupby(bucket_col, observed=True):
        ece += len(group) / total * abs(float(group[prob_col].mean()) - float(group["won"].mean()))
    return float(ece)


def probability_audit(discovery: pd.DataFrame, validation: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for sample, frame in [("discovery", discovery), ("validation", validation)]:
        valid = frame[~frame["pushed"]].copy()
        y = valid["won"].astype(float)
        p = valid["recommended_probability"]
        row = {
            "sample": sample,
            "bets": len(frame),
            "mean_recommended_probability": float(p.mean()),
            "actual_win_rate": float(y.mean()) if len(y) else math.nan,
            "calibration_error": float(p.mean() - y.mean()) if len(y) else math.nan,
            "brier_score": float(((p - y) ** 2).mean()) if len(y) else math.nan,
            "expected_calibration_error": ece_by_bucket(valid),
            "pearson_corr_probability_outcome": float(p.corr(y, method="pearson")) if y.nunique() > 1 else math.nan,
            "spearman_corr_probability_outcome": float(p.corr(y, method="spearman")) if y.nunique() > 1 else math.nan,
            "auc_probability": auc_score(y, p),
            "mean_raw_implied_probability": float(valid["raw_implied_probability"].mean()),
            "mean_no_vig_implied_probability": float(valid["no_vig_implied_probability"].mean()),
            "mean_probability_edge_vs_raw_market": float(valid["probability_edge_vs_raw_market"].mean()),
            "mean_probability_edge_vs_no_vig_market": float(valid["probability_edge_vs_no_vig_market"].mean()),
        }
        for label, col in [
            ("probability", "recommended_probability"),
            ("absolute_edge", "absolute_projection_edge"),
        ]:
            lift = quantile_lift(valid, col)
            for key, value in lift.items():
                row[f"{label}_{key}"] = value
        rows.append(row)
    return pd.DataFrame(rows)


def monotonic_direction(values: list[float]) -> str:
    clean = [v for v in values if not pd.isna(v)]
    if len(clean) < 3:
        return "insufficient buckets"
    diffs = np.diff(clean)
    if np.all(diffs >= 0):
        return "increasing"
    if np.all(diffs <= 0):
        return "decreasing"
    return "not monotonic"


def quantile_lift(frame: pd.DataFrame, col: str, q: float = 0.25) -> dict[str, float]:
    valid = frame[frame[col].notna()]
    if valid.empty:
        return {"bottom_roi": math.nan, "top_roi": math.nan, "roi_lift": math.nan, "bottom_hit_rate": math.nan, "top_hit_rate": math.nan}
    low_cut = valid[col].quantile(q)
    high_cut = valid[col].quantile(1 - q)
    bottom = summarize(valid[valid[col].le(low_cut)])
    top = summarize(valid[valid[col].ge(high_cut)])
    return {
        "bottom_roi": bottom["roi"],
        "top_roi": top["roi"],
        "roi_lift": top["roi"] - bottom["roi"],
        "bottom_hit_rate": bottom["win_rate"],
        "top_hit_rate": top["win_rate"],
    }


def current_rule_035(discovery: pd.DataFrame, validation: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for sample, frame in [("discovery", discovery), ("validation", validation)]:
        kept = frame[frame["absolute_projection_edge"].ge(0.35)]
        for table, dims in [
            ("overall", []),
            ("side", ["side"]),
            ("line_bucket", ["line_bucket"]),
            ("season", ["season"]),
        ]:
            if dims:
                part = grouped_table(kept, dims, table)
                if not part.empty:
                    part.insert(0, "sample", sample)
                    rows.extend(part.to_dict("records"))
            else:
                rows.append({"sample": sample, "table": table, "rule": "absolute_projection_edge >= 0.35", **summarize(kept)})
    return pd.DataFrame(rows)


def save_holdout_charts(output_dir: Path, discovery_cal: pd.DataFrame, validation_cal: pd.DataFrame, threshold: pd.DataFrame) -> list[str]:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return ["matplotlib is not installed; holdout charts skipped."]
    chart_dir = output_dir / "charts"
    chart_dir.mkdir(parents=True, exist_ok=True)
    if not discovery_cal.empty and not validation_cal.empty:
        fig, ax = plt.subplots(figsize=(10, 5))
        for label, table in [("discovery", discovery_cal), ("validation", validation_cal)]:
            ax.plot(table["bucket"].astype(str), table["actual_win_rate"], marker="o", label=label)
        ax.tick_params(axis="x", rotation=45)
        ax.set_ylabel("Hit rate")
        ax.set_title("Probability Bucket Hit Rate by Sample")
        ax.legend()
        fig.tight_layout()
        fig.savefig(chart_dir / "probability_bucket_hit_rate.png", dpi=150)
        plt.close(fig)
    if not threshold.empty:
        edge = threshold[threshold["signal"].eq("absolute_projection_edge")]
        if not edge.empty:
            fig, ax = plt.subplots(figsize=(8, 5))
            ax.plot(edge["threshold"], edge["discovery_roi"], marker="o", label="discovery")
            ax.plot(edge["threshold"], edge["validation_roi"], marker="o", label="validation")
            ax.axhline(0, linewidth=1)
            ax.set_xlabel("Minimum absolute projection edge")
            ax.set_ylabel("ROI")
            ax.set_title("Threshold Stability")
            ax.legend()
            fig.tight_layout()
            fig.savefig(chart_dir / "absolute_edge_threshold_stability.png", dpi=150)
            plt.close(fig)
    return []
