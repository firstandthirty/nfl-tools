# PFF API Discovery For Weekly NFL Content Research

Discovery date: 2026-09-14  
Repository root: `C:\Users\brady\OneDrive\Desktop\nfl-tools`  
New project: `C:\Users\brady\OneDrive\Desktop\nfl-tools\pff_content`

This discovery is architecture only. It does not implement the weekly analytics pipeline and does not change any `player_props` betting or grading artifacts.

## 1. Authentication Findings

Authentication uses:

```text
Authorization: Bearer <PFF_API_KEY>
```

The current key is loaded from `../player_props/.env` by `scripts/test_pff_connection.py`. The script prints status, safe account fields, safe response headers, and small response-shape samples. It never prints the key.

Observed auth result from `scripts/test_pff_connection.py` on 2026-09-14:

- `GET /v1/auth/whoami`: status `200`
- tier: `pro`
- entitled: `true`
- credential: API key
- safe sample requests returned populated Week 1 2026 tables for `games`, `passing_summary`, and `receiving_summary`

## 2. Existing nfl-tools Code To Reuse

Reuse from `player_props`:

- Secure `.env` loading pattern from `scripts/04_analysis/audit_pff_api_capabilities.py` and `scripts/05_grading/grade_player_props.py`.
- PFF request pattern: `urllib.request`, Bearer token header, JSON decode, and HTTP error body handling.
- Safe-header filtering so rate-limit/request metadata can be logged without secrets.
- Raw response cache convention: write JSON response plus adjacent metadata containing endpoint, captured timestamp, response hash, source, and safe headers.
- OpenAPI inventory logic from `audit_pff_api_capabilities.py`, especially operation/path inventory from the official schema.
- Team/game/status handling from the player-prop grader: `/v1/games`, PFF franchise IDs, team abbreviation/name handling.
- `props_env` can run the discovery scripts. The new project currently needs only standard library plus `pandas`.

Do not reuse from `player_props`:

- Betting policy, model thresholds, odds logic, or grading outputs. This project is content discovery, not betting.
- Prospective model snapshots as inputs. PFF content should stand on PFF stat tables and optional future editorial configuration.

Repository `.gitignore` patterns already ignore `.env`, virtual environments, `__pycache__`, and generated raw data. `pff_content/.gitignore` repeats those local protections.

## 3. PFF API Discovery Method

The official OpenAPI schema is the source of truth:

- `https://developer.pff.com/openapi.json`
- fallback observed in existing audit: `https://api.pff.com/openapi.json`

Existing inventory found 70 operations. Relevant endpoint families:

- `v1/ref`: games, leagues, players
- `v1/facet`: league-wide player/team leaderboards
- `v1/player`: one-player reports
- `v1/signature`: signature stat leaderboards
- `v2/teams`: team directory, schedule, roster, leaders, reports, stats

Small authenticated Week 1 2026 samples were cached under:

```text
pff_content/data/raw/pff/discovery/2026/week_01/20260914T150924Z/
```

Previously cached player-prop grading samples under `player_props/data/raw/results/pff/2026/week_01/20260914T143211Z/` also confirmed `games`, `passing`, `receiving`, `rushing`, `offense`, and roster structures.

## 4. Relevant PFF Endpoints

### Reference And Schedule

`GET /v1/games`

- Version: v1
- Required parameters: `league`, `season`, `week`
- Optional: `franchise_id`
- Response table: `games`
- Level: game
- League-wide request: yes
- Useful fields observed: `id`, `start`, `home_team`, `away_team`, `has_stats`, `lock_status`, `score`, `season`, `week`
- Use: weekly schedule, final/in-progress availability, game IDs for `game_id` filters.

`GET /v1/players`

- Version: v1
- Required parameter: `league`
- Optional: name/player search parameters per OpenAPI.
- Level: player directory
- Use: stable PFF player IDs when one-player drilldowns are needed.

`GET /v2/{league}/teams`

- Version: v2
- Required path parameter: `league`
- Query: `season`
- Level: team
- Use: PFF team/franchise IDs and slugs.

`GET /v2/{league}/teams/{team}/schedule`

- Version: v2
- Required path parameters: `league`, `team`
- Query: `season`
- Level: team schedule
- Team-by-team request: yes
- Use: team-level schedule/results if richer than `/v1/games`.

### QB

