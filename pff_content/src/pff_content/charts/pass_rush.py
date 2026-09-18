from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from matplotlib.ticker import PercentFormatter

from pff_content.analysis.qualifiers import QUALIFIERS, safe_divide

from .dense_labels import add_dense_point_labels, dense_label_points_from_dataframe, existing_text_bboxes, record_label_stats
from .scatter import LabelPoint, add_average_lines, padded_limits
from .style import DEFAULT_STYLE, add_footer, add_title_block, format_axes, save_png, social_figure


PASS_RUSH_REQUIRED_COLUMNS = {
    "player_name",
    "team",
    "position",
    "pass_rush_snaps",
    "total_pressures",
    "sacks",
    "hits",
    "hurries",
    "pass_rush_wins",
    "pass_rush_win_rate",
    "pass_rush_productivity",
}

PASS_RUSH_CHART_COLUMNS = [
    "player_name",
    "team",
    "position",
    "pass_rush_snaps",
    "pressures",
    "sacks",
    "hits",
    "hurries",
    "pass_rush_wins",
    "pass_rush_win_rate",
    "pass_rush_win_rate_derived",
    "pass_rush_win_rate_discrepancy",
    "pressure_rate",
    "pressure_rate_native",
    "pressure_rate_discrepancy",
    "prp",
    "rookie",
    "true_pass_set_pass_rush_snaps",
    "true_pass_set_pressures",
    "true_pass_set_pass_rush_wins",
    "true_pass_set_pass_rush_win_rate",
    "true_pass_set_prp",
]

WIN_RATE_RECONCILIATION_TOLERANCE = 0.001
PRESSURE_RATE_RECONCILIATION_TOLERANCE = 1e-9


@dataclass(frozen=True)
class PassRushLabelSelection:
    labels: list[LabelPoint]
    reasons: dict[str, list[str]]


def pass_rush_position_counts(pass_rush: pd.DataFrame) -> pd.Series:
    if "position" not in pass_rush.columns:
        raise ValueError("Pass-rush data missing column: position")
    return pass_rush["position"].fillna("<missing>").astype(str).value_counts(dropna=False)


def pass_rush_threshold_breakdowns(pass_rush: pd.DataFrame, thresholds: tuple[int, ...] = (10, 15, 20, 25)) -> dict[int, dict[str, object]]:
    if "pass_rush_snaps" not in pass_rush.columns or "position" not in pass_rush.columns:
        raise ValueError("Pass-rush data missing pass_rush_snaps or position columns")
    df = pass_rush.copy()
    df["pass_rush_snaps"] = pd.to_numeric(df["pass_rush_snaps"], errors="coerce")
    out: dict[int, dict[str, object]] = {}
    for threshold in thresholds:
        subset = df[df["pass_rush_snaps"].ge(threshold)]
        out[threshold] = {
            "count": int(len(subset)),
            "positions": subset["position"].fillna("<missing>").astype(str).value_counts().to_dict(),
        }
    return out


