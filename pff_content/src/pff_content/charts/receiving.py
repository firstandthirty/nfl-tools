from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from matplotlib.ticker import PercentFormatter

from pff_content.analysis.qualifiers import QUALIFIERS, safe_divide

from .dense_labels import add_dense_point_labels, dense_label_points_from_dataframe, existing_text_bboxes, record_label_stats
from .scatter import LabelPoint, add_average_lines, padded_limits
from .style import DEFAULT_STYLE, add_footer, add_title_block, format_axes, save_png, social_figure


RECEIVING_POSITIONS = {"WR", "TE"}
RECONCILIATION_TOLERANCE = 0.01

RECEIVING_REQUIRED_COLUMNS = {
    "player_name",
    "team",
    "position",
    "routes",
    "targets",
    "receptions",
    "yards",
}

RECEIVING_CHART_COLUMNS = [
    "player_name",
    "team",
    "position",
    "routes",
    "targets",
    "receptions",
    "receiving_yards",
    "targets_per_route_run",
    "yards_per_route_run",
    "yards_per_route_run_derived",
    "yards_per_route_run_discrepancy",
    "average_depth_of_target",
    "rookie",
]


@dataclass(frozen=True)
class ReceivingLabelSelection:
    labels: list[LabelPoint]
    reasons: dict[str, list[str]]


def receiving_position_counts(receiving: pd.DataFrame) -> pd.Series:
    if "position" not in receiving.columns:
        raise ValueError("Receiving data missing column: position")
    return receiving["position"].fillna("<missing>").astype(str).value_counts(dropna=False)


def route_threshold_breakdowns(receiving: pd.DataFrame, thresholds: tuple[int, ...] = (10, 15, 20, 25)) -> dict[int, dict[str, object]]:
    if "routes" not in receiving.columns or "position" not in receiving.columns:
        raise ValueError("Receiving data missing route or position columns")
    df = receiving.copy()
    df["routes"] = pd.to_numeric(df["routes"], errors="coerce")
    out: dict[int, dict[str, object]] = {}
    for threshold in thresholds:
        subset = df[df["routes"].ge(threshold)]
        out[threshold] = {
            "count": int(len(subset)),
            "positions": subset["position"].fillna("<missing>").astype(str).value_counts().to_dict(),
        }
    return out


