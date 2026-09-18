from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Literal

import pandas as pd
from matplotlib import pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

from pff_content.charts.pass_rush import pass_rush_win_rate_vs_pressure_rate_dataframe
from pff_content.charts.receiving import receiving_tprr_vs_yprr_dataframe
from pff_content.charts.rushing import rb_ypa_vs_yaco_dataframe
from pff_content.charts.style import DEFAULT_STYLE, apply_theme, save_png

SortDirection = Literal["ascending", "descending"]
Formatter = Callable[[object], str]
DataBuilder = Callable[[dict[str, pd.DataFrame]], pd.DataFrame]


@dataclass(frozen=True)
class LeaderboardColumn:
    key: str
    label: str
    formatter: Formatter


@dataclass(frozen=True)
class LeaderboardDefinition:
    id: str
    title: str
    subtitle: str
    dataset: str
    qualifier: str
    ranking_metric: str
    sort_direction: SortDirection
    volume_tiebreaker: str
    n: int
    primary_metric: LeaderboardColumn
    context_columns: tuple[LeaderboardColumn, ...]
    output_filename: str
    data_builder: DataBuilder


@dataclass(frozen=True)
class LeaderboardResult:
    definition: LeaderboardDefinition
    rows: pd.DataFrame
    png_path: Path
    csv_path: Path


def format_percentage(value: object, decimals: int = 1) -> str:
    if pd.isna(value):
        return "--"
    return f"{float(value):.{decimals}%}"


def format_decimal(value: object, decimals: int = 2) -> str:
    if pd.isna(value):
        return "--"
    return f"{float(value):.{decimals}f}"


def format_integer(value: object) -> str:
    if pd.isna(value):
        return "--"
    return f"{int(value)}"


def _player_display(row: pd.Series) -> str:
    return f"{row['player_name']} ({row['team']})"


def _fit_text_size(text: str, *, base: float, max_chars: int, minimum: float) -> float:
    overflow = max(len(text) - max_chars, 0)
    return max(minimum, base - overflow * 0.22)


def select_top_n(definition: LeaderboardDefinition, population: pd.DataFrame) -> pd.DataFrame:
    ascending = definition.sort_direction == "ascending"
    sorted_df = population.sort_values(
        [definition.ranking_metric, definition.volume_tiebreaker, "player_name"],
        ascending=[ascending, False, True],
        kind="mergesort",
    ).head(definition.n).copy()
    sorted_df.insert(0, "rank", range(1, len(sorted_df) + 1))
    return sorted_df.reset_index(drop=True)


