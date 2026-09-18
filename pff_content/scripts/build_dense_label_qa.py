from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pff_content.charts.dense_labels import (
    DenseLabelPoint,
    HIGHLIGHT_LABEL_FONT_SIZE,
    STANDARD_LABEL_FONT_SIZE,
    add_dense_point_labels,
)
from pff_content.charts.pass_rush import (
    _add_pass_rush_quadrants,
    format_rate_axes,
    pass_rush_reference_stats,
    pass_rush_win_rate_vs_pressure_rate_dataframe,
    select_pass_rush_labels,
)
from pff_content.charts.receiving import (
    _add_receiving_quadrants,
    format_tprr_axis,
    receiving_reference_stats,
    receiving_tprr_vs_yprr_dataframe,
    select_receiving_labels,
)
from pff_content.charts.rushing import (
    _add_before_after_quadrants,
    before_after_reference_stats,
    rb_before_vs_after_contact_dataframe,
    select_before_after_labels,
)
from pff_content.charts.scatter import add_average_lines, padded_limits
from pff_content.charts.style import DEFAULT_STYLE, add_footer, add_title_block, format_axes, save_png, social_figure
from pff_content.paths import week_label


def analysis_dir(season: int, week: int) -> Path:
    return ROOT / "outputs" / str(season) / week_label(week)


def chart_dir(season: int, week: int) -> Path:
    return analysis_dir(season, week) / "charts"


def dense_points(
    df: pd.DataFrame,
    *,
    x_col: str,
    y_col: str,
    highlight_reasons: dict[str, list[str]],
    volume_col: str,
) -> list[DenseLabelPoint]:
    volume_rank = df[volume_col].rank(method="first", ascending=False).astype(int).to_dict()
    points: list[DenseLabelPoint] = []
    for index, row in df.iterrows():
        name = str(row["player_name"])
        highlighted = name in highlight_reasons
        points.append(
            DenseLabelPoint(
                label=name,
                player_name=name,
                team=str(row["team"]),
                x=float(row[x_col]),
                y=float(row[y_col]),
                highlighted=highlighted,
                priority=0 if highlighted else int(volume_rank[index]),
            )
        )
    return points


def build_pass_rush_qa(pass_rush: pd.DataFrame, *, output_path: Path, season: int, week: int, min_snaps: int) -> dict[str, object]:
    df = pass_rush_win_rate_vs_pressure_rate_dataframe(pass_rush, min_pass_rush_snaps=min_snaps)
    stats = pass_rush_reference_stats(df)
    fig, ax = social_figure(width=12.2, height=6.75)
    fig.subplots_adjust(left=0.065, right=0.985, top=0.825, bottom=0.13)
    format_axes(ax)
    ax.scatter(
        df["pass_rush_win_rate"],
        df["pressure_rate"],
        s=(df["pass_rush_snaps"].clip(lower=min_snaps, upper=55) * 3.5) + 22,
        c=DEFAULT_STYLE.accent,
        alpha=0.76,
        edgecolors=DEFAULT_STYLE.point_edge,
        linewidths=0.45,
    )
    ax.set_xlim(*padded_limits(df["pass_rush_win_rate"], min_pad=0.025))
    ax.set_ylim(*padded_limits(df["pressure_rate"], min_pad=0.025))
    add_average_lines(ax, x_avg=stats["mean_win_rate"], y_avg=stats["mean_pressure_rate"])
    _add_pass_rush_quadrants(ax, x_ref=stats["mean_win_rate"], y_ref=stats["mean_pressure_rate"])
    format_rate_axes(ax)
    ax.set_xlabel("Pass-Rush Win Rate")
    ax.set_ylabel("Pressure Rate")
    ax.text(stats["mean_win_rate"], ax.get_ylim()[1], f" Avg win rate {stats['mean_win_rate']:.1%}", color=DEFAULT_STYLE.muted_text, fontsize=9.0, va="top", ha="left")
    ax.text(ax.get_xlim()[1], stats["mean_pressure_rate"], f"Avg pressure rate {stats['mean_pressure_rate']:.1%} ", color=DEFAULT_STYLE.muted_text, fontsize=9.0, va="bottom", ha="right")
    selection = select_pass_rush_labels(df, max_labels=8)
    placement = add_dense_point_labels(
        ax,
        dense_points(df, x_col="pass_rush_win_rate", y_col="pressure_rate", highlight_reasons=selection.reasons, volume_col="pass_rush_snaps"),
        include_standard_team=False,
    )
    add_title_block(fig, title="Pass Rush: Winning vs. Creating Pressure", subtitle=f"Defenders with {min_snaps}+ pass-rush snaps | {season} Week {week}")
    add_footer(fig, text=f"First & Thirty | PFF data | {season} Week {week} | dense-label QA")
    save_png(fig, output_path)
    return placement.__dict__ | {"path": str(output_path)}


