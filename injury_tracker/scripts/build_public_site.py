from __future__ import annotations

import argparse
import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .injury_schema import PROJECT_ROOT, load_teams
from .review import (
    POSITION_GROUP_ORDER,
    ReviewPaths,
    build_game_id,
    build_stale_review_info,
    default_review_paths,
    latest_processed_file,
    load_json_rows,
    load_review_status,
    status_key,
    status_reviewed,
)
from .schedule_context import ScheduleGameContext, load_schedule_context
from .week_config import resolve_season_week


PUBLIC_PLAYER_FIELDS = {
    "player_name",
    "team",
    "opponent",
    "position",
    "position_group",
    "section",
    "injury",
    "practice",
    "designation",
    "reserve_status",
    "reserve_transaction_date",
    "designated_for_return",
    "source",
    "ft_note",
}

RESERVE_STATUSES = {"IR", "PUP", "NFI", "OTHER_RESERVE"}
BLANK_DESIGNATIONS = {"", "(-)", "-", "NONE", "NULL", "N/A"}
ET = ZoneInfo("America/New_York")


def default_reviewed_path(season: int, week: int) -> Path:
    return PROJECT_ROOT / "data" / "reviewed" / str(season) / f"week_{week:02d}" / "reviewed_players.json"


def default_review_status_path() -> Path:
    return PROJECT_ROOT / "data" / "manual" / "review_status.csv"


def default_output_root() -> Path:
    return PROJECT_ROOT / "docs" / "injuries"