`GET /v1/facet/passing/summary`

- Version: v1
- Required parameters: `league`, `season`
- Week filtering: `week`
- Other documented filters: `franchise_id`, `game_id`, `division`, `export`
- Response table: `passing_summary`
- Level: player
- League-wide request: yes
- Relevant fields observed: `attempts`, `completions`, `yards`, `interceptions`, `turnover_worthy_plays`, `twp_rate`, `big_time_throws`, `btt_rate`, `avg_time_to_throw`, `avg_depth_of_target`, `accuracy_percent`, `completion_percent`, `dropbacks`, `sacks`, `sack_percent`, `pressure_to_sack_rate`, `def_gen_pressures`, `qb_rating`, `ypa`, `player`, `player_id`, `position`, `team`, `franchise_id`, `draft_season`
- Availability: core QB passing/process fields are definitely available.

`GET /v1/facet/passing/pressure`

- Version: v1
- Required/filter parameters: same facet pattern, including `league`, `season`, `week`, `franchise_id`, `game_id`, `division`, `export`
- Response: pressure-split passing leaderboard
- Level: player
- League-wide request: yes
- Use: clean-pocket vs pressured performance. Field inventory should be sampled in implementation phase.

`GET /v1/facet/passing/allowed_pressure`

- Version: v1
- Same facet filters.
- Response: pressure-allowed passing leaderboard
- Level: likely player/QB or offense-facing pressure context; verify fields before using.
- Use: pressure faced by QBs if fields align. This needs a sample before production transform.

`GET /v1/facet/passing/depth`

- Use: passing by target depth and aDOT style splits.

`GET /v1/facet/passing/detail`

- Use: detailed QB passing process fields if summary is insufficient.

`GET /v1/facet/signature/passing/time_in_pocket`

- Version: v1
- Required/filter parameters: signature facet pattern
- Response table observed: `time_in_pockets`
- Level: player/QB
- League-wide request: yes
- Relevant fields observed: `avg_ttt_attempts`, `avg_ttt_scrambles`, `dropbacks`, plus less/more time-in-pocket splits for attempts, completions, yards, big-time throws, turnover-worthy plays, sacks, pressure-to-sack rate, average depth of target, QB rating, and accuracy.
- Availability: time-to-throw/time-in-pocket split data is definitely available.

### WR/TE

`GET /v1/facet/receiving/summary`

- Version: v1
- Required/filter parameters: `league`, `season`, `week`, optional `franchise_id`, `game_id`, `division`, `export`
- Response table: `receiving_summary`
- Level: player
- League-wide request: yes
- Relevant fields observed: `targets`, `receptions`, `yards`, `routes`, `yprr`, `avg_depth_of_target`, `contested_targets`, `contested_receptions`, `contested_catch_rate`, `caught_percent`, `drop_rate`, `drops`, `first_downs`, `yards_after_catch_per_reception`, `yards_after_catch`, `pass_plays`, `route_rate`, `inline_snaps`, `slot_snaps`, `wide_snaps`, `player`, `player_id`, `position`, `team`, `franchise_id`, `draft_season`
- Availability: targets, routes, TPRR, YPRR, contested targets, aDOT, and rookie status via `draft_season` are definitely available.
- Target share: not directly observed as a field; can be computed if team target totals are available from the same week/game scope.
- First-read targets: not observed in sampled summary; uncertain.

`GET /v1/facet/receiving/depth`

- Use: target-depth splits for receivers.

`GET /v1/facet/receiving/coverage`

- Use: production versus coverage types; sample before transform.

`GET /v1/facet/receiving/concept`

- Use: concept splits; sample before transform.

`GET /v1/facet/receiving/scheme`

- Use: receiving versus scheme/shell concepts; sample before transform.

### RB

`GET /v1/facet/rushing/summary`

- Version: v1
- Required/filter parameters: `league`, `season`, `week`, optional `franchise_id`, `game_id`, `division`, `export`
- Response table: `rushing_summary`
- Level: player
- League-wide request: yes
- Relevant fields observed: `attempts`, `yards`, `yards_after_contact`, `yco_attempt`, `avoided_tackles`, `elu_rush_mtf`, `elu_recv_mtf`, `explosive`, `breakaway_attempts`, `breakaway_yards`, `breakaway_percent`, `first_downs`, `longest`, `scrambles`, `designed_yards`, `grades_run`, `grades_offense`, `player`, `player_id`, `position`, `team`, `franchise_id`, `draft_season`
- Availability: attempts, YAC, YAC/attempt, missed tackles forced variants, and explosive/breakaway runs are definitely available.

