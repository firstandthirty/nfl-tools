from __future__ import annotations

import argparse
import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

try:
    from .review import (
        append_manual_player,
        default_review_paths,
        game_source_fingerprint,
        load_review_bundle,
        save_decision,
        save_ft_note,
        save_review_status,
    )
    from .injury_schema import load_teams
    from .week_config import resolve_season_week
except ImportError:  # pragma: no cover - allows direct script execution
    from review import (  # type: ignore
        append_manual_player,
        default_review_paths,
        game_source_fingerprint,
        load_review_bundle,
        save_decision,
        save_ft_note,
        save_review_status,
    )
    from injury_schema import load_teams  # type: ignore
    from week_config import resolve_season_week  # type: ignore


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Injury Review</title>
  <style>
    :root { color-scheme: light; --bg:#f7f7f4; --ink:#20211f; --muted:#686c65; --line:#d7d8d2; --panel:#fff; --yes:#176b42; --no:#9c2f2f; --warn:#8a5a00; }
    * { box-sizing: border-box; }
    body { margin:0; font:13px/1.35 system-ui, -apple-system, Segoe UI, sans-serif; background:var(--bg); color:var(--ink); }
    header { position:sticky; top:0; z-index:5; background:#eeeee8; border-bottom:1px solid var(--line); padding:10px 14px; }
    h1 { font-size:18px; margin:0 0 8px; }
    .stats, .filters { display:flex; flex-wrap:wrap; gap:8px; align-items:center; }
    .pill { border:1px solid var(--line); background:var(--panel); padding:4px 8px; border-radius:5px; white-space:nowrap; }
    .filters button, .actions button, .player button, .team-add button { border:1px solid var(--line); background:#fff; padding:4px 8px; border-radius:5px; cursor:pointer; }
    button.active, .include { background:#e8f4ed !important; border-color:#8cbfa4 !important; color:var(--yes); }
    .exclude { background:#f8eaea !important; border-color:#d69a9a !important; color:var(--no); }
    main { padding:12px 14px 32px; }
    .game { margin:0 0 18px; border-top:2px solid #333; padding-top:8px; }
    .game-head { display:flex; justify-content:space-between; gap:12px; align-items:center; margin-bottom:8px; }
    .game-title { font-weight:700; font-size:16px; }
    .teams { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
    .team { background:var(--panel); border:1px solid var(--line); border-radius:6px; padding:8px; }
    .team h3 { margin:0 0 8px; font-size:15px; display:flex; justify-content:space-between; }
    .pos { margin:8px 0; }
    .pos h4 { margin:0 0 3px; font-size:12px; color:var(--muted); border-bottom:1px solid var(--line); }
    .player { display:grid; grid-template-columns: 1.1fr 1.4fr 1.2fr 1.1fr auto; gap:7px; align-items:start; padding:6px 0; border-bottom:1px solid #ededeb; }
    .name { font-weight:650; }
    .small { color:var(--muted); font-size:12px; }
    .tag { display:inline-block; margin:1px 4px 1px 0; padding:1px 5px; border:1px solid var(--line); border-radius:4px; background:#fafafa; font-size:11px; }
    .tag.warn { border-color:#e0bf6a; color:var(--warn); background:#fff8e8; }
    .reviewed { color:var(--yes); }
    .unreviewed { color:var(--warn); }
    .stale { color:var(--no); font-weight:700; }
    .source-link { color:inherit; text-decoration: underline; text-decoration-style:dotted; text-underline-offset:3px; }
    .hidden { display:none !important; }
    input, select, textarea { width:100%; border:1px solid var(--line); border-radius:4px; padding:5px; font:inherit; background:#fff; }
    dialog { width:min(720px, 92vw); border:1px solid var(--line); border-radius:8px; padding:14px; }
    dialog::backdrop { background:rgba(0,0,0,.25); }
    .form-grid { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
    @media (max-width: 900px) { .teams { grid-template-columns:1fr; } .player { grid-template-columns:1fr; } }
  </style>
</head>
<body>
<header>
  <h1 id="title">Injury Review</h1>
  <div class="stats" id="stats"></div>
  <div class="filters" id="filters"></div>
</header>
<main id="app"></main>
<dialog id="addDialog">
  <h3>Add Player</h3>
  <div class="form-grid">
    <label>Team <input id="addTeam"></label>
    <label>Search known player <input id="knownSearch" placeholder="type a name"></label>
  </div>
  <select id="knownList" size="8" style="margin-top:8px"></select>
  <div style="margin:8px 0" class="small">Or add a player missing from all current source data.</div>
  <div class="form-grid">
    <label>Name <input id="manualName"></label>
    <label>Position <input id="manualPosition"></label>
    <label>Injury/status note <input id="manualInjury"></label>
    <label>Game status <input id="manualGameStatus"></label>
  </div>
  <label style="display:block;margin-top:8px">Manual note <textarea id="manualNote"></textarea></label>
  <div class="actions" style="margin-top:10px">
    <button onclick="includeKnown()">Include selected known player</button>
    <button onclick="addManual()">Add missing player</button>
    <button onclick="document.getElementById('addDialog').close()">Close</button>
  </div>
</dialog>
<script>
let bundle = null;
let filter = 'all';
let addTeam = '';

const filters = [
  ['all','Show all'], ['auto_yes','Automated YES'], ['manual_excluded','Manual excluded'],
  ['manual_added','Manual added'], ['reserve_only','Reserve only'], ['injury_only','Injury report only'],
  ['fallback','2025 fallback']
];

async function load() {
  const res = await fetch('/api/bundle');
  bundle = await res.json();
  render();
}

function render() {
  document.getElementById('title').textContent = `Injury Review - ${bundle.season} Week ${bundle.week}`;
  const s = bundle.summary;
  document.getElementById('stats').innerHTML = [
    `Data updated: ${s.data_updated_at_et || 'unknown'}`,
    `Automated candidates: ${s.automated_candidates}`,
    `Included: ${s.included}`,
    `Excluded: ${s.excluded}`,
    `Unreviewed/default: ${s.unreviewed_default_include}`,
      `Games reviewed: ${s.games_reviewed}/${s.games_represented}`,
      `Stale games: ${s.games_stale || 0}`,
    `Fully reviewed: ${s.week_fully_reviewed ? 'yes' : 'no'}`
  ].map(x => `<span class="pill">${x}</span>`).join('');
  document.getElementById('filters').innerHTML = filters.map(([id,label]) => `<button class="${filter===id?'active':''}" onclick="filter='${id}'; render()">${label}</button>`).join('');
  document.getElementById('app').innerHTML = bundle.grouped.map(renderGame).join('');
}

function renderGame(game) {
  const teams = game.teams.map(renderTeam).join('');
  return `<section class="game">
    <div class="game-head">
      <div class="game-title">${game.away_team || ''} @ ${game.home_team || ''} <span class="small">${game.game_date || ''}</span> ${reviewStatus(game)}</div>
      <div class="actions"><button onclick="markGame('${game.game_id}')">Mark game reviewed</button></div>
    </div>
    <div class="teams">${teams}</div>
  </section>`;
}

function renderTeam(team) {
  const groups = team.groups.map(renderGroup).join('');
  return `<section class="team">
    <h3>${teamLink(team.team)} <span>${team.reviewed ? 'reviewed' : 'unreviewed'}</span></h3>
    <div class="actions"><button onclick="openAdd('${team.team}')">Add Player</button><button onclick="markTeam('${team.team}')">Mark team reviewed</button></div>
    ${groups}
  </section>`;
}

function reviewStatus(game) {
  if (game.stale_review) return '<span class="stale">needs re-review</span>';
  if (game.reviewed) return '<span class="reviewed">reviewed</span>';
  return '<span class="unreviewed">unreviewed</span>';
}

function teamLink(team) {
  const info = (bundle.team_info || {})[team] || {};
  if (!info.injury_report_url) return escapeHtml(team);
  return `<a class="source-link" href="${escapeHtml(info.injury_report_url)}" target="_blank" rel="noopener noreferrer">${escapeHtml(team)}</a>`;
}

function renderGroup(group) {
  const players = group.players.filter(matchesFilter).map(renderPlayer).join('');
  if (!players) return '';
  return `<div class="pos"><h4>${group.position_group}</h4>${players}</div>`;
}

function renderPlayer(p) {
  const source = p.source_labels.map(x => `<span class="tag">${x.replace('_',' ')}</span>`).join('');
  const fallback = p.prior_season_fallback_used ? '<span class="tag warn">2025 fallback</span>' : '';
  const reviewed = p.explicitly_reviewed ? '<span class="tag">reviewed</span>' : '<span class="tag warn">default</span>';
  const reserve = p.canonical_roster_status ? `<div>${p.raw_roster_status || p.canonical_roster_status}${p.designated_for_return ? ' DFR' : ''}</div><div class="small">${p.reserve_transaction_date || ''}</div>` : '';
  return `<div class="player" data-id="${p.record_id}">
    <div><div class="name">${p.player_name}</div><div class="small">${p.display_position || p.canonical_position || ''} ${p.pff_position ? `PFF ${p.pff_position}` : ''}</div>${source}${fallback}${reviewed}</div>
    <div><div>${p.display_injury || ''}</div><div class="small">Practice: ${p.latest_practice || ''} &nbsp; Game: ${p.game_status || ''}</div></div>
    <div>${reserve}<div class="small">${(p.candidate_reasons || []).join(', ')}</div></div>
    <div><div>Snap: ${fmtPct(p.relevant_snap_pct)}</div><div class="small">Source season: ${p.participation_source_season || ''}</div></div>
    <div class="actions"><button class="include" onclick="decide('${p.record_id}','INCLUDE')">INCLUDE</button><button class="exclude" onclick="decide('${p.record_id}','EXCLUDE')">EXCLUDE</button></div>
    <div style="grid-column:1 / -1"><label class="small">F&amp;T Note</label><textarea rows="2" onchange="saveNote('${p.record_id}', this.value)" placeholder="Human editorial note only">${escapeHtml(p.ft_note || '')}</textarea></div>
  </div>`;
}

function matchesFilter(p) {
  if (filter === 'auto_yes') return p.automated_candidate;
  if (filter === 'manual_excluded') return p.manual_decision === 'EXCLUDE';
  if (filter === 'manual_added') return p.source_memberships.manual_player;
  if (filter === 'reserve_only') return p.source_memberships.reserve_roster && !p.source_memberships.injury_report;
  if (filter === 'injury_only') return p.source_memberships.injury_report && !p.source_memberships.reserve_roster;
  if (filter === 'fallback') return p.prior_season_fallback_used;
  return true;
}

function fmtPct(v) {
  if (v === null || v === undefined || v === '') return '';
  return `${(Number(v) * 100).toFixed(1)}%`;
}

function record(id) {
  return bundle.records.find(p => p.record_id === id);
}

async function decide(id, decision) {
  const p = record(id);
  await post('/api/decision', {
    team: p.team, player_name: p.player_name, normalized_player_name: p.normalized_player_name,
    pff_player_id: p.pff_player_id, decision
  });
}

async function saveNote(id, ft_note) {
  const p = record(id);
  await post('/api/note', {
    team: p.team, player_name: p.player_name, normalized_player_name: p.normalized_player_name,
    pff_player_id: p.pff_player_id, ft_note
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

async function markGame(game_id) {
  await post('/api/status', { scope:'GAME', game_id, reviewed:true });
}

async function markTeam(team) {
  const game = bundle.grouped.find(g => g.teams.some(t => t.team === team));
  await post('/api/status', { scope:'TEAM', game_id:game.game_id, team, reviewed:true });
}

function openAdd(team) {
  addTeam = team;
  document.getElementById('addTeam').value = team;
  document.getElementById('knownSearch').value = '';
  renderKnownOptions();
  document.getElementById('addDialog').showModal();
}

function renderKnownOptions() {
  const q = document.getElementById('knownSearch').value.toLowerCase();
  const options = bundle.manual_add_options
    .filter(p => p.team === addTeam && (!q || p.player_name.toLowerCase().includes(q)))
    .slice(0, 80)
    .map(p => `<option value="${p.record_id}">${p.player_name} - ${p.canonical_position || ''} - ${(p.candidate_reasons || []).join(', ')}</option>`)
    .join('');
  document.getElementById('knownList').innerHTML = options;
}
document.getElementById('knownSearch').addEventListener('input', renderKnownOptions);

async function includeKnown() {
  const id = document.getElementById('knownList').value;
  if (!id) return;
  await decide(id, 'INCLUDE');
  document.getElementById('addDialog').close();
}

async function addManual() {
  await post('/api/manual_player', {
    team: document.getElementById('addTeam').value,
    player_name: document.getElementById('manualName').value,
    source_position: document.getElementById('manualPosition').value,
    injury: document.getElementById('manualInjury').value,
    game_status: document.getElementById('manualGameStatus').value,
    note: document.getElementById('manualNote').value
  });
  document.getElementById('addDialog').close();
}

async function post(url, body) {
  const res = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body) });
  if (!res.ok) alert(await res.text());
  await load();
}

load();
</script>
</body>
</html>"""


class ReviewHandler(BaseHTTPRequestHandler):
    server: "ReviewServer"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_text(HTML, "text/html; charset=utf-8")
        elif parsed.path == "/api/bundle":
            self.send_json(self.server.bundle())
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        try:
            payload = self.read_json()
            if self.path == "/api/decision":
                save_decision(
                    season=self.server.season,
                    week=self.server.week,
                    team=payload["team"],
                    player_name=payload["player_name"],
                    normalized_player_name=payload.get("normalized_player_name"),
                    pff_player_id=payload.get("pff_player_id"),
                    decision=payload["decision"],
                    note=payload.get("note"),
                    display_position=payload.get("display_position"),
                    display_injury=payload.get("display_injury"),
                    path=self.server.paths.review_decisions_path,
                )
                self.send_json({"ok": True})
            elif self.path == "/api/status":
                source_fingerprint = None
                if str(payload.get("scope") or "").upper() == "GAME" and bool(payload.get("reviewed", True)):
                    bundle = load_review_bundle(self.server.season, self.server.week, self.server.paths)
                    source_fingerprint = game_source_fingerprint(bundle["records"], payload["game_id"])
                save_review_status(
                    season=self.server.season,
                    week=self.server.week,
                    scope=payload["scope"],
                    game_id=payload["game_id"],
                    team=payload.get("team") or "",
                    opponent=payload.get("opponent") or "",
                    reviewed=bool(payload.get("reviewed", True)),
                    note=payload.get("note"),
                    source_fingerprint=source_fingerprint,
                    path=self.server.paths.review_status_path,
                )
                self.send_json({"ok": True})
            elif self.path == "/api/note":
                save_ft_note(
                    season=self.server.season,
                    week=self.server.week,
                    team=payload["team"],
                    player_name=payload["player_name"],
                    normalized_player_name=payload.get("normalized_player_name"),
                    pff_player_id=payload.get("pff_player_id"),
                    ft_note=payload.get("ft_note") or "",
                    path=self.server.paths.review_decisions_path,
                )
                self.send_json({"ok": True})
            elif self.path == "/api/manual_player":
                row = append_manual_player(
                    season=self.server.season,
                    week=self.server.week,
                    team=payload["team"].strip().upper(),
                    player_name=payload["player_name"],
                    source_position=payload.get("source_position"),
                    injury=payload.get("injury"),
                    game_status=payload.get("game_status"),
                    note=payload.get("note"),
                    path=self.server.paths.manual_players_path,
                )
                save_decision(
                    season=self.server.season,
                    week=self.server.week,
                    team=row["team"],
                    player_name=row["player"],
                    normalized_player_name=None,
                    pff_player_id=None,
                    decision="INCLUDE",
                    note=row.get("manual_note"),
                    path=self.server.paths.review_decisions_path,
                )
                self.send_json({"ok": True})
            else:
                self.send_error(404)
        except Exception as exc:  # pragma: no cover - surfaced in local UI
            self.send_error(400, str(exc))

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length).decode("utf-8") or "{}")

    def send_json(self, value: Any) -> None:
        body = json.dumps(json_ready(value), sort_keys=True).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, value: str, content_type: str) -> None:
        body = value.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


class ReviewServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler], *, season: int, week: int):
        super().__init__(address, handler)
        self.season = season
        self.week = week
        self.paths = default_review_paths(season, week)

    def bundle(self) -> dict[str, Any]:
        bundle = load_review_bundle(self.season, self.week, self.paths)
        return {
            "season": bundle["season"],
            "week": bundle["week"],
            "summary": bundle["summary"],
            "records": bundle["records"],
            "primary_records": bundle["primary_records"],
            "manual_add_options": bundle["manual_add_options"],
            "grouped": bundle["grouped"],
            "team_info": team_info(),
        }


def json_ready(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value


def team_info() -> dict[str, dict[str, str]]:
    output = {}
    for team in load_teams():
        url = safe_url(team.get("injury_report_url"))
        output[team["abbr"]] = {
            "full_name": team.get("full_name") or team["abbr"],
            "injury_report_url": url or "",
        }
    return output


def safe_url(value: Any) -> str | None:
    text = str(value or "").strip()
    if text.startswith("https://") or text.startswith("http://"):
        return text
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch the local injury tracker manual review app.")
    parser.add_argument("--season", type=int)
    parser.add_argument("--week", type=int)
    parser.add_argument("--config", type=Path, help="JSON file with season/week. Defaults to injury_tracker/config/current_week.json.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    season, week = resolve_season_week(args)
    server = ReviewServer((args.host, args.port), ReviewHandler, season=season, week=week)
    url = f"http://{args.host}:{args.port}/"
    print(f"Review app running at {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