def pass_rush_win_rate_vs_pressure_rate_dataframe(
    pass_rush: pd.DataFrame,
    *,
    min_pass_rush_snaps: int = QUALIFIERS["pass_rush_min_snaps"],
    win_tolerance: float = WIN_RATE_RECONCILIATION_TOLERANCE,
    pressure_tolerance: float = PRESSURE_RATE_RECONCILIATION_TOLERANCE,
) -> pd.DataFrame:
    missing = PASS_RUSH_REQUIRED_COLUMNS - set(pass_rush.columns)
    if missing:
        raise ValueError(f"Pass-rush chart data missing columns: {sorted(missing)}")

    df = pass_rush.copy()
    numeric_cols = [
        "pass_rush_snaps",
        "total_pressures",
        "sacks",
        "hits",
        "hurries",
        "pass_rush_wins",
        "pass_rush_win_rate",
        "pass_rush_productivity",
    ]
    for column in numeric_cols:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["pressures"] = df["total_pressures"]
    df["pass_rush_win_rate"] = df["pass_rush_win_rate"] / 100.0
    if "pass_rush_opp" in df.columns:
        df["pass_rush_opp"] = pd.to_numeric(df["pass_rush_opp"], errors="coerce")
        df["pass_rush_win_rate_derived"] = safe_divide(df["pass_rush_wins"], df["pass_rush_opp"])
    else:
        df["pass_rush_win_rate_derived"] = pd.NA
    df["pass_rush_win_rate_discrepancy"] = df["pass_rush_win_rate"] - df["pass_rush_win_rate_derived"]

    meaningful_win = df[df["pass_rush_win_rate_discrepancy"].abs() > win_tolerance]
    if not meaningful_win.empty:
        details = meaningful_win[["player_name", "team", "pass_rush_win_rate", "pass_rush_win_rate_derived", "pass_rush_win_rate_discrepancy"]]
        raise ValueError("Native pass-rush win rate does not reconcile to wins / opportunities: " + details.to_dict("records").__repr__())

    df["pressure_rate"] = safe_divide(df["pressures"], df["pass_rush_snaps"])
    if "pressure_rate" in pass_rush.columns:
        df["pressure_rate_native"] = pd.to_numeric(pass_rush["pressure_rate"], errors="coerce")
        df["pressure_rate_discrepancy"] = df["pressure_rate_native"] - df["pressure_rate"]
        meaningful_pressure = df[df["pressure_rate_discrepancy"].abs() > pressure_tolerance]
        if not meaningful_pressure.empty:
            details = meaningful_pressure[["player_name", "team", "pressure_rate_native", "pressure_rate", "pressure_rate_discrepancy"]]
            raise ValueError("Native pressure rate does not reconcile to pressures / pass-rush snaps: " + details.to_dict("records").__repr__())
    else:
        df["pressure_rate_native"] = pd.NA
        df["pressure_rate_discrepancy"] = pd.NA

    df["prp"] = df["pass_rush_productivity"]
    if "rookie" not in df.columns:
        if "draft_season" in df.columns and "season" in df.columns:
            df["rookie"] = pd.to_numeric(df["draft_season"], errors="coerce").eq(pd.to_numeric(df["season"], errors="coerce"))
        else:
            df["rookie"] = False

    true_mapping = {
        "true_pass_set_snap_counts_pass_rush": "true_pass_set_pass_rush_snaps",
        "true_pass_set_total_pressures": "true_pass_set_pressures",
        "true_pass_set_pass_rush_wins": "true_pass_set_pass_rush_wins",
        "true_pass_set_pass_rush_win_rate": "true_pass_set_pass_rush_win_rate",
        "true_pass_set_prp": "true_pass_set_prp",
    }
    for source, target in true_mapping.items():
        if source in df.columns:
            df[target] = pd.to_numeric(df[source], errors="coerce")
            if target == "true_pass_set_pass_rush_win_rate":
                df[target] = df[target] / 100.0
        else:
            df[target] = pd.NA

    qualified = df[
        df["pass_rush_snaps"].ge(min_pass_rush_snaps)
        & df["pass_rush_win_rate"].notna()
        & df["pressure_rate"].notna()
    ].copy()
    if qualified.empty:
        raise ValueError(f"No qualified pass rushers found with pass-rush snaps >= {min_pass_rush_snaps}.")

    return qualified[PASS_RUSH_CHART_COLUMNS].sort_values(
        ["pass_rush_win_rate", "pressure_rate", "pressures"], ascending=[False, False, False]
    ).reset_index(drop=True)


def pass_rush_reference_stats(chart_df: pd.DataFrame) -> dict[str, float]:
    return {
        "mean_win_rate": float(chart_df["pass_rush_win_rate"].mean()),
        "median_win_rate": float(chart_df["pass_rush_win_rate"].median()),
        "mean_pressure_rate": float(chart_df["pressure_rate"].mean()),
        "median_pressure_rate": float(chart_df["pressure_rate"].median()),
    }