`GET /v1/facet/rushing/direction`

- Use: gap/direction splits; useful for run-game content and matchup articles.

### Offensive Line / Pass Blocking

`GET /v1/facet/offense/pass_blocking`

- Version: v1
- Required/filter parameters: `league`, `season`, `week`, optional `franchise_id`, `game_id`, `division`, `export`
- Response table: `pass_blocking`
- Level: player
- League-wide request: yes
- Relevant fields observed: `snap_counts_pass_block`, `snap_counts_pass_play`, `pressures_allowed`, `sacks_allowed`, `hits_allowed`, `hurries_allowed`, `pbe`, `pass_block_percent`, `grades_pass_block`, true-pass-set versions of snaps, pressures, sacks, hits, hurries, and PBE.
- Availability: OL pressure/sack/hit/hurry allowed and pass-blocking efficiency are definitely available.

`GET /v1/facet/offense/blocking`

- Use: broader blocking report across run/pass.

`GET /v1/facet/offense/run_blocking`

- Use: run-blocking grades/snaps; useful for OL/run-game content.

### Pass Rush

`GET /v1/facet/defense/pass_rush`

- Version: v1
- Required/filter parameters: `league`, `season`, `week`, optional `franchise_id`, `game_id`, `division`, `export`
- Response table: `pass_rush_summary`
- Level: player
- League-wide request: yes
- Relevant fields observed: `snap_counts_pass_rush`, `snap_counts_pass_play`, `pass_rush_opp`, `pass_rush_wins`, `pass_rush_win_rate`, `total_pressures`, `sacks`, `hits`, `hurries`, `batted_passes`, `prp`, `pass_rush_percent`, `grades_pass_rush_defense`, and true-pass-set equivalents.
- Availability: pass-rush wins/rate, pressures, sacks/hits/hurries, and productivity are definitely available.

`GET /v1/facet/signature/defense/outside_pass_rush`

- Use: edge/outside pass-rush content. Sample before transform.

### Run Defense

`GET /v1/facet/defense/run`

- Version: v1
- Required/filter parameters: `league`, `season`, `week`, optional `franchise_id`, `game_id`, `division`, `export`
- Response table: `run_defense_summary`
- Level: player
- League-wide request: yes
- Relevant fields observed: `snap_counts_run`, `run_stop_opp`, `stops`, `stop_percent`, `tackles`, `assists`, `missed_tackles`, `missed_tackle_rate`, `avg_depth_of_tackle`, `forced_fumbles`, `grades_run_defense`, `grades_tackle`.
- Availability: run stops, run-stop percentage, run-defense snaps, missed tackles are definitely available.
- Tackles for loss: not observed in sampled fields.

### Coverage

`GET /v1/facet/defense/coverage`

- Version: v1
- Required/filter parameters: `league`, `season`, `week`, optional `franchise_id`, `game_id`, `division`, `export`
- Response table: `coverage_summary`
- Level: player
- League-wide request: yes
- Relevant fields observed: `snap_counts_coverage`, `targets`, `receptions`, `yards`, `yards_after_catch`, `interceptions`, `forced_incompletes`, `forced_incompletion_rate`, `pass_break_ups`, `qb_rating_against`, `yards_per_coverage_snap`, `coverage_snaps_per_target`, `coverage_snaps_per_reception`, `avg_depth_of_target`, `catch_rate`, `touchdowns`, `grades_coverage_defense`.
- Availability: coverage targets, catches/yards allowed, INTs, forced incompletions, rating when targeted, YPCS are definitely available.

`GET /v1/facet/defense/coverage_scheme`

- Version: v1
- Response table: `coverage_scheme`
- Level: player
- League-wide request: yes
- Relevant observed field families: `man_*` and `zone_*` coverage snaps, targets, receptions, yards, touchdowns, interceptions, catch rate, forced incompletion rate, YPCS, aDOT, and coverage grades.
- Availability: man/zone player coverage splits are definitely available.
- Cover 0/1/2/3/4/6 usage: not observed in this sampled endpoint.

`GET /v1/facet/defense/coverage_matchup`