def build_receiving_qa(receiving: pd.DataFrame, *, output_path: Path, season: int, week: int) -> dict[str, object]:
    df = receiving_tprr_vs_yprr_dataframe(receiving, min_routes=15)
    stats = receiving_reference_stats(df)
    fig, ax = social_figure(width=12.2, height=6.75)
    fig.subplots_adjust(left=0.065, right=0.985, top=0.825, bottom=0.13)
    format_axes(ax)
    ax.scatter(
        df["targets_per_route_run"],
        df["yards_per_route_run"],
        s=(df["routes"].clip(lower=15, upper=45) * 3.8) + 20,
        c=DEFAULT_STYLE.accent,
        alpha=0.76,
        edgecolors=DEFAULT_STYLE.point_edge,
        linewidths=0.45,
    )
    ax.set_xlim(*padded_limits(df["targets_per_route_run"], min_pad=0.025))
    ax.set_ylim(*padded_limits(df["yards_per_route_run"], min_pad=0.25))
    add_average_lines(ax, x_avg=stats["mean_tprr"], y_avg=stats["mean_yprr"])
    _add_receiving_quadrants(ax, x_ref=stats["mean_tprr"], y_ref=stats["mean_yprr"])
    format_tprr_axis(ax)
    ax.set_xlabel("Targets per route run")
    ax.set_ylabel("Yards per route run")
    ax.text(stats["mean_tprr"], ax.get_ylim()[1], f" Avg TPRR {stats['mean_tprr']:.1%}", color=DEFAULT_STYLE.muted_text, fontsize=9.0, va="top", ha="left")
    ax.text(ax.get_xlim()[1], stats["mean_yprr"], f"Avg YPRR {stats['mean_yprr']:.2f} ", color=DEFAULT_STYLE.muted_text, fontsize=9.0, va="bottom", ha="right")
    selection = select_receiving_labels(df, max_labels=8)
    placement = add_dense_point_labels(
        ax,
        dense_points(df, x_col="targets_per_route_run", y_col="yards_per_route_run", highlight_reasons=selection.reasons, volume_col="routes"),
        include_standard_team=False,
    )
    add_title_block(fig, title="Target Earners vs. Receiving Production", subtitle=f"WR/TE with 15+ routes | {season} Week {week}")
    add_footer(fig, text=f"First & Thirty | PFF data | {season} Week {week} | dense-label QA")
    save_png(fig, output_path)
    return placement.__dict__ | {"path": str(output_path)}


def build_rb_qa(rushing: pd.DataFrame, *, output_path: Path, season: int, week: int) -> dict[str, object]:
    df = rb_before_vs_after_contact_dataframe(rushing, min_attempts=8)
    stats = before_after_reference_stats(df)
    fig, ax = social_figure(width=12.2, height=6.75)
    fig.subplots_adjust(left=0.065, right=0.985, top=0.825, bottom=0.13)
    format_axes(ax)
    ax.scatter(
        df["yards_before_contact_per_attempt"],
        df["yards_after_contact_per_attempt"],
        s=(df["attempts"].clip(lower=8, upper=25) * 6.5) + 28,
        c=DEFAULT_STYLE.accent,
        alpha=0.78,
        edgecolors=DEFAULT_STYLE.point_edge,
        linewidths=0.45,
    )
    x_limits = padded_limits(df["yards_before_contact_per_attempt"])
    y_limits = padded_limits(df["yards_after_contact_per_attempt"])
    ax.set_xlim(*x_limits)
    ax.set_ylim(*y_limits)
    add_average_lines(ax, x_avg=stats["mean_before"], y_avg=stats["mean_after"])
    if x_limits[0] <= 0 <= x_limits[1]:
        ax.axvline(0, color=DEFAULT_STYLE.accent_secondary, linewidth=0.8, alpha=0.42, linestyle=(0, (1, 4)))
    _add_before_after_quadrants(ax, x_ref=stats["mean_before"], y_ref=stats["mean_after"])
    ax.set_xlabel("Yards before contact per attempt")
    ax.set_ylabel("Yards after contact per attempt")
    ax.text(stats["mean_before"], ax.get_ylim()[1], f" Avg before/att {stats['mean_before']:.2f}", color=DEFAULT_STYLE.muted_text, fontsize=9.0, va="top", ha="left")
    ax.text(ax.get_xlim()[1], stats["mean_after"], f"Avg after/att {stats['mean_after']:.2f} ", color=DEFAULT_STYLE.muted_text, fontsize=9.0, va="bottom", ha="right")
    selection = select_before_after_labels(df, max_labels=8)
    placement = add_dense_point_labels(
        ax,
        dense_points(df, x_col="yards_before_contact_per_attempt", y_col="yards_after_contact_per_attempt", highlight_reasons=selection.reasons, volume_col="attempts"),
        include_standard_team=False,
    )
    add_title_block(fig, title="RB Rushing Profiles: Before vs. After Contact", subtitle=f"Qualified running backs, minimum 8 rushing attempts | {season} Week {week}")
    add_footer(fig, text=f"First & Thirty | PFF data | {season} Week {week} | dense-label QA")
    save_png(fig, output_path)
    return placement.__dict__ | {"path": str(output_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build dense-label QA chart variants without touching official chart outputs.")
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--week", type=int, default=1)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base = analysis_dir(args.season, args.week)
    out = chart_dir(args.season, args.week) / "qa"
    out.mkdir(parents=True, exist_ok=True)
    pass_rush = pd.read_csv(base / "pass_rush.csv")
    receiving = pd.read_csv(base / "receiving.csv")
    rushing = pd.read_csv(base / "rushing.csv")
    results = {
        "standard_label_font_size": STANDARD_LABEL_FONT_SIZE,
        "highlight_label_font_size": HIGHLIGHT_LABEL_FONT_SIZE,
        "standard_labels_include_team": False,
        "pass_rush_15": build_pass_rush_qa(pass_rush, output_path=out / "pass_rush_15.png", season=args.season, week=args.week, min_snaps=15),
        "pass_rush_20": build_pass_rush_qa(pass_rush, output_path=out / "pass_rush_20.png", season=args.season, week=args.week, min_snaps=20),
        "pass_rush_25": build_pass_rush_qa(pass_rush, output_path=out / "pass_rush_25.png", season=args.season, week=args.week, min_snaps=25),
        "receiving": build_receiving_qa(receiving, output_path=out / "receiving_dense_labels.png", season=args.season, week=args.week),
        "rb_before_after": build_rb_qa(rushing, output_path=out / "rb_before_after_dense_labels.png", season=args.season, week=args.week),
    }
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