def receiving_tprr_vs_yprr_dataframe(
    receiving: pd.DataFrame,
    *,
    min_routes: int = QUALIFIERS["receiving_min_routes"],
    positions: set[str] = RECEIVING_POSITIONS,
    tolerance: float = RECONCILIATION_TOLERANCE,
) -> pd.DataFrame:
    missing = RECEIVING_REQUIRED_COLUMNS - set(receiving.columns)
    if missing:
        raise ValueError(f"Receiving chart data missing columns: {sorted(missing)}")

    df = receiving.copy()
    for column in ["routes", "targets", "receptions", "yards"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df["receiving_yards"] = df["yards"]
    df["targets_per_route_run"] = safe_divide(df["targets"], df["routes"])
    df["yards_per_route_run_derived"] = safe_divide(df["receiving_yards"], df["routes"])
    if "yprr" in df.columns:
        df["yards_per_route_run"] = pd.to_numeric(df["yprr"], errors="coerce")
    else:
        df["yards_per_route_run"] = df["yards_per_route_run_derived"]
    df["yards_per_route_run_discrepancy"] = df["yards_per_route_run"] - df["yards_per_route_run_derived"]

    meaningful = df[df["yards_per_route_run_discrepancy"].abs() > tolerance]
    if not meaningful.empty:
        details = meaningful[["player_name", "team", "yards_per_route_run", "yards_per_route_run_derived", "yards_per_route_run_discrepancy"]]
        raise ValueError("Native YPRR does not reconcile to receiving_yards / routes: " + details.to_dict("records").__repr__())

    if "avg_depth_of_target" in df.columns:
        df["average_depth_of_target"] = pd.to_numeric(df["avg_depth_of_target"], errors="coerce")
    elif "average_depth_of_target" not in df.columns:
        df["average_depth_of_target"] = pd.NA

    if "rookie" not in df.columns:
        if "draft_season" in df.columns and "season" in df.columns:
            df["rookie"] = pd.to_numeric(df["draft_season"], errors="coerce").eq(pd.to_numeric(df["season"], errors="coerce"))
        else:
            df["rookie"] = False

    position_mask = df["position"].astype(str).str.upper().isin(positions)
    qualified = df[
        position_mask
        & df["routes"].ge(min_routes)
        & df["targets_per_route_run"].notna()
        & df["yards_per_route_run"].notna()
    ].copy()
    if qualified.empty:
        raise ValueError(f"No qualified receivers found with routes >= {min_routes}.")

    return qualified[RECEIVING_CHART_COLUMNS].sort_values(
        ["targets_per_route_run", "yards_per_route_run", "routes"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def receiving_reference_stats(chart_df: pd.DataFrame) -> dict[str, float]:
    return {
        "mean_tprr": float(chart_df["targets_per_route_run"].mean()),
        "median_tprr": float(chart_df["targets_per_route_run"].median()),
        "mean_yprr": float(chart_df["yards_per_route_run"].mean()),
        "median_yprr": float(chart_df["yards_per_route_run"].median()),
    }


def receiving_quadrant_counts(chart_df: pd.DataFrame, *, x_ref: float, y_ref: float) -> dict[str, int]:
    x = chart_df["targets_per_route_run"]
    y = chart_df["yards_per_route_run"]
    return {
        "upper_right": int(((x > x_ref) & (y > y_ref)).sum()),
        "upper_left": int(((x <= x_ref) & (y > y_ref)).sum()),
        "lower_right": int(((x > x_ref) & (y <= y_ref)).sum()),
        "lower_left": int(((x <= x_ref) & (y <= y_ref)).sum()),
    }


def add_receiving_ranks(chart_df: pd.DataFrame) -> pd.DataFrame:
    out = chart_df.copy()
    out["tprr_rank"] = out["targets_per_route_run"].rank(method="min", ascending=False).astype("Int64")
    out["yprr_rank"] = out["yards_per_route_run"].rank(method="min", ascending=False).astype("Int64")
    out["rank_difference"] = out["tprr_rank"].astype(int) - out["yprr_rank"].astype(int)
    return out


def select_receiving_labels(chart_df: pd.DataFrame, *, max_labels: int = 8) -> ReceivingLabelSelection:
    ranked = add_receiving_ranks(chart_df)
    candidates: list[tuple[int, str]] = []
    candidates.extend((int(index), "top 3 targets per route run") for index in ranked.sort_values("targets_per_route_run", ascending=False).head(3).index)
    candidates.extend((int(index), "top 3 yards per route run") for index in ranked.sort_values("yards_per_route_run", ascending=False).head(3).index)
    candidates.extend((int(index), "TPRR rank much better than YPRR rank") for index in ranked.sort_values("rank_difference", ascending=True).head(3).index)
    candidates.extend((int(index), "YPRR rank much better than TPRR rank") for index in ranked.sort_values("rank_difference", ascending=False).head(3).index)
    candidates.extend((int(index), "bottom 2 targets per route run") for index in ranked.sort_values("targets_per_route_run", ascending=True).head(2).index)
    candidates.extend((int(index), "bottom 2 yards per route run") for index in ranked.sort_values("yards_per_route_run", ascending=True).head(2).index)

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
                x=float(row["targets_per_route_run"]),
                y=float(row["yards_per_route_run"]),
            )
        )
        reasons[player_key] = reasons_by_index[index]
    return ReceivingLabelSelection(labels=labels, reasons=reasons)


def format_tprr_axis(ax) -> None:
    ax.xaxis.set_major_formatter(PercentFormatter(xmax=1.0, decimals=0))


def _add_receiving_quadrants(ax, *, x_ref: float, y_ref: float) -> None:
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()
    labels = [
        ("More targets, more production", (x_ref + x_max) / 2, y_ref + (y_max - y_ref) * 0.88, "center"),
        ("Fewer targets, more production", x_min + (x_ref - x_min) * 0.08, y_ref + (y_max - y_ref) * 0.88, "left"),
        ("More targets, less production", (x_ref + x_max) / 2, y_min + (y_ref - y_min) * 0.10, "center"),
        ("Fewer targets, less production", x_min + (x_ref - x_min) * 0.08, y_min + (y_ref - y_min) * 0.10, "left"),
    ]
    for text, x, y, ha in labels:
        ax.text(x, y, text, color=DEFAULT_STYLE.muted_text, fontsize=9.0, alpha=0.54, ha=ha)



def _add_receiving_labels(ax, points: list[LabelPoint]) -> None:
    custom_offsets = {
        "Dalton Kincaid (BUF)": (-38, -22),
        "Jaxon Smith-Njigba (SEA)": (-4, 22),
        "Parker Washington (JAX)": (-64, -8),
        "Puka Nacua (LA)": (10, 12),
        "Noah Fant (NO)": (10, -18),
        "George Kittle (SF)": (-14, -26),
        "Jayden Reed (GB)": (-34, -34),
        "Mason Taylor (NYJ)": (8, 14),
    }
    fallback_offsets = [(8, 8), (8, -14), (-8, 8), (-8, -14), (12, 0), (-12, 0)]
    for index, point in enumerate(points):
        dx, dy = custom_offsets.get(point.label, fallback_offsets[index % len(fallback_offsets)])
        ax.annotate(
            point.label,
            xy=(point.x, point.y),
            xytext=(dx, dy),
            textcoords="offset points",
            ha="left" if dx >= 0 else "right",
            va="bottom" if dy >= 0 else "top",
            fontsize=9.5,
            fontweight="bold",
            color=DEFAULT_STYLE.text,
            arrowprops={
                "arrowstyle": "-",
                "color": DEFAULT_STYLE.grid,
                "alpha": 0.75,
                "linewidth": 0.8,
                "shrinkA": 0,
                "shrinkB": 4,
            },
        )
def build_receiving_tprr_vs_yprr_chart(
    receiving: pd.DataFrame,
    *,
    output_dir: Path,
    season: int,
    week: int,
    min_routes: int = QUALIFIERS["receiving_min_routes"],
    period_label: str | None = None,
) -> Path:
    label = period_label or f"{season} Week {week}"
    chart_df = receiving_tprr_vs_yprr_dataframe(receiving, min_routes=min_routes)
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_df.to_csv(output_dir / "receiving_tprr_vs_yprr.csv", index=False)

    x_col = "targets_per_route_run"
    y_col = "yards_per_route_run"
    stats = receiving_reference_stats(chart_df)
    x_avg = stats["mean_tprr"]
    y_avg = stats["mean_yprr"]

    fig, ax = social_figure()
    fig.subplots_adjust(left=0.075, right=0.965, top=0.80, bottom=0.15)
    format_axes(ax)

    sizes = (chart_df["routes"].clip(lower=min_routes, upper=45) * 3.8) + 20
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
    ax.set_ylim(*padded_limits(chart_df[y_col], min_pad=0.25))
    add_average_lines(ax, x_avg=x_avg, y_avg=y_avg)
    _add_receiving_quadrants(ax, x_ref=x_avg, y_ref=y_avg)
    format_tprr_axis(ax)

    ax.set_xlabel("Targets per route run")
    ax.set_ylabel("Yards per route run")
    ax.text(
        x_avg,
        ax.get_ylim()[1],
        f" Avg TPRR {x_avg:.1%}",
        color=DEFAULT_STYLE.muted_text,
        fontsize=9.5,
        va="top",
        ha="left",
    )
    ax.text(
        ax.get_xlim()[1],
        y_avg,
        f"Avg YPRR {y_avg:.2f} ",
        color=DEFAULT_STYLE.muted_text,
        fontsize=9.5,
        va="bottom",
        ha="right",
    )

    selection = select_receiving_labels(chart_df, max_labels=8)
    placement = add_dense_point_labels(
        ax,
        dense_label_points_from_dataframe(
            chart_df,
            x_col=x_col,
            y_col=y_col,
            highlight_names=set(selection.reasons),
            volume_col="routes",
        ),
        reserved_bboxes=existing_text_bboxes(ax),
    )
    record_label_stats("receiving_tprr_vs_yprr", placement)

    add_title_block(
        fig,
        title="Target Earners vs. Receiving Production",
        subtitle=f"WR/TE with {min_routes}+ routes | {label}",
    )
    add_footer(fig, text=f"First & Thirty | PFF data | {label}")

    output_path = output_dir / "receiving_tprr_vs_yprr.png"
    save_png(fig, output_path)
    return output_path