- Use: individual coverage matchup content. Sample before transform.

`GET /v1/facet/signature/defense/slot_coverage`

- Use: slot-coverage content. Sample before transform.

### Team Defense

`GET /v2/{league}/teams/stats`

- Version: v2
- Required path parameter: `league`
- Query parameters: `season`, `weekGroup`, `weekIds`, `category`, `scope`, `format`
- Level: team
- League-wide request: yes
- Use: team stat tables. Needs category discovery before transform.

`GET /v2/{league}/teams/{team}/reports/{report}`

- Version: v2
- Required path parameters: `league`, `team`, `report`
- Query parameters: `season`, `weekGroup`, `week`, `weekTo`, `format`
- Level: team/player report
- Team-by-team request: yes
- OpenAPI notes: columns are dynamic and returned in each response's `columns` array; `playerId`, `player`, and `position` are always present.
- Use: team-scoped reports for categories not covered cleanly by v1 facets.

`GET /v2/{league}/teams/{team}/leaders`

- Version: v2
- Required path parameters: `league`, `team`
- Query parameters: `season`, `weekGroup`, `weekIds`, `positionGroup`, `scope`, `format`
- Level: team leaders
- Team-by-team request: yes
- Use: team-level story leads after a league-wide ranking identifies a target team/player.

Team blitz rate, pressure rate, man/zone usage, and coverage shell rates need a second discovery pass over `v2 teams/stats` categories and team reports. Player-level man/zone coverage splits are confirmed; team-level Cover 0/1/2/3/4/6 is uncertain.

## 5. Desired Statistics Availability

Definitely available from sampled endpoints:

- QB attempts, completions, yards, interceptions, turnover-worthy plays/rate, big-time throws/rate, average time to throw, average depth of target, dropbacks, pressure-to-sack rate, sacks, QB rating.
- WR/TE targets, receptions, yards, routes, YPRR, aDOT, contested targets, contested catches/rate, catch rate, drops/drop rate, alignments/snaps.
- RB attempts, rushing yards, yards after contact, YAC/attempt, missed tackles forced variants, explosive/breakaway fields.
- OL pass-blocking snaps, pressures/sacks/hits/hurries allowed, PBE, pass-block grade, true-pass-set variants.
- Pass rush snaps, pressures, sacks, hits, hurries, pass-rush wins, win rate, PRP.
- Run-defense snaps, stops, stop percentage, tackles, missed tackles/rate, run-defense grade.
- Coverage snaps, targets, receptions/yards allowed, INTs, forced incompletions/rate, rating against, yards per coverage snap.
- Rookie status via `draft_season` and `eligible_season`.

Uncertain or not observed:

- First-read targets.
- Team blitz rate and total blitzes.
- QB blitz rate faced.
- Team Cover 0/1/2/3/4/6 usage.
- Defensive front/alignment tendencies.
- Tackles for loss.
- Whether `/v1/facet/passing/allowed_pressure` maps cleanly to QB pressures faced or blocker pressures allowed; sample required.

## 6. Recommended Qualifiers

Initial content-discovery qualifiers should be conservative and configurable:

- QB passing: at least 20 dropbacks or 15 attempts.
- QB pressure/time-to-throw splits: at least 10 qualifying dropbacks in the split.
- WR/TE receiving: at least 12 routes or 4 targets.
- YPRR / TPRR: at least 10 routes.
- RB rushing: at least 6 rushing attempts for efficiency; no attempt minimum for volume leaderboards.
- OL pass blocking: at least 15 pass-block snaps.
- Pass rush: at least 10 pass-rush snaps.
- Run defense: at least 10 run-defense snaps.
- Coverage: at least 10 coverage snaps or 3 targets, depending on metric.
- Rookies: `draft_season == season`; keep qualifier per metric so low-sample rookies can still be flagged as "small-sample watch" rather than ranked.

These are starting publication safeguards, not model thresholds.

## 7. Proposed Architecture

Recommended layout:

```text
pff_content/
  README.md
  requirements.txt
  scripts/
    test_pff_connection.py
    discover_pff_schema.py
    build_weekly_content_candidates.py
  src/
    pff_content/
      __init__.py
      config.py
      client.py
      cache.py
      api/
        endpoints.py
        schema.py
      transforms/
        normalize.py
        player_tables.py
        team_tables.py
        qualifiers.py
      reports/
        weekly_candidates.py
        html.py
        markdown.py
  data/
    raw/
    processed/
  outputs/
  docs/
    pff_api_discovery.md
  tests/
```

