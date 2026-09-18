from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from pff_content.analysis.qualifiers import QUALIFIERS, safe_divide
from pff_content.paths import week_label

from .dense_labels import add_dense_point_labels, dense_label_points_from_dataframe, existing_text_bboxes, record_label_stats
from .scatter import LabelPoint, add_average_lines, add_subtle_quadrants, padded_limits
from .style import DEFAULT_STYLE, add_footer, add_title_block, format_axes, save_png, social_figure


RB_POSITIONS = {"RB", "HB", "FB"}
RECONCILIATION_TOLERANCE = 1e-9

REQUIRED_COLUMNS = {
    "player_name",
    "team",
    "attempts",
    "yards",
    "yards_after_contact_per_attempt",
    "yards_per_carry",
}

BEFORE_AFTER_REQUIRED_COLUMNS = {
    "player_name",
    "team",
    "position",
    "attempts",
    "yards",
    "yards_per_carry",
    "yards_after_contact",
}

BEFORE_AFTER_COLUMNS = [
    "player_name",
    "team",
    "position",
    "attempts",
    "rushing_yards",
    "yards_per_carry",
    "yards_after_contact",
    "yards_after_contact_per_attempt",
    "yards_before_contact",
    "yards_before_contact_per_attempt",
    "rookie",
]


@dataclass(frozen=True)
class LabelSelection:
    labels: list[LabelPoint]
    reasons: dict[str, list[str]]


def _qualified_rb_mask(df: pd.DataFrame, *, min_attempts: int) -> pd.Series:
    if "position" not in df.columns:
        return df["attempts"].ge(min_attempts)
    return df["attempts"].ge(min_attempts) & df["position"].astype(str).str.upper().isin(RB_POSITIONS)


