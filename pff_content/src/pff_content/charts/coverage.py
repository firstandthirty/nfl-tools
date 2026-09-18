from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from pff_content.analysis.qualifiers import QUALIFIERS, safe_divide

from .dense_labels import add_dense_point_labels, dense_label_points_from_dataframe, existing_text_bboxes, record_label_stats
from .scatter import add_average_lines, padded_limits
from .style import DEFAULT_STYLE, add_footer, add_title_block, format_axes, save_png, social_figure


COVERAGE_CHART_COLUMNS = [
    "player_name",
    "team",
    "opponent",
    "position",
    "coverage_snaps",
    "targets",
    "receptions_allowed",
    "yards_allowed",
    "passer_rating_when_targeted",
    "forced_incompletes",
    "forced_incompletion_rate",
    "target_rank",
    "lowest_rating_rank",
    "highest_rating_rank",
    "forced_incompletion_rank",
    "highlight_reasons",
]


@dataclass(frozen=True)
class CoverageChartStats:
    qualified_count: int
    target_mean: float
    target_median: float
    passer_rating_mean: float
    passer_rating_median: float
    target_reference: float
    target_reference_type: str
    highlight_reasons: dict[str, list[str]]


def coverage_targets_vs_passer_rating_dataframe(
    coverage: pd.DataFrame,
    *,
    min_coverage_snaps: int = QUALIFIERS["coverage_min_snaps"],
    min_targets: int = QUALIFIERS["coverage_min_targets"],
) -> pd.DataFrame:
    required = {"player_name", "team", "position", "coverage_snaps", "targets", "passer_rating_when_targeted"}
    missing = required - set(coverage.columns)
    if missing:
        raise ValueError(f"Coverage chart data missing columns: {sorted(missing)}")
    df = coverage.copy()
    for col in ["coverage_snaps", "targets", "receptions", "yards", "passer_rating_when_targeted", "forced_incompletes", "forced_incompletion_rate"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "forced_incompletion_rate" not in df.columns and {"forced_incompletes", "targets"}.issubset(df.columns):
        df["forced_incompletion_rate"] = safe_divide(df["forced_incompletes"], df["targets"])
    df["receptions_allowed"] = df["receptions"] if "receptions" in df.columns else pd.NA
    df["yards_allowed"] = df["yards"] if "yards" in df.columns else pd.NA
    qualified = df[
        df["coverage_snaps"].ge(min_coverage_snaps)
        & df["targets"].ge(min_targets)
        & df["passer_rating_when_targeted"].notna()
    ].copy()
    qualified = qualified.sort_values(["targets", "passer_rating_when_targeted", "player_name"], ascending=[False, True, True], kind="mergesort")
    qualified["target_rank"] = qualified["targets"].rank(method="first", ascending=False).astype(int)
    qualified["lowest_rating_rank"] = qualified["passer_rating_when_targeted"].rank(method="first", ascending=True).astype(int)
    qualified["highest_rating_rank"] = qualified["passer_rating_when_targeted"].rank(method="first", ascending=False).astype(int)
    if "forced_incompletes" in qualified.columns:
        qualified["forced_incompletion_rank"] = qualified["forced_incompletes"].rank(method="first", ascending=False).astype(int)
    reasons = select_coverage_highlights(qualified)
    qualified["highlight_reasons"] = qualified["player_name"].map(lambda name: "; ".join(reasons.get(str(name), [])))
    cols = [col for col in COVERAGE_CHART_COLUMNS if col in qualified.columns]
    return qualified[cols].reset_index(drop=True)


def select_coverage_highlights(df: pd.DataFrame) -> dict[str, list[str]]:
    reasons: dict[str, list[str]] = {}
    candidate_sets: list[tuple[pd.Index, str]] = [
        (df.sort_values("targets", ascending=False).head(3).index, "top 3 target volume"),
        (df.sort_values("passer_rating_when_targeted", ascending=True).head(3).index, "top 3 lowest passer rating allowed"),
        (df.sort_values("passer_rating_when_targeted", ascending=False).head(3).index, "top 3 highest passer rating allowed"),
    ]
    if "forced_incompletes" in df.columns:
        candidate_sets.append((df.sort_values(["forced_incompletes", "forced_incompletion_rate", "targets"], ascending=[False, False, False]).head(5).index, "top forced-incompletion performers"))
    high_volume_low_rating = df[(df["target_rank"] <= 10) & (df["lowest_rating_rank"] <= 10)]
    candidate_sets.append((high_volume_low_rating.index, "top 10 targets and top 10 lowest passer rating allowed"))
    for indexes, reason in candidate_sets:
        for index in indexes:
            name = str(df.loc[index, "player_name"])
            reasons.setdefault(name, [])
            if reason not in reasons[name]:
                reasons[name].append(reason)
    return reasons


def coverage_targets_rating_stats(df: pd.DataFrame) -> CoverageChartStats:
    target_mean = float(df["targets"].mean())
    target_median = float(df["targets"].median())
    rating_mean = float(df["passer_rating_when_targeted"].mean())
    rating_median = float(df["passer_rating_when_targeted"].median())
    return CoverageChartStats(
        qualified_count=int(len(df)),
        target_mean=target_mean,
        target_median=target_median,
        passer_rating_mean=rating_mean,
        passer_rating_median=rating_median,
        target_reference=target_median,
        target_reference_type="median",
        highlight_reasons={str(row.player_name): str(row.highlight_reasons).split("; ") for _, row in df[df["highlight_reasons"].astype(str).ne("")].iterrows()},
    )


def _add_coverage_quadrants(ax, *, x_ref: float, y_ref: float) -> None:
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()
    labels = [
        ("More targets / Higher rating", x_ref + (x_max - x_ref) * 0.08, y_ref + (y_max - y_ref) * 0.88),
        ("Fewer targets / Higher rating", x_min + (x_ref - x_min) * 0.08, y_ref + (y_max - y_ref) * 0.88),
        ("More targets / Lower rating", x_ref + (x_max - x_ref) * 0.08, y_min + (y_ref - y_min) * 0.10),
        ("Fewer targets / Lower rating", x_min + (x_ref - x_min) * 0.08, y_min + (y_ref - y_min) * 0.10),
    ]
    for text, x, y in labels:
        ax.text(x, y, text, color=DEFAULT_STYLE.muted_text, fontsize=8.5, alpha=0.52, ha="left")


def build_coverage_targets_vs_passer_rating_chart(
    coverage: pd.DataFrame,
    *,
    output_dir: Path,
    season: int,
    week: int,
    min_coverage_snaps: int = QUALIFIERS["coverage_min_snaps"],
    min_targets: int = QUALIFIERS["coverage_min_targets"],
    period_label: str | None = None,
) -> Path:
    label = period_label or f"{season} Week {week}"
    chart_df = coverage_targets_vs_passer_rating_dataframe(coverage, min_coverage_snaps=min_coverage_snaps, min_targets=min_targets)
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_df.to_csv(output_dir / "coverage_targets_vs_passer_rating.csv", index=False)

    stats = coverage_targets_rating_stats(chart_df)
    fig, ax = social_figure()
    fig.subplots_adjust(left=0.075, right=0.965, top=0.80, bottom=0.15)
    format_axes(ax)
    ax.scatter(
        chart_df["targets"],
        chart_df["passer_rating_when_targeted"],
        s=(chart_df["coverage_snaps"].clip(lower=min_coverage_snaps, upper=65) * 3.0) + 18,
        c=DEFAULT_STYLE.accent,
        alpha=0.78,
        edgecolors=DEFAULT_STYLE.point_edge,
        linewidths=0.42,
    )
    ax.set_xlim(*padded_limits(chart_df["targets"], min_pad=0.75))
    ax.set_ylim(*padded_limits(chart_df["passer_rating_when_targeted"], min_pad=10))
    add_average_lines(ax, x_avg=stats.target_reference, y_avg=stats.passer_rating_mean)
    _add_coverage_quadrants(ax, x_ref=stats.target_reference, y_ref=stats.passer_rating_mean)
    ax.set_xlabel("Targets")
    ax.set_ylabel("Passer rating when targeted")
    ax.text(stats.target_reference, ax.get_ylim()[1], f" Median targets {stats.target_reference:.0f}", color=DEFAULT_STYLE.muted_text, fontsize=9.5, va="top", ha="left")
    ax.text(ax.get_xlim()[1], stats.passer_rating_mean, f"Avg rating {stats.passer_rating_mean:.1f} ", color=DEFAULT_STYLE.muted_text, fontsize=9.5, va="bottom", ha="right")
    highlights = set(stats.highlight_reasons)
    placement = add_dense_point_labels(
        ax,
        dense_label_points_from_dataframe(chart_df, x_col="targets", y_col="passer_rating_when_targeted", highlight_names=highlights, volume_col="targets"),
        include_standard_team=False,
        max_standard_labels=18,
        standard_font_size=5.5,
        highlight_font_size=7.1,
        reserved_bboxes=existing_text_bboxes(ax),
    )
    record_label_stats("coverage_targets_vs_passer_rating", placement)
    add_title_block(fig, title="Coverage Volume vs. Passer Rating Allowed", subtitle=f"Defenders with {min_coverage_snaps}+ coverage snaps and {min_targets}+ targets | {label}")
    add_footer(fig, text=f"First & Thirty | PFF data | {label}")
    output_path = output_dir / "coverage_targets_vs_passer_rating.png"
    save_png(fig, output_path)
    return output_path