For this task, only the scaffold, connection diagnostic, and discovery report were created.

## 8. Proposed API And Cache Strategy

Use a small reusable client:

- Load `PFF_API_KEY` from `PFF_API_KEY` env var, falling back temporarily to `../player_props/.env`.
- Never log request headers containing `Authorization`.
- Cache raw JSON at:

```text
data/raw/pff/<season>/week_<WW>/<capture_id>/<endpoint_slug>.json
data/raw/pff/<season>/week_<WW>/<capture_id>/<endpoint_slug>.metadata.json
```

Metadata should include:

- endpoint path
- query params with no secrets
- captured_at UTC
- HTTP status
- response SHA-256
- safe rate-limit/request headers
- source: `pff_api`
- OpenAPI spec hash/version if available

Processing strategy:

- First write raw response.
- Decode to normalized tables only from raw cache.
- Keep dynamic v2 `columns` metadata beside processed files.
- Make schema drift visible by writing per-endpoint field inventories.
- Avoid repeated API calls by default if a same-day cache exists unless `--refresh` is passed.

## 9. Recommended Implementation Phases

1. Build `client.py` and `cache.py` around the proven `player_props` request/cache pattern.
2. Add `discover_pff_schema.py` to fetch OpenAPI, inventory relevant endpoints, and sample dynamic v2 reports.
3. Add v1 transforms for confirmed league-wide endpoints: games, passing summary, receiving summary, rushing summary, pass blocking, pass rush, run defense, coverage.
4. Build a candidate-metric registry with fields, directionality, qualifiers, and story templates.
5. Build `build_weekly_content_candidates.py` to generate ranked internal CSV/Markdown candidates.
6. Add team-level discovery for `v2 teams/stats` categories and team reports.
7. Add HTML/Markdown/social export only after candidate tables are stable.

## 10. Uncertainties Before Full Coding

- Which v2 `teams/stats` categories expose team blitz/man/zone/Cover shell rates.
- Whether first-read targets are exposed under a receiving detail/report endpoint.
- Whether QB blitz rate faced is available directly or must be inferred from pressure/detail splits.
- Exact response schema for `/v1/facet/passing/allowed_pressure`.
- Whether dynamic v2 team report names are enumerated elsewhere or must be discovered from failed/successful calls.
- Publication rules: how aggressively to surface small-sample outliers versus "watch list" notes.

## Discovery Summary

Files created:

- `README.md`
- `.gitignore`
- `requirements.txt`
- `scripts/test_pff_connection.py`
- `src/pff_content/__init__.py`
- `src/pff_content/api/__init__.py`
- `src/pff_content/transforms/__init__.py`
- `src/pff_content/reports/__init__.py`
- `data/raw/.gitkeep`
- `data/processed/.gitkeep`
- `outputs/.gitkeep`
- `docs/pff_api_discovery.md`

API calls made for this discovery task:

- `GET /v1/auth/whoami`
- `GET /v1/games`
- `GET /v1/facet/passing/summary`
- `GET /v1/facet/receiving/summary`
- `GET /v1/facet/offense/pass_blocking`
- `GET /v1/facet/defense/pass_rush`
- `GET /v1/facet/defense/run`
- `GET /v1/facet/defense/coverage`
- `GET /v1/facet/defense/coverage_scheme`
- `GET /v1/facet/signature/passing/time_in_pocket`

Authentication result:

- `scripts/test_pff_connection.py` confirms authenticated and entitled PFF API access: status `200`, tier `pro`, credential type API key.

Definitely available:

- QB passing/process stats, receiving route/target efficiency, rushing YAC/missed tackles/explosives, OL pass blocking, pass rush, run defense, coverage production, man/zone player coverage splits, rookie indicators.

Uncertain or unavailable from current samples:

- First-read targets, QB blitz rate faced, team blitz rate, detailed Cover shell usage, defensive front/alignment tendencies, tackles for loss.

Recommended next implementation step:

- Build `src/pff_content/client.py` and `cache.py`, then a schema-discovery script that fetches OpenAPI plus selected endpoint field inventories into stable CSV files before any weekly content ranking logic is implemented.