def pass_rush_quadrant_counts(chart_df: pd.DataFrame, *, x_ref: float, y_ref: float) -> dict[str, int]:
    x = chart_df["pass_rush_win_rate"]
    y = chart_df["pressure_rate"]
    return {
        "upper_right": int(((x > x_ref) & (y > y_ref)).sum()),
        "upper_left": int(((x <= x_ref) & (y > y_ref)).sum()),
        "lower_right": int(((x > x_ref) & (y <= y_ref)).sum()),
        "lower_left": int(((x <= x_ref) & (y <= y_ref)).sum()),
    }


def add_pass_rush_ranks(chart_df: pd.DataFrame) -> pd.DataFrame:
    out = chart_df.copy()
    out["win_rate_rank"] = out["pass_rush_win_rate"].rank(method="min", ascending=False).astype("Int64")
    out["pressure_rate_rank"] = out["pressure_rate"].rank(method="min", ascending=False).astype("Int64")
    out["rank_difference"] = out["win_rate_rank"].astype(int) - out["pressure_rate_rank"].astype(int)
    return out


def select_pass_rush_labels(chart_df: pd.DataFrame, *, max_labels: int = 8) -> PassRushLabelSelection:
    ranked = add_pass_rush_ranks(chart_df)
    top_win = set(ranked.sort_values("pass_rush_win_rate", ascending=False).head(3).index)
    top_pressure_rate = set(ranked.sort_values("pressure_rate", ascending=False).head(3).index)
    candidates: list[tuple[int, str]] = []
    candidates.extend((int(index), "top 3 in both win rate and pressure rate") for index in ranked.index if index in top_win & top_pressure_rate)
    candidates.extend((int(index), "top 3 pass-rush win rate") for index in ranked.sort_values("pass_rush_win_rate", ascending=False).head(3).index)
    candidates.extend((int(index), "top 3 pressure rate") for index in ranked.sort_values("pressure_rate", ascending=False).head(3).index)
    candidates.extend((int(index), "win-rate rank much better than pressure-rate rank") for index in ranked.sort_values("rank_difference", ascending=True).head(3).index)
    candidates.extend((int(index), "pressure-rate rank much better than win-rate rank") for index in ranked.sort_values("rank_difference", ascending=False).head(3).index)
    candidates.extend((int(index), "top 3 raw pressures") for index in ranked.sort_values(["pressures", "pressure_rate"], ascending=[False, False]).head(3).index)

    reasons_by_index: dict[int, list[str]] = {}
    ordered_indexes: list[int] = []
    for index, reason in candidates:
        reasons_by_index.setdefault(index, []).append(reason)
        if index not in ordered_indexes:
            ordered_indexes.append(index)

    selected_indexes = ordered_indexes[:max_labels]
    labels: list[LabelPoint] = []
    reasons: dict[str, list[str]] = {}
    for index in selected_indexes:
        row = ranked.loc[index]
        player_key = str(row["player_name"])
        labels.append(
            LabelPoint(
                label=f"{row.player_name} ({row.team})",
                x=float(row["pass_rush_win_rate"]),
                y=float(row["pressure_rate"]),
            )
        )
        reasons[player_key] = reasons_by_index[index]
    return PassRushLabelSelection(labels=labels, reasons=reasons)


def format_rate_axes(ax) -> None:
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=1.0, decimals=0))
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1.0, decimals=0))