def build_public_site(
    season: int,
    week: int,
    *,
    reviewed_path: Path | None = None,
    review_population_path: Path | None = None,
    review_status_path: Path | None = None,
    output_root: Path | None = None,
    contexts: list[ScheduleGameContext] | None = None,
    manifest_path: Path | None = None,
    generated_at: datetime | None = None,
    print_summary: bool = True,
) -> dict[str, Any]:
    reviewed_path = reviewed_path or default_reviewed_path(season, week)
    review_population_path = review_population_path or reviewed_path.with_name("review_population.json")
    review_status_path = review_status_path or default_review_status_path()
    output_root = output_root or default_output_root()
    contexts = contexts if contexts is not None else load_schedule_context()
    manifest_path = manifest_path or optional_latest_processed_file(season, week, "manifest.json")
    generated_at = generated_at or datetime.now(timezone.utc)

    records = load_json_rows(reviewed_path) if reviewed_path.exists() else []
    population_records = load_json_rows(review_population_path) if review_population_path and review_population_path.exists() else records
    statuses = load_review_status(review_status_path)
    stale_info = public_stale_info(season, week, population_records, statuses)
    report_statuses = load_report_statuses(manifest_path)
    view_model = build_public_view_model(
        season,
        week,
        records,
        statuses=statuses,
        stale_info=stale_info,
        contexts=contexts,
        report_statuses=report_statuses,
        generated_at=generated_at,
    )
    html = render_html(view_model)

    archive_dir = output_root / str(season) / f"week_{week:02d}"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_html = archive_dir / "index.html"
    archive_model = archive_dir / "public_view_model.json"
    archive_html.write_text(html, encoding="utf-8")
    archive_model.write_text(json.dumps(view_model, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    current_html = output_root / "index.html"
    current_model = output_root / "public_view_model.json"
    output_root.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(archive_html, current_html)
    shutil.copyfile(archive_model, current_model)

    summary = {
        "season": season,
        "week": week,
        "archive_html": str(archive_html),
        "current_html": str(current_html),
        "archive_view_model": str(archive_model),
        "current_view_model": str(current_model),
        "games": len(view_model["games"]),
        "reviewed_games": sum(1 for game in view_model["games"] if game["reviewed"]),
        "stale_games": sum(1 for game in view_model["games"] if game["stale_review"]),
        "public_players": sum(len(team["current_injuries"]) + len(team["reserve_players"]) for game in view_model["games"] for team in game["teams"]),
    }
    if print_summary:
        print(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def build_public_view_model(
    season: int,
    week: int,
    records: list[dict[str, Any]],
    *,
    statuses: dict[str, dict[str, str]],
    stale_info: dict[str, dict[str, Any]] | None = None,
    contexts: list[ScheduleGameContext],
    report_statuses: dict[str, str],
    generated_at: datetime,
) -> dict[str, Any]:
    team_info = public_team_info()
    games = schedule_games(season, week, contexts)
    records_by_game_team: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        if int(record.get("season") or 0) != season or int(record.get("week") or 0) != week:
            continue
        if not truthy(record.get("final_include")):
            continue
        records_by_game_team[(str(record.get("game_id") or ""), str(record.get("team") or ""))].append(record)

    public_games = []
    for game in games:
        stale = bool((stale_info or {}).get(game["game_id"], {}).get("stale"))
        reviewed = status_reviewed(statuses.get(status_key(season, week, "GAME", game["game_id"], ""))) and not stale
        public_teams = []
        for team in [game["away_team"], game["home_team"]]:
            team_records = records_by_game_team.get((game["game_id"], team), []) if reviewed else []
            current, reserve = public_team_players(team_records, team=team)
            status = report_statuses.get(team, "UNKNOWN")
            public_teams.append(
                {
                    "team": team,
                    "team_name": team_info.get(team, {}).get("full_name") or team,
                    "injury_report_url": team_info.get(team, {}).get("injury_report_url") or "",
                    "opponent": game["home_team"] if team == game["away_team"] else game["away_team"],
                    "current_injuries": current,
                    "reserve_players": reserve,
                    "injury_report_status": status,
                    "report_available": status == "SUCCESS_CURRENT",
                }
            )
        public_games.append(
            {
                "game_id": game["game_id"],
                "anchor": game["game_id"].lower(),
                "matchup": f'{game["away_team"]} at {game["home_team"]}',
                "game_date": game.get("game_date"),
                "kickoff": game.get("kickoff"),
                "kickoff_display": format_kickoff(game.get("kickoff"), game.get("game_date")),
                "reviewed": reviewed,
                "stale_review": stale,
                "teams": public_teams,
            }
        )

    return {
        "season": season,
        "week": week,
        "title": f"NFL Week {week} Injury Tracker",
        "subtitle": f"Key injuries, practice participation, reserve status, and First & Thirty notes for every Week {week} matchup.",
        "generated_at_utc": generated_at.astimezone(timezone.utc).isoformat(),
        "generated_at_et": generated_at.astimezone(ET).strftime("%Y-%m-%d %H:%M %Z"),
        "games": public_games,
        "nav": [{"anchor": game["anchor"], "label": game["matchup"], "reviewed": game["reviewed"], "stale_review": game["stale_review"]} for game in public_games],
    }


def schedule_games(season: int, week: int, contexts: list[ScheduleGameContext]) -> list[dict[str, Any]]:
    pairs: dict[tuple[str, str], ScheduleGameContext] = {}
    for context in contexts:
        if context.season != season or context.week != week:
            continue
        key = (context.away_team, context.home_team)
        if key not in pairs or context.home_away == "HOME":
            pairs[key] = context
    games = []
    for (away, home), context in pairs.items():
        games.append(
            {
                "game_id": build_game_id(season, week, context, home, away),
                "away_team": away,
                "home_team": home,
                "game_date": context.game_date,
                "kickoff": context.kickoff,
            }
        )
    return sorted(games, key=lambda game: (game.get("kickoff") or game.get("game_date") or "", game["game_id"]))


def public_team_players(records: list[dict[str, Any]], *, team: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    current = []
    reserve = []
    for record in records:
        player = public_player(record, team=team)
        unexpected = set(player) - PUBLIC_PLAYER_FIELDS
        if unexpected:
            raise ValueError(f"Public player leaked internal fields: {sorted(unexpected)}")
        if player["section"] == "reserve":
            reserve.append(player)
        else:
            current.append(player)
    return sort_public_players(current), sort_public_players(reserve)


def public_player(record: dict[str, Any], *, team: str) -> dict[str, Any]:
    reserve_status = clean_text(record.get("reserve_status"))
    raw_reserve = clean_text(record.get("raw_roster_status"))
    is_reserve = bool(reserve_status in RESERVE_STATUSES or ("Reserve/" in raw_reserve if raw_reserve else False))
    return {
        "player_name": clean_text(record.get("player_name")),
        "team": team,
        "opponent": clean_text(record.get("opponent")),
        "position": clean_text(record.get("display_position") or record.get("canonical_position") or record.get("position_group")),
        "position_group": clean_text(record.get("position_group") or "ST"),
        "section": "reserve" if is_reserve else "current",
        "injury": clean_text(record.get("display_injury") or record.get("injury")),
        "practice": clean_text(record.get("latest_practice")),
        "designation": public_designation(record.get("game_status")),
        "reserve_status": raw_reserve or reserve_status,
        "reserve_transaction_date": format_date(record.get("reserve_transaction_date")),
        "designated_for_return": truthy(record.get("designated_for_return")),
        "source": public_source(record.get("source_memberships")),
        "ft_note": clean_text(record.get("ft_note")),
    }


def sort_public_players(players: list[dict[str, Any]]) -> list[dict[str, Any]]:
    order = {group: index for index, group in enumerate(POSITION_GROUP_ORDER)}
    return sorted(players, key=lambda player: (order.get(player["position_group"], 99), player["position"] or "", player["player_name"] or ""))


def render_html(model: dict[str, Any]) -> str:
    games_html = "\n".join(render_game(game) for game in model["games"])
    nav_html = "\n".join(
        f'<a class="nav-link{" pending" if not item["reviewed"] else ""}" href="#{h(item["anchor"])}">{h(item["label"])}</a>'
        for item in model["nav"]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>First &amp; Thirty - {h(model["title"])}</title>
  <style>{CSS}</style>
</head>
<body>
  <header class="topbar">
    <div>
      <p class="eyebrow">First &amp; Thirty</p>
      <h1>{h(model["title"])}</h1>
      <p class="subtitle">{h(model["subtitle"])}</p>
      <p class="updated">Updated {h(model["generated_at_et"])}</p>
    </div>
  </header>
  <nav class="week-nav" aria-label="Game navigation">
    {nav_html}
  </nav>
  <main>
    {games_html}
  </main>
</body>
</html>
"""


def render_game(game: dict[str, Any]) -> str:
    teams = "\n".join(render_team(team, reviewed=game["reviewed"]) for team in game["teams"])
    if game["stale_review"]:
        pending = '<p class="pending-copy">Updated injury information is pending First &amp; Thirty review.</p>'
    elif game["reviewed"]:
        pending = ""
    else:
        pending = '<p class="pending-copy">Pending First &amp; Thirty review.</p>'
    badge = "" if game["reviewed"] else f'<span class="status-pill pending">{"Pending Review" if game["stale_review"] else "Pending"}</span>'
    return f"""<section class="game" id="{h(game["anchor"])}">
  <div class="game-header">
    <div>
      <h2>{h(game["matchup"])}</h2>
      <p>{h(game["kickoff_display"])}</p>
    </div>
    {badge}
  </div>
  {pending}
  <div class="teams">
    {teams}
  </div>
</section>"""


def render_team(team: dict[str, Any], *, reviewed: bool) -> str:
    if not reviewed:
        body = report_status_message(team)
    else:
        current = render_player_section("Current injuries", team["current_injuries"], empty_current_message(team))
        reserve = render_player_section("Reserve / IR", team["reserve_players"], "No tracked reserve players.")
        body = current + reserve
    return f"""<article class="team-card">
  <div class="team-header">
    <h3>{team_heading(team)}</h3>
  </div>
  {body}
</article>"""


def team_heading(team: dict[str, Any]) -> str:
    label = f'{team["team"]} <span>{h(team["team_name"])}</span>'
    url = safe_url(team.get("injury_report_url"))
    if not url:
        return label
    return f'<a class="team-source-link" href="{h(url)}" target="_blank" rel="noopener noreferrer">{label}</a>'


def render_player_section(title: str, players: list[dict[str, Any]], empty_message: str) -> str:
    if not players:
        return f"""<section class="player-section">
  <h4>{h(title)}</h4>
  <p class="empty">{h(empty_message)}</p>
</section>"""
    return f"""<section class="player-section">
  <h4>{h(title)}</h4>
  <div class="player-list">
    {''.join(render_player(player) for player in players)}
  </div>
</section>"""


def render_player(player: dict[str, Any]) -> str:
    meta = []
    if player["injury"]:
        meta.append(player["injury"])
    if player["practice"]:
        meta.append(f'Practice: {player["practice"]}')
    if player["designation"]:
        meta.append(player["designation"])
    if player["reserve_status"]:
        meta.append(player["reserve_status"])
    if player["designated_for_return"]:
        meta.append("Designated for return")
    if player["reserve_transaction_date"]:
        meta.append(f'Listed: {player["reserve_transaction_date"]}')
    note = f'<p class="ft-note"><strong>F&amp;T Note:</strong> {h(player["ft_note"])}</p>' if player["ft_note"] else ""
    return f"""<article class="player">
  <div class="player-main">
    <span class="pos">{h(player["position"])}</span>
    <strong>{h(player["player_name"])}</strong>
  </div>
  <p class="player-meta">{h(' | '.join(meta))}</p>
  {note}
</article>"""


def load_report_statuses(manifest_path: Path | None) -> dict[str, str]:
    if not manifest_path or not manifest_path.exists():
        return {}
    rows = json.loads(manifest_path.read_text(encoding="utf-8"))
    return {str(row.get("team") or ""): str(row.get("current_week_status") or row.get("parse_status") or "UNKNOWN") for row in rows}


def public_stale_info(
    season: int,
    week: int,
    population_records: list[dict[str, Any]],
    statuses: dict[str, dict[str, str]],
) -> dict[str, dict[str, Any]]:
    try:
        paths = default_review_paths(season, week)
    except FileNotFoundError:
        paths = ReviewPaths(
            injury_path=Path("__missing_injury__"),
            reserve_path=Path("__missing_reserve__"),
            output_dir=PROJECT_ROOT / "data" / "reviewed" / str(season) / f"week_{week:02d}",
        )
    return build_stale_review_info(population_records, statuses, paths=paths)


def public_team_info() -> dict[str, dict[str, str]]:
    output = {}
    for team in load_teams():
        output[team["abbr"]] = {
            "full_name": team.get("full_name") or team["abbr"],
            "injury_report_url": safe_url(team.get("injury_report_url")) or "",
        }
    return output


def safe_url(value: Any) -> str | None:
    text = clean_text(value)
    if text.startswith("https://") or text.startswith("http://"):
        return text
    return None


def optional_latest_processed_file(season: int, week: int, filename: str) -> Path | None:
    try:
        return latest_processed_file(season, week, filename)
    except (FileNotFoundError, NotADirectoryError):
        return None


def public_source(source_memberships: Any) -> str:
    source = clean_text(source_memberships)
    if "injury_report" in source and "reserve_roster" in source:
        return "injury_report|reserve_roster"
    if "reserve_roster" in source:
        return "reserve_roster"
    if "manual_player" in source:
        return "manual_player"
    return "injury_report"


def report_status_message(team: dict[str, Any]) -> str:
    if team.get("injury_report_status") == "NO_REPORT_YET":
        return '<p class="empty">Official injury report not yet available. Player list pending review.</p>'
    return '<p class="empty">Player list pending review.</p>'


def empty_current_message(team: dict[str, Any]) -> str:
    if team.get("injury_report_status") == "NO_REPORT_YET":
        return "Official injury report not yet available."
    return "No tracked current injuries."


def public_designation(value: Any) -> str:
    text = clean_text(value)
    if text.upper() in BLANK_DESIGNATIONS:
        return ""
    return text


def format_kickoff(kickoff: str | None, game_date: str | None = None) -> str:
    if kickoff:
        try:
            parsed = datetime.fromisoformat(kickoff.replace("Z", "+00:00"))
            local = parsed.astimezone(ET)
            return f"{local.strftime('%a, %b')} {local.day}, {format_time(local)} ET"
        except ValueError:
            pass
    if game_date:
        return game_date
    return "Kickoff TBD"


def format_date(value: Any) -> str:
    text = clean_text(value)
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text[:10])
        return f"{parsed.strftime('%b')} {parsed.day}, {parsed.year}"
    except ValueError:
        return text


def format_time(value: datetime) -> str:
    hour = value.hour % 12 or 12
    return f"{hour}:{value.minute:02d} {value.strftime('%p')}"


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() in {"none", "nan", "null"}:
        return ""
    return text


def truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "include"}


def h(value: Any) -> str:
    return escape(clean_text(value), quote=True)


CSS = """
:root {
  color-scheme: light;
  --bg: #f4f6f8;
  --panel: #ffffff;
  --ink: #17202a;
  --muted: #667085;
  --line: #d9dee7;
  --accent: #155e75;
  --soft: #eef7fa;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: Arial, Helvetica, sans-serif;
  background: var(--bg);
  color: var(--ink);
}
.topbar {
  padding: 24px clamp(16px, 4vw, 44px) 18px;
  background: #101820;
  color: #fff;
}
.eyebrow {
  margin: 0 0 6px;
  color: #9fd5df;
  font-size: 12px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0;
}
h1, h2, h3, h4, p { margin-top: 0; }
h1 { margin-bottom: 8px; font-size: clamp(28px, 4vw, 46px); letter-spacing: 0; }
.updated { margin-bottom: 0; color: #cbd5e1; }
.subtitle {
  max-width: 760px;
  margin-bottom: 8px;
  color: #e5eef5;
  font-size: 15px;
}
.week-nav {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding: 12px clamp(16px, 4vw, 44px);
  background: #fff;
  border-bottom: 1px solid var(--line);
}
.nav-link {
  flex: 0 0 auto;
  padding: 8px 10px;
  border: 1px solid var(--line);
  border-radius: 6px;
  color: var(--accent);
  text-decoration: none;
  font-size: 13px;
  font-weight: 700;
}
.nav-link.pending { color: var(--muted); }
main { padding: 18px clamp(12px, 3vw, 36px) 42px; }
.game {
  max-width: 1120px;
  margin: 0 auto 20px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  overflow: hidden;
}
.game-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 18px;
  border-bottom: 1px solid var(--line);
}
.game-header h2 { margin-bottom: 4px; font-size: 22px; letter-spacing: 0; }
.game-header p { margin-bottom: 0; color: var(--muted); }
.status-pill {
  flex: 0 0 auto;
  border-radius: 999px;
  padding: 5px 9px;
  font-size: 12px;
  font-weight: 700;
}
.status-pill.reviewed { color: #0f5132; background: #d1e7dd; }
.status-pill.pending { color: #664d03; background: #fff3cd; }
.pending-copy { margin: 14px 18px 0; color: var(--muted); }
.teams {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0;
}
.team-card {
  min-width: 0;
  padding: 16px 18px 18px;
}
.team-card + .team-card { border-left: 1px solid var(--line); }
.team-header h3 { margin-bottom: 14px; font-size: 18px; letter-spacing: 0; }
.team-header span { display: block; color: var(--muted); font-size: 13px; font-weight: 400; }
.team-source-link {
  color: inherit;
  text-decoration: underline;
  text-decoration-style: dotted;
  text-underline-offset: 3px;
}
.player-section + .player-section { margin-top: 18px; }
.player-section h4 {
  margin-bottom: 8px;
  color: var(--muted);
  font-size: 12px;
  text-transform: uppercase;
  letter-spacing: 0;
}
.player {
  padding: 10px 0;
  border-top: 1px solid var(--line);
}
.player-main {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.pos {
  min-width: 36px;
  color: var(--accent);
  font-size: 12px;
  font-weight: 800;
}
.player-meta {
  margin: 4px 0 0 44px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.35;
}
.ft-note {
  margin: 6px 0 0 44px;
  padding: 8px 10px;
  background: var(--soft);
  border-left: 3px solid var(--accent);
  color: #1f2937;
  font-size: 13px;
  line-height: 1.35;
}
.empty {
  margin-bottom: 0;
  color: var(--muted);
  font-size: 13px;
}
@media (max-width: 760px) {
  .teams { grid-template-columns: 1fr; }
  .team-card + .team-card {
    border-left: 0;
    border-top: 1px solid var(--line);
  }
  .game-header { flex-direction: column; }
  .player-meta, .ft-note { margin-left: 0; }
}
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the public static injury tracker page from reviewed data.")
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--config", type=Path, help="JSON file with season/week. Defaults to injury_tracker/config/current_week.json.")
    parser.add_argument("--output-root", type=Path, default=None)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    season, week = resolve_season_week(args)
    build_public_site(season, week, output_root=args.output_root)


if __name__ == "__main__":
    main()
