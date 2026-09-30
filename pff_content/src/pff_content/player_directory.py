from __future__ import annotations

import csv
import json
import re
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .client import PFFClient


@dataclass(frozen=True)
class PlayerSearchRequest:
    official_name: str
    search_name: str
    aliases: tuple[str, ...] = ()


def build_player_directory(
    requests: list[PlayerSearchRequest],
    *,
    season: int,
    week: int,
    output_dir: Path,
    client: PFFClient | None = None,
    request_sleep: float = 0.0,
) -> dict[str, Any]:
    client = client or PFFClient()
    players_by_id = load_existing_directory(output_dir / "players.csv")
    searches = []
    for request in dedupe_requests(requests):
        response = client.get(
            "/v1/players",
            params={"league": "nfl", "name": request.search_name},
            dataset="player_directory",
            season=season,
            week=week,
            table="players",
            use_cache=True,
        )
        players = response.body.get("players", []) if isinstance(response.body, dict) else []
        searches.append(
            {
                "official_name": request.official_name,
                "search_name": request.search_name,
                "aliases": list(request.aliases),
                "cache_hit": response.cache_hit,
                "results": len(players),
            }
        )
        if request_sleep > 0 and not response.cache_hit:
            time.sleep(request_sleep)
        for player in players:
            player_id = clean_id(player.get("id"))
            if not player_id:
                continue
            row = players_by_id.setdefault(player_id, row_from_player(player))
            add_alias(row, request.search_name)
            for alias in request.aliases:
                add_alias(row, alias)
            add_alias(row, request.official_name)
            row["query_names"].add(request.search_name)
            row["official_names"].add(request.official_name)
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "players.csv"
    json_path = output_dir / "players.json"
    rows = finalize_rows(players_by_id)
    write_csv(csv_path, rows)
    json_path.write_text(json.dumps(rows, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"players": len(rows), "searches": searches, "csv": str(csv_path), "json": str(json_path)}


def load_existing_directory(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    output: dict[str, dict[str, Any]] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            player_id = clean_id(row.get("pff_player_id"))
            if not player_id:
                continue
            item = dict(row)
            item["aliases"] = split_pipe(row.get("aliases"))
            item["query_names"] = split_pipe(row.get("query_names"))
            item["official_names"] = split_pipe(row.get("official_names"))
            output[player_id] = item
    return output


def requests_from_names(names: list[str]) -> list[PlayerSearchRequest]:
    return [PlayerSearchRequest(official_name=name, search_name=name) for name in names]


def dedupe_requests(requests: list[PlayerSearchRequest]) -> list[PlayerSearchRequest]:
    seen = set()
    output = []
    for request in requests:
        key = (normalize_name(request.official_name), normalize_name(request.search_name), tuple(sorted(request.aliases)))
        if key in seen:
            continue
        seen.add(key)
        output.append(request)
    return output


def row_from_player(player: dict[str, Any]) -> dict[str, Any]:
    pff_name = player_name(player)
    team = team_abbr(player.get("team"))
    draft_team = team_abbr((player.get("draft") or {}).get("team"))
    return {
        "pff_player_id": clean_id(player.get("id")) or "",
        "pff_player_name": pff_name,
        "normalized_player_name": normalize_name(pff_name),
        "first_name": clean_text(player.get("first_name")),
        "last_name": clean_text(player.get("last_name")),
        "pff_position": clean_text(player.get("position")).upper(),
        "team": team,
        "jersey_number": clean_text(player.get("jersey_number")),
        "college": clean_text(player.get("college")),
        "draft_team": draft_team,
        "aliases": set(),
        "query_names": set(),
        "official_names": set(),
    }


def finalize_rows(players_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for row in players_by_id.values():
        item = dict(row)
        item["aliases"] = "|".join(sorted(row["aliases"]))
        item["query_names"] = "|".join(sorted(row["query_names"]))
        item["official_names"] = "|".join(sorted(row["official_names"]))
        rows.append(item)
    return sorted(rows, key=lambda item: (item["normalized_player_name"], int(item["pff_player_id"])))


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = [
        "pff_player_id",
        "pff_player_name",
        "normalized_player_name",
        "first_name",
        "last_name",
        "pff_position",
        "team",
        "jersey_number",
        "college",
        "draft_team",
        "aliases",
        "query_names",
        "official_names",
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column) for column in columns})


def add_alias(row: dict[str, Any], value: str) -> None:
    normalized = normalize_name(value)
    if normalized and normalized != row["normalized_player_name"]:
        row["aliases"].add(normalized)


def split_pipe(value: Any) -> set[str]:
    return {item.strip() for item in str(value or "").split("|") if item.strip()}


def player_name(player: dict[str, Any]) -> str:
    first = clean_text(player.get("first_name"))
    last = clean_text(player.get("last_name"))
    return f"{first} {last}".strip() or clean_text(player.get("name"))


def team_abbr(team: object) -> str:
    if isinstance(team, dict):
        return clean_text(team.get("abbreviation"))
    return ""


def clean_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith(".0"):
        text = text[:-2]
    return text


def clean_text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value).strip().lower())
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    suffixes = {"jr", "sr", "ii", "iii", "iv", "v"}
    parts = text.split()
    while parts and parts[-1] in suffixes:
        parts.pop()
    return " ".join(parts)