def _add_pass_rush_quadrants(ax, *, x_ref: float, y_ref: float) -> None:
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()
    labels = [
        ("More wins, more pressure", (x_ref + x_max) / 2, y_ref + (y_max - y_ref) * 0.88, "center"),
        ("Fewer wins, more pressure", x_min + (x_ref - x_min) * 0.08, y_ref + (y_max - y_ref) * 0.88, "left"),
        ("More wins, less pressure", (x_ref + x_max) / 2, y_min + (y_ref - y_min) * 0.10, "center"),
        ("Fewer wins, less pressure", x_min + (x_ref - x_min) * 0.08, y_min + (y_ref - y_min) * 0.10, "left"),
    ]
    for text, x, y, ha in labels:
        ax.text(x, y, text, color=DEFAULT_STYLE.muted_text, fontsize=9.0, alpha=0.54, ha=ha)


def build_pass_rush_win_rate_vs_pressure_rate_chart(
    pass_rush: pd.DataFrame,
    *,
    output_dir: Path,
    season: int,
    week: int,
    min_pass_rush_snaps: int = QUALIFIERS["pass_rush_min_snaps"],
    period_label: str | None = None,
) -> Path:
    label = period_label or f"{season} Week {week}"
    chart_df = pass_rush_win_rate_vs_pressure_rate_dataframe(pass_rush, min_pass_rush_snaps=min_pass_rush_snaps)
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_df.to_csv(output_dir / "pass_rush_win_rate_vs_pressure_rate.csv", index=False)

    x_col = "pass_rush_win_rate"
    y_col = "pressure_rate"
    stats = pass_rush_reference_stats(chart_df)
    x_avg = stats["mean_win_rate"]
    y_avg = stats["mean_pressure_rate"]

    fig, ax = social_figure()
    fig.subplots_adjust(left=0.075, right=0.965, top=0.80, bottom=0.15)
    format_axes(ax)

    sizes = (chart_df["pass_rush_snaps"].clip(lower=min_pass_rush_snaps, upper=55) * 3.5) + 22
    ax.scatter(
        chart_df[x_col],
        chart_df[y_col],
        s=sizes,
        c=DEFAULT_STYLE.accent,
        alpha=0.82,
        edgecolors=DEFAULT_STYLE.point_edge,
        linewidths=0.45,
    )

    ax.set_xlim(*padded_limits(chart_df[x_col], min_pad=0.025))
    ax.set_ylim(*padded_limits(chart_df[y_col], min_pad=0.025))
    add_average_lines(ax, x_avg=x_avg, y_avg=y_avg)
    _add_pass_rush_quadrants(ax, x_ref=x_avg, y_ref=y_avg)
    format_rate_axes(ax)

    ax.set_xlabel("Pass-Rush Win Rate")
    ax.set_ylabel("Pressure Rate")
    ax.text(
        x_avg,
        ax.get_ylim()[1],
        f" Avg win rate {x_avg:.1%}",
        color=DEFAULT_STYLE.muted_text,
        fontsize=9.5,
        va="top",
        ha="left",
    )
    ax.text(
        ax.get_xlim()[1],
        y_avg,
        f"Avg pressure rate {y_avg:.1%} ",
        color=DEFAULT_STYLE.muted_text,
        fontsize=9.5,
        va="bottom",
        ha="right",
    )

    selection = select_pass_rush_labels(chart_df, max_labels=8)
    placement = add_dense_point_labels(
        ax,
        dense_label_points_from_dataframe(
            chart_df,
            x_col=x_col,
            y_col=y_col,
            highlight_names=set(selection.reasons),
            volume_col="pass_rush_snaps",
        ),
        reserved_bboxes=existing_text_bboxes(ax),
    )
    record_label_stats("pass_rush_win_rate_vs_pressure_rate", placement)

    add_title_block(
        fig,
        title="Pass Rush: Winning vs. Creating Pressure",
        subtitle=f"Defenders with {min_pass_rush_snaps}+ pass-rush snaps | {label}",
    )
    add_footer(fig, text=f"First & Thirty | PFF data | {label}")

    output_path = output_dir / "pass_rush_win_rate_vs_pressure_rate.png"
    save_png(fig, output_path)
    return output_path

