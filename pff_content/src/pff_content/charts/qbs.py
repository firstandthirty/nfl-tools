from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle
from matplotlib.ticker import PercentFormatter

from pff_content.analysis.qualifiers import QUALIFIERS, safe_divide

from .dense_labels import add_dense_point_labels, dense_label_points_from_dataframe, existing_text_bboxes, record_label_stats
from .scatter import add_average_lines, padded_limits
from .style import DEFAULT_STYLE, add_footer, add_title_block, format_axes, save_png, social_figure


QB_CHART_COLUMNS = [
    "player_name",
    "team",
    "opponent",
    "dropbacks",
    "attempts",
    "def_gen_pressures",
    "pressure_rate_faced",
    "avg_time_to_throw",
    "sacks",
    "turnover_worthy_plays",
    "twp_per_dropback",
    "interceptions",
    "twp_minus_int",
    "pressure_rate_rank",
    "fast_ttt_rank",
    "slow_ttt_rank",
    "highlight_reasons",
]


@dataclass(frozen=True)
class QbPressureTttStats:
    qualified_count: int
    mean_time_to_throw: float
    mean_pressure_rate: float
    quadrant_counts: dict[str, int]
    highlight_reasons: dict[str, list[str]]


def qb_pressure_rate_vs_time_to_throw_dataframe(qbs: pd.DataFrame, *, min_dropbacks: int = QUALIFIERS["qb_min_dropbacks"]) -> pd.DataFrame:
    required = {"player_name", "team", "dropbacks", "pressure_rate_faced", "avg_time_to_throw"}
    missing = required - set(qbs.columns)
    if missing:
        raise ValueError(f"QB pressure/TTT chart data missing columns: {sorted(missing)}")
    df = qbs.copy()
    for col in ["dropbacks", "attempts", "def_gen_pressures", "pressure_rate_faced", "avg_time_to_throw", "sacks", "turnover_worthy_plays", "interceptions", "twp_per_dropback"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "twp_per_dropback" not in df.columns and {"turnover_worthy_plays", "dropbacks"}.issubset(df.columns):
        df["twp_per_dropback"] = safe_divide(df["turnover_worthy_plays"], df["dropbacks"])
    if "twp_minus_int" not in df.columns and {"turnover_worthy_plays", "interceptions"}.issubset(df.columns):
        df["twp_minus_int"] = df["turnover_worthy_plays"] - df["interceptions"]
    qualified = df[df["dropbacks"].ge(min_dropbacks) & df["pressure_rate_faced"].notna() & df["avg_time_to_throw"].notna()].copy()
    qualified["pressure_rate_rank"] = qualified["pressure_rate_faced"].rank(method="first", ascending=False).astype(int)
    qualified["fast_ttt_rank"] = qualified["avg_time_to_throw"].rank(method="first", ascending=True).astype(int)
    qualified["slow_ttt_rank"] = qualified["avg_time_to_throw"].rank(method="first", ascending=False).astype(int)
    reasons = select_qb_pressure_ttt_highlights(qualified)
    qualified["highlight_reasons"] = qualified["player_name"].map(lambda name: "; ".join(reasons.get(str(name), [])))
    cols = [col for col in QB_CHART_COLUMNS if col in qualified.columns]
    return qualified.sort_values(["pressure_rate_faced", "avg_time_to_throw", "player_name"], ascending=[False, True, True], kind="mergesort")[cols].reset_index(drop=True)


def select_qb_pressure_ttt_highlights(df: pd.DataFrame) -> dict[str, list[str]]:
    reasons: dict[str, list[str]] = {}
    picks: list[tuple[pd.Index, str]] = [
        (df.sort_values("pressure_rate_faced", ascending=False).head(3).index, "top 3 pressure rate faced"),
        (df.sort_values("avg_time_to_throw", ascending=True).head(3).index, "top 3 fastest average time to throw"),
        (df.sort_values("avg_time_to_throw", ascending=False).head(3).index, "top 3 slowest average time to throw"),
    ]
    pressure_mean = df["pressure_rate_faced"].mean()
    ttt_mean = df["avg_time_to_throw"].mean()
    pressure_std = max(float(df["pressure_rate_faced"].std(ddof=0)), 0.01)
    ttt_std = max(float(df["avg_time_to_throw"].std(ddof=0)), 0.01)
    extremes = df.assign(
        centered_distance=((df["pressure_rate_faced"] - pressure_mean).abs() / pressure_std)
        + ((df["avg_time_to_throw"] - ttt_mean).abs() / ttt_std)
    ).sort_values("centered_distance", ascending=False).head(4)
    picks.append((extremes.index, "largest combined distance from qualified averages"))
    for indexes, reason in picks:
        for index in indexes:
            name = str(df.loc[index, "player_name"])
            reasons.setdefault(name, [])
            if reason not in reasons[name]:
                reasons[name].append(reason)
    return reasons


def qb_pressure_ttt_stats(df: pd.DataFrame) -> QbPressureTttStats:
    x_ref = float(df["avg_time_to_throw"].mean())
    y_ref = float(df["pressure_rate_faced"].mean())
    x = df["avg_time_to_throw"]
    y = df["pressure_rate_faced"]
    return QbPressureTttStats(
        qualified_count=int(len(df)),
        mean_time_to_throw=x_ref,
        mean_pressure_rate=y_ref,
        quadrant_counts={
            "slower_ttt_higher_pressure": int(((x > x_ref) & (y > y_ref)).sum()),
            "faster_ttt_higher_pressure": int(((x <= x_ref) & (y > y_ref)).sum()),
            "slower_ttt_lower_pressure": int(((x > x_ref) & (y <= y_ref)).sum()),
            "faster_ttt_lower_pressure": int(((x <= x_ref) & (y <= y_ref)).sum()),
        },
        highlight_reasons={str(row.player_name): str(row.highlight_reasons).split("; ") for _, row in df[df["highlight_reasons"].astype(str).ne("")].iterrows()},
    )


def _add_qb_quadrants(ax, *, x_ref: float, y_ref: float) -> None:
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()
    labels = [
        ("Slower TTT / Higher Pressure", x_ref + (x_max - x_ref) * 0.08, y_ref + (y_max - y_ref) * 0.88, "left"),
        ("Faster TTT / Higher Pressure", x_min + (x_ref - x_min) * 0.08, y_ref + (y_max - y_ref) * 0.88, "left"),
        ("Slower TTT / Lower Pressure", x_ref + (x_max - x_ref) * 0.08, y_min + (y_ref - y_min) * 0.10, "left"),
        ("Faster TTT / Lower Pressure", x_min + (x_ref - x_min) * 0.08, y_min + (y_ref - y_min) * 0.10, "left"),
    ]
    for text, x, y, ha in labels:
        ax.text(x, y, text, color=DEFAULT_STYLE.muted_text, fontsize=8.8, alpha=0.55, ha=ha)


def build_qb_pressure_rate_vs_time_to_throw_chart(qbs: pd.DataFrame, *, output_dir: Path, season: int, week: int, min_dropbacks: int = QUALIFIERS["qb_min_dropbacks"], period_label: str | None = None) -> Path:
    label = period_label or f"{season} Week {week}"
    chart_df = qb_pressure_rate_vs_time_to_throw_dataframe(qbs, min_dropbacks=min_dropbacks)
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_df.to_csv(output_dir / "qb_pressure_rate_vs_time_to_throw.csv", index=False)

    fig, ax = social_figure()
    fig.subplots_adjust(left=0.075, right=0.965, top=0.80, bottom=0.15)
    format_axes(ax)
    ax.scatter(
        chart_df["avg_time_to_throw"],
        chart_df["pressure_rate_faced"],
        s=(chart_df["dropbacks"].clip(lower=min_dropbacks, upper=60) * 3.2) + 22,
        c=DEFAULT_STYLE.accent,
        alpha=0.82,
        edgecolors=DEFAULT_STYLE.point_edge,
        linewidths=0.45,
    )
    x_avg = chart_df["avg_time_to_throw"].mean()
    y_avg = chart_df["pressure_rate_faced"].mean()
    ax.set_xlim(*padded_limits(chart_df["avg_time_to_throw"], min_pad=0.08))
    ax.set_ylim(*padded_limits(chart_df["pressure_rate_faced"], min_pad=0.035))
    add_average_lines(ax, x_avg=float(x_avg), y_avg=float(y_avg))
    _add_qb_quadrants(ax, x_ref=float(x_avg), y_ref=float(y_avg))
    ax.yaxis.set_major_formatter(PercentFormatter(xmax=1.0, decimals=0))
    ax.set_xlabel("Average time to throw (seconds)")
    ax.set_ylabel("Pressure Rate Faced")
    ax.text(x_avg, ax.get_ylim()[1], f" Avg TTT {x_avg:.2f}s", color=DEFAULT_STYLE.muted_text, fontsize=9.5, va="top", ha="left")
    ax.text(ax.get_xlim()[1], y_avg, f"Avg pressure {y_avg:.1%} ", color=DEFAULT_STYLE.muted_text, fontsize=9.5, va="bottom", ha="right")
    highlights = {name for name, reasons in qb_pressure_ttt_stats(chart_df).highlight_reasons.items() if reasons}
    placement = add_dense_point_labels(
        ax,
        dense_label_points_from_dataframe(chart_df, x_col="avg_time_to_throw", y_col="pressure_rate_faced", highlight_names=highlights, volume_col="dropbacks"),
        include_standard_team=False,
        max_standard_labels=None,
        reserved_bboxes=existing_text_bboxes(ax),
    )
    record_label_stats("qb_pressure_rate_vs_time_to_throw", placement)
    add_title_block(fig, title="QB Pressure Rate Faced vs. Time to Throw", subtitle=f"QBs with {min_dropbacks}+ dropbacks | {label}")
    add_footer(fig, text=f"First & Thirty | PFF data | {label}")
    output_path = output_dir / "qb_pressure_rate_vs_time_to_throw.png"
    save_png(fig, output_path)
    return output_path


def qb_twp_vs_interceptions_dataframe(qbs: pd.DataFrame, *, min_dropbacks: int = QUALIFIERS["qb_min_dropbacks"]) -> pd.DataFrame:
    required = {"player_name", "team", "dropbacks", "turnover_worthy_plays", "interceptions"}
    missing = required - set(qbs.columns)
    if missing:
        raise ValueError(f"QB TWP/INT data missing columns: {sorted(missing)}")
    df = qbs.copy()
    for col in ["dropbacks", "attempts", "turnover_worthy_plays", "interceptions"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df[df["dropbacks"].ge(min_dropbacks)].copy()
    df["twp_rate"] = safe_divide(df["turnover_worthy_plays"], df["dropbacks"])
    df["twp_minus_int"] = df["turnover_worthy_plays"] - df["interceptions"]
    df["abs_twp_minus_int"] = df["twp_minus_int"].abs()
    df = df.sort_values(["abs_twp_minus_int", "dropbacks", "player_name"], ascending=[False, False, True], kind="mergesort").reset_index(drop=True)
    cols = ["player_name", "team", "opponent", "dropbacks", "attempts", "turnover_worthy_plays", "twp_rate", "interceptions", "twp_minus_int", "abs_twp_minus_int"]
    return df[[col for col in cols if col in df.columns]]


def _fit_name_size(text: str) -> float:
    return max(9.8, 13.2 - max(len(text) - 24, 0) * 0.22)


def build_qb_twp_vs_interceptions_chart(qbs: pd.DataFrame, *, output_dir: Path, season: int, week: int, min_dropbacks: int = QUALIFIERS["qb_min_dropbacks"], max_rows: int = 12, period_label: str | None = None) -> Path:
    label = period_label or f"{season} Week {week}"
    df = qb_twp_vs_interceptions_dataframe(qbs, min_dropbacks=min_dropbacks)
    output_dir.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_dir / "qb_twp_vs_interceptions.csv", index=False)
    positive = df[df["twp_minus_int"].gt(0)].head(max_rows - 2)
    negative = df[df["twp_minus_int"].lt(0)].head(max(2, max_rows - len(positive)))
    display = pd.concat([positive, negative], ignore_index=True).head(max_rows)
    if display.empty:
        display = df.head(max_rows).copy()

    fig = plt.figure(figsize=(12, 6.75), constrained_layout=False)
    fig.patch.set_facecolor(DEFAULT_STYLE.background)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.text(0.07, 0.94, "QB Turnover-Worthy Plays vs. Interceptions", fontsize=23, fontweight="bold", color=DEFAULT_STYLE.text, ha="left", va="top")
    ax.text(0.07, 0.885, f"QBs with {min_dropbacks}+ dropbacks | {label}", fontsize=12.5, color=DEFAULT_STYLE.muted_text, ha="left", va="top")
    headers = [("PLAYER", 0.09), ("TWP", 0.57), ("INT", 0.66), ("TWP-INT", 0.75), ("CONTEXT", 0.84)]
    for text, x in headers:
        ax.text(x, 0.805, text, fontsize=10.5, fontweight="bold", color=DEFAULT_STYLE.muted_text, ha="left", va="center")
    ax.plot([0.07, 0.93], [0.777, 0.777], color=DEFAULT_STYLE.grid, alpha=0.45, linewidth=1.0)
    start_y = 0.725
    row_h = 0.051
    max_abs = max(float(display["abs_twp_minus_int"].max()), 1.0)
    for idx, row in display.reset_index(drop=True).iterrows():
        y = start_y - int(idx) * row_h
        if int(idx) % 2 == 0:
            ax.add_patch(Rectangle((0.07, y - 0.024), 0.86, 0.041, color="#17212A", alpha=0.42, linewidth=0))
        player = f"{row.player_name} ({row.team})"
        ax.text(0.09, y, player, fontsize=_fit_name_size(player), color=DEFAULT_STYLE.text, fontweight="bold", ha="left", va="center")
        ax.text(0.57, y, f"{int(row.turnover_worthy_plays)}", fontsize=15.5, color=DEFAULT_STYLE.text, fontweight="bold", ha="left", va="center")
        ax.text(0.66, y, f"{int(row.interceptions)}", fontsize=15.5, color=DEFAULT_STYLE.text, fontweight="bold", ha="left", va="center")
        diff = int(row.twp_minus_int)
        color = DEFAULT_STYLE.accent if diff >= 0 else DEFAULT_STYLE.accent_secondary
        width = 0.052 * (abs(diff) / max_abs)
        x0 = 0.748 if diff >= 0 else 0.748 - width
        ax.add_patch(FancyBboxPatch((x0, y - 0.015), width, 0.03, boxstyle="round,pad=0.003,rounding_size=0.005", linewidth=0, facecolor=color, alpha=0.28))
        ax.text(0.75, y, f"{diff:+d}", fontsize=15.5, color=DEFAULT_STYLE.text, fontweight="bold", ha="left", va="center")
        context = f"{int(row.dropbacks)} dropbacks"
        if "attempts" in row and not pd.isna(row.attempts):
            context = f"{int(row.attempts)} att | {context}"
        ax.text(0.84, y, context, fontsize=10.8, color=DEFAULT_STYLE.muted_text, ha="left", va="center")
    ax.text(0.07, 0.055, "TWP and INT are separate outcomes; difference shown for comparison only.", fontsize=8.8, color=DEFAULT_STYLE.muted_text, ha="left", va="bottom", alpha=0.82)
    ax.text(0.07, 0.035, f"First & Thirty | PFF data | {label}", fontsize=10.5, color=DEFAULT_STYLE.muted_text, ha="left", va="bottom")
    output_path = output_dir / "qb_twp_vs_interceptions.png"
    save_png(fig, output_path)
    return output_path