def rb_ypa_vs_yaco_dataframe(rushing: pd.DataFrame, *, min_attempts: int = QUALIFIERS["rushing_min_attempts"]) -> pd.DataFrame:
    missing = REQUIRED_COLUMNS - set(rushing.columns)
    if missing:
        raise ValueError(f"Rushing chart data missing columns: {sorted(missing)}")

    df = rushing.copy()
    for column in ["attempts", "yards", "yards_after_contact_per_attempt", "yards_per_carry"]:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    qualified = df[
        _qualified_rb_mask(df, min_attempts=min_attempts)
        & df["yards_after_contact_per_attempt"].notna()
        & df["yards_per_carry"].notna()
    ].copy()
    if qualified.empty:
        raise ValueError(f"No qualified running backs found with attempts >= {min_attempts}.")

    cols = [
        "player_name",
        "team",
        "attempts",
        "yards",
        "yards_after_contact_per_attempt",
        "yards_per_carry",
    ]
    for optional in ["opponent", "position"]:
        if optional in qualified.columns:
            cols.insert(2, optional)

    return qualified[cols].sort_values(
        ["yards_after_contact_per_attempt", "yards_per_carry", "attempts"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def rb_before_vs_after_contact_dataframe(
    rushing: pd.DataFrame,
    *,
    min_attempts: int = QUALIFIERS["rushing_min_attempts"],
    tolerance: float = RECONCILIATION_TOLERANCE,
) -> pd.DataFrame:
    missing = BEFORE_AFTER_REQUIRED_COLUMNS - set(rushing.columns)
    if missing:
        raise ValueError(f"Before/after contact chart data missing columns: {sorted(missing)}")

    df = rushing.copy()
    numeric_cols = ["attempts", "yards", "yards_per_carry", "yards_after_contact"]
    for column in numeric_cols:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    qualified = df[
        _qualified_rb_mask(df, min_attempts=min_attempts)
        & df["yards"].notna()
        & df["yards_per_carry"].notna()
        & df["yards_after_contact"].notna()
    ].copy()
    if qualified.empty:
        raise ValueError(f"No qualified running backs found with attempts >= {min_attempts}.")

    qualified["rushing_yards"] = qualified["yards"]
    qualified["yards_before_contact"] = qualified["rushing_yards"] - qualified["yards_after_contact"]
    qualified["yards_before_contact_per_attempt"] = safe_divide(qualified["yards_before_contact"], qualified["attempts"])
    qualified["yards_after_contact_per_attempt"] = safe_divide(qualified["yards_after_contact"], qualified["attempts"])
    if "rookie" not in qualified.columns:
        qualified["rookie"] = False

    calculated_ypc = qualified["yards_before_contact_per_attempt"] + qualified["yards_after_contact_per_attempt"]
    unreconciled = qualified[(qualified["yards_per_carry"] - calculated_ypc).abs() > tolerance]
    if not unreconciled.empty:
        details = unreconciled[["player_name", "team", "yards_per_carry"]].copy()
        details["before_plus_after"] = calculated_ypc.loc[unreconciled.index]
        raise ValueError(
            "Before/after contact values do not reconcile to yards per carry: "
            + details.to_dict("records").__repr__()
        )

    return qualified[BEFORE_AFTER_COLUMNS].sort_values(
        ["yards_before_contact_per_attempt", "yards_after_contact_per_attempt", "attempts"],
        ascending=[False, False, False],
    ).reset_index(drop=True)


def before_after_reference_stats(chart_df: pd.DataFrame) -> dict[str, float]:
    return {
        "mean_before": float(chart_df["yards_before_contact_per_attempt"].mean()),
        "median_before": float(chart_df["yards_before_contact_per_attempt"].median()),
        "mean_after": float(chart_df["yards_after_contact_per_attempt"].mean()),
        "median_after": float(chart_df["yards_after_contact_per_attempt"].median()),
    }


def before_after_quadrant_counts(chart_df: pd.DataFrame, *, x_ref: float, y_ref: float) -> dict[str, int]:
    x = chart_df["yards_before_contact_per_attempt"]
    y = chart_df["yards_after_contact_per_attempt"]
    return {
        "upper_right": int(((x > x_ref) & (y > y_ref)).sum()),
        "upper_left": int(((x <= x_ref) & (y > y_ref)).sum()),
        "lower_right": int(((x > x_ref) & (y <= y_ref)).sum()),
        "lower_left": int(((x <= x_ref) & (y <= y_ref)).sum()),
    }


def add_before_after_contrasts(chart_df: pd.DataFrame) -> pd.DataFrame:
    out = chart_df.copy()
    before = out["yards_before_contact_per_attempt"]
    after = out["yards_after_contact_per_attempt"]
    out["after_minus_before"] = after - before
    out["before_minus_after"] = before - after
    return out


def select_before_after_labels(chart_df: pd.DataFrame, *, max_labels: int = 8) -> LabelSelection:
    scored = add_before_after_contrasts(chart_df)
    candidates: list[tuple[int, str]] = [
        (int(scored["yards_before_contact_per_attempt"].idxmax()), "highest before-contact yards/attempt"),
        (int(scored["yards_before_contact_per_attempt"].idxmin()), "lowest before-contact yards/attempt"),
        (int(scored["yards_after_contact_per_attempt"].idxmax()), "highest after-contact yards/attempt"),
        (int(scored["yards_after_contact_per_attempt"].idxmin()), "lowest after-contact yards/attempt"),
    ]
    candidates.extend(
        (int(index), "top 3 after-minus-before contrast")
        for index in scored.sort_values("after_minus_before", ascending=False).head(3).index
    )
    candidates.extend(
        (int(index), "top 3 before-minus-after contrast")
        for index in scored.sort_values("before_minus_after", ascending=False).head(3).index
    )

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
        row = scored.loc[index]
        player_key = str(row["player_name"])
        labels.append(
            LabelPoint(
                label=f"{row.player_name} ({row.team})",
                x=float(row["yards_before_contact_per_attempt"]),
                y=float(row["yards_after_contact_per_attempt"]),
            )
        )
        reasons[player_key] = reasons_by_index[index]
    return LabelSelection(labels=labels, reasons=reasons)


def build_rb_ypa_vs_yaco_chart(
    rushing: pd.DataFrame,
    *,
    output_dir: Path,
    season: int,
    week: int,
    min_attempts: int = QUALIFIERS["rushing_min_attempts"],
    period_label: str | None = None,
) -> Path:
    label = period_label or f"{season} Week {week}"
    chart_df = rb_ypa_vs_yaco_dataframe(rushing, min_attempts=min_attempts)
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_df.to_csv(output_dir / "rb_ypa_vs_yaco.csv", index=False)

    x_col = "yards_after_contact_per_attempt"
    y_col = "yards_per_carry"
    x_avg = float(chart_df[x_col].mean())
    y_avg = float(chart_df[y_col].mean())

    fig, ax = social_figure()
    fig.subplots_adjust(left=0.075, right=0.965, top=0.80, bottom=0.15)
    format_axes(ax)

    sizes = (chart_df["attempts"].clip(lower=min_attempts, upper=25) * 6.5) + 28
    ax.scatter(
        chart_df[x_col],
        chart_df[y_col],
        s=sizes,
        c=DEFAULT_STYLE.accent,
        alpha=0.82,
        edgecolors=DEFAULT_STYLE.point_edge,
        linewidths=0.45,
    )

    add_average_lines(ax, x_avg=x_avg, y_avg=y_avg)
    ax.set_xlim(*padded_limits(chart_df[x_col]))
    ax.set_ylim(*padded_limits(chart_df[y_col]))
    add_subtle_quadrants(ax, x_avg=x_avg, y_avg=y_avg)

    ax.set_xlabel("Yards after contact per attempt")
    ax.set_ylabel("Yards per carry")
    ax.text(
        x_avg,
        ax.get_ylim()[1],
        f" Avg YAC/att {x_avg:.2f}",
        color=DEFAULT_STYLE.muted_text,
        fontsize=9.5,
        va="top",
        ha="left",
    )
    ax.text(
        ax.get_xlim()[1],
        y_avg,
        f"Avg YPC {y_avg:.2f} ",
        color=DEFAULT_STYLE.muted_text,
        fontsize=9.5,
        va="bottom",
        ha="right",
    )

    labels = select_rb_labels(chart_df, x_col=x_col, y_col=y_col, max_labels=7)
    highlight_names = {label.label.split(" (")[0] for label in labels}
    placement = add_dense_point_labels(
        ax,
        dense_label_points_from_dataframe(
            chart_df,
            x_col=x_col,
            y_col=y_col,
            highlight_names=highlight_names,
            volume_col="attempts",
        ),
        reserved_bboxes=existing_text_bboxes(ax),
    )
    record_label_stats("rb_ypa_vs_yaco", placement)

    title = "RB Efficiency: Yards After Contact vs. Yards Per Carry"
    subtitle = f"Qualified running backs, minimum {min_attempts} rushing attempts | {label}"
    add_title_block(fig, title=title, subtitle=subtitle)
    add_footer(fig, text=f"First & Thirty | PFF data | {label}")

    output_path = output_dir / "rb_ypa_vs_yaco.png"
    save_png(fig, output_path)
    return output_path


def _add_before_after_quadrants(ax, *, x_ref: float, y_ref: float) -> None:
    x_min, x_max = ax.get_xlim()
    y_min, y_max = ax.get_ylim()
    labels = [
        ("More before contact, more after contact", (x_ref + x_max) / 2, y_ref + (y_max - y_ref) * 0.88, "center"),
        ("Less before contact, more after contact", x_min + (x_ref - x_min) * 0.08, y_ref + (y_max - y_ref) * 0.88, "left"),
        ("More before contact, less after contact", (x_ref + x_max) / 2, y_min + (y_ref - y_min) * 0.10, "center"),
        ("Less before contact, less after contact", x_min + (x_ref - x_min) * 0.08, y_min + (y_ref - y_min) * 0.10, "left"),
    ]
    for text, x, y, ha in labels:
        ax.text(x, y, text, color=DEFAULT_STYLE.muted_text, fontsize=9.0, alpha=0.54, ha=ha)


def build_rb_before_vs_after_contact_chart(
    rushing: pd.DataFrame,
    *,
    output_dir: Path,
    season: int,
    week: int,
    min_attempts: int = QUALIFIERS["rushing_min_attempts"],
    period_label: str | None = None,
) -> Path:
    label = period_label or f"{season} Week {week}"
    chart_df = rb_before_vs_after_contact_dataframe(rushing, min_attempts=min_attempts)
    output_dir.mkdir(parents=True, exist_ok=True)
    chart_df.to_csv(output_dir / "rb_before_vs_after_contact.csv", index=False)

    x_col = "yards_before_contact_per_attempt"
    y_col = "yards_after_contact_per_attempt"
    stats = before_after_reference_stats(chart_df)
    x_avg = stats["mean_before"]
    y_avg = stats["mean_after"]

    fig, ax = social_figure()
    fig.subplots_adjust(left=0.075, right=0.965, top=0.80, bottom=0.15)
    format_axes(ax)

    sizes = (chart_df["attempts"].clip(lower=min_attempts, upper=25) * 6.5) + 28
    ax.scatter(
        chart_df[x_col],
        chart_df[y_col],
        s=sizes,
        c=DEFAULT_STYLE.accent,
        alpha=0.82,
        edgecolors=DEFAULT_STYLE.point_edge,
        linewidths=0.45,
    )

    x_limits = padded_limits(chart_df[x_col])
    y_limits = padded_limits(chart_df[y_col])
    ax.set_xlim(*x_limits)
    ax.set_ylim(*y_limits)
    add_average_lines(ax, x_avg=x_avg, y_avg=y_avg)
    if x_limits[0] <= 0 <= x_limits[1]:
        ax.axvline(0, color=DEFAULT_STYLE.accent_secondary, linewidth=0.9, alpha=0.48, linestyle=(0, (1, 4)))
        ax.text(
            0,
            y_limits[0],
            " Zero before contact",
            color=DEFAULT_STYLE.muted_text,
            fontsize=8.8,
            va="bottom",
            ha="left",
            alpha=0.75,
        )
    _add_before_after_quadrants(ax, x_ref=x_avg, y_ref=y_avg)

    ax.set_xlabel("Yards before contact per attempt")
    ax.set_ylabel("Yards after contact per attempt")
    ax.text(
        x_avg,
        ax.get_ylim()[1],
        f" Avg before/att {x_avg:.2f}",
        color=DEFAULT_STYLE.muted_text,
        fontsize=9.5,
        va="top",
        ha="left",
    )
    ax.text(
        ax.get_xlim()[1],
        y_avg,
        f"Avg after/att {y_avg:.2f} ",
        color=DEFAULT_STYLE.muted_text,
        fontsize=9.5,
        va="bottom",
        ha="right",
    )

    selection = select_before_after_labels(chart_df, max_labels=8)
    placement = add_dense_point_labels(
        ax,
        dense_label_points_from_dataframe(
            chart_df,
            x_col=x_col,
            y_col=y_col,
            highlight_names=set(selection.reasons),
            volume_col="attempts",
        ),
        reserved_bboxes=existing_text_bboxes(ax),
    )
    record_label_stats("rb_before_vs_after_contact", placement)

    add_title_block(
        fig,
        title="RB Rushing Profiles: Before vs. After Contact",
        subtitle=f"Qualified running backs, minimum {min_attempts} rushing attempts | {label}",
    )
    add_footer(fig, text=f"First & Thirty | PFF data | {label}")

    output_path = output_dir / "rb_before_vs_after_contact.png"
    save_png(fig, output_path)
    return output_path


def select_rb_labels(
    chart_df: pd.DataFrame,
    *,
    x_col: str,
    y_col: str,
    max_labels: int = 9,
) -> list[LabelPoint]:
    picks: list[int] = []
    candidate_indexes = [
        chart_df[x_col].idxmax(),
        chart_df[y_col].idxmax(),
        chart_df["attempts"].idxmax(),
        chart_df[x_col].idxmin(),
        chart_df[y_col].idxmin(),
    ]

    x_avg = chart_df[x_col].mean()
    y_avg = chart_df[y_col].mean()
    scored = chart_df.assign(
        quadrant_distance=((chart_df[x_col] - x_avg).abs() + (chart_df[y_col] - y_avg).abs())
    )
    candidate_indexes.extend(scored.sort_values("quadrant_distance", ascending=False).head(max_labels).index.tolist())

    for index in candidate_indexes:
        if index not in picks:
            picks.append(index)
        if len(picks) >= max_labels:
            break

    labels = []
    for index in picks:
        row = chart_df.loc[index]
        labels.append(
            LabelPoint(
                label=f"{row.player_name} ({row.team})",
                x=float(row[x_col]),
                y=float(row[y_col]),
            )
        )
    return labels