def _receiving_population(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return receiving_tprr_vs_yprr_dataframe(data["receiving"], min_routes=15)


def _rushing_population(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    df = rb_ypa_vs_yaco_dataframe(data["rushing"], min_attempts=8).copy()
    df["rushing_yards"] = df["yards"]
    return df


def _pass_rush_population(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pass_rush_win_rate_vs_pressure_rate_dataframe(data["pass_rush"], min_pass_rush_snaps=15)


def leaderboard_definitions(period_label: str = "Week 1") -> list[LeaderboardDefinition]:
    return [
        LeaderboardDefinition(
            id="target_earners",
            title=f"{period_label} Target Earners",
            subtitle="WR/TE with 15+ routes",
            dataset="receiving",
            qualifier="WR/TE with 15+ routes",
            ranking_metric="targets_per_route_run",
            sort_direction="descending",
            volume_tiebreaker="routes",
            n=10,
            primary_metric=LeaderboardColumn("targets_per_route_run", "TPRR", lambda value: format_percentage(value, 1)),
            context_columns=(
                LeaderboardColumn("targets", "targets", format_integer),
                LeaderboardColumn("routes", "routes", format_integer),
            ),
            output_filename="target_earners",
            data_builder=_receiving_population,
        ),
        LeaderboardDefinition(
            id="yprr_leaders",
            title=f"{period_label} Yards Per Route Run Leaders",
            subtitle="WR/TE with 15+ routes",
            dataset="receiving",
            qualifier="WR/TE with 15+ routes",
            ranking_metric="yards_per_route_run",
            sort_direction="descending",
            volume_tiebreaker="routes",
            n=10,
            primary_metric=LeaderboardColumn("yards_per_route_run", "YPRR", lambda value: format_decimal(value, 2)),
            context_columns=(
                LeaderboardColumn("receiving_yards", "rec yds", format_integer),
                LeaderboardColumn("routes", "routes", format_integer),
            ),
            output_filename="yprr_leaders",
            data_builder=_receiving_population,
        ),
        LeaderboardDefinition(
            id="yac_per_attempt_leaders",
            title=f"{period_label} Yards After Contact Leaders",
            subtitle="RBs with 8+ rushing attempts",
            dataset="rushing",
            qualifier="RB/HB/FB with 8+ rushing attempts",
            ranking_metric="yards_after_contact_per_attempt",
            sort_direction="descending",
            volume_tiebreaker="attempts",
            n=10,
            primary_metric=LeaderboardColumn("yards_after_contact_per_attempt", "YAC/att", lambda value: format_decimal(value, 2)),
            context_columns=(
                LeaderboardColumn("rushing_yards", "rush yds", format_integer),
                LeaderboardColumn("attempts", "attempts", format_integer),
            ),
            output_filename="yac_per_attempt_leaders",
            data_builder=_rushing_population,
        ),
        LeaderboardDefinition(
            id="pressure_leaders",
            title=f"{period_label} Pressure Leaders",
            subtitle="Defenders with 15+ pass-rush snaps",
            dataset="pass_rush",
            qualifier="Defenders with 15+ pass-rush snaps",
            ranking_metric="pressures",
            sort_direction="descending",
            volume_tiebreaker="pass_rush_snaps",
            n=10,
            primary_metric=LeaderboardColumn("pressures", "pressures", format_integer),
            context_columns=(
                LeaderboardColumn("pass_rush_win_rate", "win rate", lambda value: format_percentage(value, 1)),
                LeaderboardColumn("pass_rush_snaps", "rush snaps", format_integer),
            ),
            output_filename="pressure_leaders",
            data_builder=_pass_rush_population,
        ),
        LeaderboardDefinition(
            id="pass_rush_win_rate_leaders",
            title=f"{period_label} Pass-Rush Win Rate Leaders",
            subtitle="Defenders with 15+ pass-rush snaps",
            dataset="pass_rush",
            qualifier="Defenders with 15+ pass-rush snaps",
            ranking_metric="pass_rush_win_rate",
            sort_direction="descending",
            volume_tiebreaker="pass_rush_snaps",
            n=10,
            primary_metric=LeaderboardColumn("pass_rush_win_rate", "win rate", lambda value: format_percentage(value, 1)),
            context_columns=(
                LeaderboardColumn("pressures", "pressures", format_integer),
                LeaderboardColumn("pass_rush_snaps", "rush snaps", format_integer),
            ),
            output_filename="pass_rush_win_rate_leaders",
            data_builder=_pass_rush_population,
        ),
    ]


def _context_text(definition: LeaderboardDefinition, row: pd.Series) -> str:
    return " | ".join(f"{column.formatter(row[column.key])} {column.label}" for column in definition.context_columns)


def render_leaderboard_png(
    definition: LeaderboardDefinition,
    rows: pd.DataFrame,
    output_path: Path,
    *,
    season: int,
    week: int,
    use_bars: bool = True,
    period_label: str | None = None,
) -> Path:
    label = period_label or f"{season} Week {week}"
    apply_theme()
    fig = plt.figure(figsize=(12, 6.75), constrained_layout=False)
    fig.patch.set_facecolor(DEFAULT_STYLE.background)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)

    ax.text(0.07, 0.945, definition.title, fontsize=25, fontweight="bold", color=DEFAULT_STYLE.text, ha="left", va="top")
    ax.text(0.07, 0.89, definition.subtitle, fontsize=13.5, color=DEFAULT_STYLE.muted_text, ha="left", va="top")

    header_y = 0.82
    ax.text(0.082, header_y, "#", fontsize=10.5, color=DEFAULT_STYLE.muted_text, fontweight="bold", ha="center", va="center")
    ax.text(0.135, header_y, "PLAYER", fontsize=10.5, color=DEFAULT_STYLE.muted_text, fontweight="bold", ha="left", va="center")
    ax.text(0.64, header_y, definition.primary_metric.label.upper(), fontsize=10.5, color=DEFAULT_STYLE.muted_text, fontweight="bold", ha="left", va="center")
    ax.text(0.78, header_y, "CONTEXT", fontsize=10.5, color=DEFAULT_STYLE.muted_text, fontweight="bold", ha="left", va="center")
    ax.plot([0.07, 0.93], [0.792, 0.792], color=DEFAULT_STYLE.grid, alpha=0.45, linewidth=1.0)

    top_value = float(rows[definition.primary_metric.key].abs().max()) if not rows.empty else 1.0
    if top_value == 0:
        top_value = 1.0
    start_y = 0.74
    row_h = 0.058
    for index, row in rows.iterrows():
        y = start_y - index * row_h
        if index % 2 == 0:
            ax.add_patch(Rectangle((0.07, y - 0.027), 0.86, 0.045, color="#17212A", alpha=0.42, linewidth=0))
        rank = int(row["rank"])
        if rank <= 3:
            ax.add_patch(FancyBboxPatch((0.072, y - 0.019), 0.034, 0.034, boxstyle="round,pad=0.004,rounding_size=0.006", linewidth=0, facecolor=DEFAULT_STYLE.accent, alpha=0.92))
            rank_color = DEFAULT_STYLE.background
            rank_weight = "bold"
        else:
            rank_color = DEFAULT_STYLE.muted_text
            rank_weight = "bold"
        ax.text(0.089, y, str(rank), fontsize=12.5, color=rank_color, fontweight=rank_weight, ha="center", va="center")

        player = _player_display(row)
        ax.text(0.135, y, player, fontsize=_fit_text_size(player, base=14.0, max_chars=27, minimum=10.7), color=DEFAULT_STYLE.text, fontweight="bold", ha="left", va="center")

        value = float(row[definition.primary_metric.key])
        bar_width = 0.118 * max(value / top_value, 0) if use_bars else 0
        if use_bars:
            ax.add_patch(FancyBboxPatch((0.635, y - 0.018), bar_width, 0.035, boxstyle="round,pad=0.003,rounding_size=0.006", linewidth=0, facecolor=DEFAULT_STYLE.accent, alpha=0.18))
        ax.text(0.64, y, definition.primary_metric.formatter(row[definition.primary_metric.key]), fontsize=16.5, color=DEFAULT_STYLE.text, fontweight="bold", ha="left", va="center")
        ax.text(0.78, y, _context_text(definition, row), fontsize=11.5, color=DEFAULT_STYLE.muted_text, ha="left", va="center")

    ax.text(0.07, 0.04, f"First & Thirty | PFF data | {label}", fontsize=10.5, color=DEFAULT_STYLE.muted_text, ha="left", va="bottom")
    save_png(fig, output_path)
    return output_path


def leaderboard_csv_columns(definition: LeaderboardDefinition) -> list[str]:
    cols = ["rank", "player_name", "team", definition.primary_metric.key]
    for column in definition.context_columns:
        if column.key not in cols:
            cols.append(column.key)
    return cols


def build_leaderboard(
    definition: LeaderboardDefinition,
    data: dict[str, pd.DataFrame],
    output_dir: Path,
    *,
    season: int,
    week: int,
    use_bars: bool = True,
    period_label: str | None = None,
) -> LeaderboardResult:
    population = definition.data_builder(data)
    rows = select_top_n(definition, population)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / f"{definition.output_filename}.csv"
    png_path = output_dir / f"{definition.output_filename}.png"
    rows[leaderboard_csv_columns(definition)].to_csv(csv_path, index=False)
    render_leaderboard_png(definition, rows, png_path, season=season, week=week, use_bars=use_bars, period_label=period_label)
    return LeaderboardResult(definition=definition, rows=rows, png_path=png_path, csv_path=csv_path)


def manifest_entry(result: LeaderboardResult) -> dict[str, object]:
    definition = result.definition
    leader = result.rows.iloc[0]
    return {
        "id": definition.id,
        "title": definition.title,
        "qualifier": definition.qualifier,
        "ranking_metric": definition.ranking_metric,
        "sort_direction": definition.sort_direction,
        "row_count": int(len(result.rows)),
        "png_path": str(result.png_path),
        "csv_path": str(result.csv_path),
        "leader": str(leader["player_name"]),
        "leader_value": definition.primary_metric.formatter(leader[definition.primary_metric.key]),
    }


def write_manifest(results: Iterable[LeaderboardResult], path: Path) -> Path:
    payload = [manifest_entry(result) for result in results]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _facts_for_result(result: LeaderboardResult) -> list[str]:
    rows = result.rows
    definition = result.definition
    hooks: list[str] = []
    if len(rows) >= 2:
        leader = rows.iloc[0]
        second = rows.iloc[1]
        hooks.append(
            f"{leader['player_name']} led {definition.title.lower()} at {definition.primary_metric.formatter(leader[definition.primary_metric.key])}; No. 2 was {second['player_name']} at {definition.primary_metric.formatter(second[definition.primary_metric.key])}."
        )
    for _, row in rows.head(3).iterrows():
        hooks.append(
            f"{row['player_name']} ranked {int(row['rank'])} with {definition.primary_metric.formatter(row[definition.primary_metric.key])} and {_context_text(definition, row)}."
        )
    return hooks[:5]


def write_content_ideas(results: Iterable[LeaderboardResult], path: Path) -> Path:
    results = list(results)
    lines = ["# Week 1 Leaderboard Content Ideas", ""]
    player_counts: dict[str, int] = {}
    for result in results:
        for player in result.rows["player_name"]:
            player_counts[str(player)] = player_counts.get(str(player), 0) + 1
    repeated = sorted(player for player, count in player_counts.items() if count > 1)
    if repeated:
        lines.append("## Cross-Leaderboard Notes")
        for player in repeated[:8]:
            boards = [result.definition.title for result in results if player in set(result.rows["player_name"])]
            lines.append(f"- {player} appeared on {len(boards)} leaderboards: {', '.join(boards)}.")
        lines.append("")
    for result in results:
        lines.append(f"## {result.definition.title}")
        for hook in _facts_for_result(result):
            lines.append(f"- {hook}")
        lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return path


def build_all_leaderboards(
    data: dict[str, pd.DataFrame],
    output_dir: Path,
    *,
    season: int,
    week: int,
    use_bars: bool = True,
    period_label: str | None = None,
) -> list[LeaderboardResult]:
    definitions = leaderboard_definitions((period_label or f"Week {week}").replace(f"{season} ", ""))
    results = [build_leaderboard(definition, data, output_dir, season=season, week=week, use_bars=use_bars, period_label=period_label) for definition in definitions]
    write_manifest(results, output_dir / "manifest.json")
    write_content_ideas(results, output_dir / "content_ideas.md")
    return results
