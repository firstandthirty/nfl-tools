# First & Thirty NFL Injury Tracker

This project is the foundation for a semi-automated NFL injury tracker. It can now fetch and parse official NFL club injury-report pages, ingest current injury-related reserve status from official club roster pages, enrich those source rows with saved PFF identity, position, and snap-participation data, provide a local manual review workflow, and build a reviewed static HTML page for GitHub Pages. It does not yet publish that page automatically.

The long-term workflow is:

1. Preserve raw source snapshots.
2. Normalize official team injury reports, roster/reserve data, FantasyPros injury/news data, and PFF snap-count data.
3. Use automation to identify players worth manual review.
4. Let a human decide who is published and what editorial note appears.
5. Publish a weekly matchup-organized injury tracker.

## Current scope

The current implementation includes the project structure, team configuration, position normalization rules, canonical injury-player schema, manual CSV templates, offline tests, official team injury-report ingestion, official club roster reserve-state ingestion, NFL.com reserve transaction-history attachment where available, PFF enrichment from saved/processed PFF data, local manual review, and static reviewed output. It deliberately does not call FantasyPros or publish GitHub Pages output automatically.

## Directory structure

```text
injury_tracker/
  config/
    teams.json
    position_groups.json
    relevance_rules.json
  data/
    raw/
    processed/
    manual/
      overrides.csv
      manual_players.csv
    output/
  docs/
  scripts/
    injury_schema.py
    official_injury_reports.py
    official_roster_reserves.py
    fetch_official_injuries.py
    enrich_pff_injuries.py
    pff_enrichment.py
    schedule_context.py
    build_public_site.py
  tests/
    test_injury_foundation.py
    test_official_injury_ingestion.py
    test_official_roster_reserves.py
    test_pff_enrichment.py
    test_schedule_context.py
```

Planned snapshot convention:

```text
data/raw/{source}/{season}/week_{WW}/{capture_id}/...
data/processed/{season}/week_{WW}/...
data/output/{season}/week_{WW}/...
```

Raw snapshots should be immutable. Use timezone-aware timestamps; Eastern Time is appropriate for editorial display, while stored timestamps should remain unambiguous with offsets or UTC.

## Official injury-report ingestion

Official club injury-report pages are authoritative for reported injury/body part, practice participation, and game designation. They are not authoritative for final canonical player position once PFF enrichment is added, so official positions are preserved as `source_position`.

The live NFL club pages inspected on September 24, 2026 share a common club-site structure:

- The page has a selected week dropdown such as `/team/injury-report/week/REG-3`.
- Most teams expose two ordinary HTML tables, one for the club and one for the opponent.
- The common table headers are `Player`, `Position`, `Injury`, weekday columns such as `Wed`, `Thu`, `Fri`, and `Game Status`.
- The pages did not expose actual practice dates in the table headers during this inspection, only weekday labels. When independent schedule context has a game date, the parser now infers the prior calendar date for each weekday and marks it with `practice_date_source=schedule_inferred`.
- No stable embedded JSON injury API was visible in the fetched HTML; the current parser uses common semantic table parsing.

The parser strategy is `official_team_common_table_v1`. It extracts recognizable injury tables, infers the table team from nearby club headings, combines duplicate player rows by `team + normalized_player_name`, and preserves source rows in record metadata.

### Schedule context and matchup validation

Official injury pages remain authoritative for injury details, participation, and game designation. Schedule context is used only to validate matchup context and infer practice dates.

`scripts/schedule_context.py` provides the abstraction. It currently looks for existing repo schedule artifacts in this order:

1. `player_props/data/processed/game_context.csv`, when it contains the requested season/week.
2. `power_rankings/data/analysis/power_ratings/2026/market_diagnostics/week_03/future_board_inventory/future_games_inventory.csv`, a saved read-only Week 3/4 inventory used here only as a schedule fallback. This does not call The Odds API.

The Week 3 run used the saved future-board inventory because the non-betting `player_props` game context did not include 2026 Week 3.

Match validation statuses:

- `MATCH_CONFIRMED`: page opponent and schedule opponent agree.
- `MATCH_CONTEXT_UNAVAILABLE`: the report has meaningful rows but page opponent could not be inferred.
- `MATCH_MISMATCH`: selected/page matchup conflicts with schedule context.
- `NO_REPORT_YET`: no meaningful requested-team report data.
- `PARSE_FAILED`: fetched HTML could not be interpreted.
- `FETCH_FAILED`: page fetch failed.

Participation values normalize to:

```text
DNP LP FP
```

Game designations normalize common values such as:

```text
Out Doubtful Questionable
```

The raw source value is retained in `game_status_raw`, `practice_observations[].raw_participation`, and `source_metadata.raw_row`.

### CLI

Fetch one team:

```powershell
py -m injury_tracker.scripts.fetch_official_injuries --season 2026 --week 3 --team NE
```

Fetch selected teams:

```powershell
py -m injury_tracker.scripts.fetch_official_injuries --season 2026 --week 3 --team NE --team NYJ --team BAL --team KC
```

Fetch all teams:

```powershell
py -m injury_tracker.scripts.fetch_official_injuries --season 2026 --week 3 --all --delay 0.25
```

### Raw snapshots

Successful and failed fetch attempts write metadata under:

```text
data/raw/official_team/{season}/week_{WW}/{run_id}/
```

Successful fetches also preserve the raw HTML as `{TEAM}.html`. Metadata files include team, source URL, fetch timestamp, HTTP status, content type, season, week, parser version, and raw file path.

### Processed outputs

Each run writes a non-overwriting processed directory:

```text
data/processed/{season}/week_{WW}/{run_id}/
```

Outputs:

- `official_injury_reports.json`
- `official_injury_reports.csv`
- `official_injury_source_rows.json`
- `official_injury_source_rows.csv`
- `manifest.json`
- `summary.md`

Canonical `official_injury_reports.*` files include only meaningful requested-team rows with injury, practice, or game-status data. Diagnostic `official_injury_source_rows.*` files preserve all parsed rows from the fetched pages, including opponent tables and rows marked `has_report_data=false`.

Records include `practice_observations`, a flattened `practice_by_day`, `source_position`, `source_page_team`, source URL, fetch timestamp, and raw snapshot reference. Manifest rows expose both `parsed_source_rows` and `meaningful_injury_records` for the requested team.

### Status meanings

- `SUCCESS_CURRENT`: selected page week matches the requested week, the requested team has at least one meaningful injury/practice/status row, and no schedule mismatch was found.
- `SUCCESS_BUT_STALE`: selected page week does not match the requested week, or schedule validation finds a matchup mismatch, while report rows were parsed.
- `NO_REPORT_YET`: no recognizable table, or the requested team table has no meaningful injury/practice/status values.
- `PARSE_FAILED`: HTML fetched but could not be interpreted as an injury report.
- `FETCH_FAILED`: page could not be retrieved after retries.

### Week 3 live diagnostic

Validation set run:

```text
data/processed/2026/week_03/20260924T130757Z/
```

Results for NE/NYJ/BAL/KC:

| Team | Fetch | Parse | Current Status | Meaningful Players | Opponent | Notes |
| --- | --- | --- | --- | ---: | --- | --- |
| NE | OK | OK | SUCCESS_CURRENT | 10 | JAX | Common table parsed |
| NYJ | OK | OK | SUCCESS_CURRENT | 6 | DET | Common table parsed |
| BAL | OK | OK | NO_REPORT_YET | 0 | DAL | Requested-team rows existed but had no injury/practice/status values |
| KC | OK | OK | SUCCESS_CURRENT | 12 | MIA | Common table parsed |

All-32 schedule-aware run:

```text
data/processed/2026/week_03/20260924T175917Z/
```

Summary:

| Metric | Count |
| --- | ---: |
| Teams requested | 32 |
| Fetch OK | 32 |
| Fetch failed | 0 |
| Parse OK | 30 |
| Parse failed | 0 |
| SUCCESS_CURRENT | 28 |
| No report yet / blank requested report | 4 |
| Stale selected week | 0 |
| Match confirmed | 27 |
| Match context unavailable | 1 |
| Match mismatch | 0 |
| Canonical meaningful records written | 230 |
| Requested-team source rows in manifest | 241 |
| Diagnostic source rows written | 482 |

Teams needing review:

- `BAL`: selected Week 3, schedule/page opponent both DAL, requested-team table rows existed but had no injury/practice/status values.
- `CHI`: selected Week 3, schedule opponent PHI, fetched HTML contained the game-status legend but no recognizable injury-report table.
- `PHI`: selected Week 3, schedule opponent CHI, fetched HTML contained the game-status legend but no recognizable injury-report table.
- `SEA`: selected Week 3, schedule opponent WAS, current report rows parsed, but page opponent context was not inferable from surrounding page text.
- `WAS`: selected Week 3, schedule/page opponent both SEA, but no meaningful requested-team rows were present.

### Week 3 PFF enrichment diagnostic

PFF enrichment run:

```text
data/processed/2026/week_03/20260924T175917Z/
```

Outputs:

- `pff_enriched_injuries.json`
- `pff_enriched_injuries.csv`
- `pff_match_manifest.json`
- `pff_enrichment_comparison.json`
- `pff_enrichment_comparison.csv`
- `pff_candidate_report.md`
- `pff_unmatched_player_search.json`
- `pff_unmatched_player_search.csv`

Summary:

| Metric | Count |
| --- | ---: |
| Official meaningful players | 230 |
| PFF identity matched | 230 |
| Exact matches | 225 |
| Normalized / safe alias matches | 5 |
| Persisted matches | 0 |
| Review required matches | 0 |
| Unmatched | 0 |
| Candidate YES | 164 |
| Candidate NO | 66 |
| Identity matched with true offense/defense snap data | 192 |
| Identity matched with only special-teams snap data | 14 |
| Identity matched with no Week 1-2 snap data | 24 |
| Out/Doubtful-only candidates | 1 |

Manual inspection notes:

- PFF position corrections are common and useful, especially `OLB/DE -> ED`, `DT/DL -> DI`, `DB -> S/CB`, and generic offensive-line labels to `C/G/T`.
- Recent-healthy usage protected several players whose previous-game percentage was low but who had a strong earlier role signal.
- Special-teams-only profiles are excluded by default even when PFF has raw special-teams snap counts.
- The true-snap source resolved 14 of the 42 players unmatched by the older facet-only proof of concept.
- The PFF player-directory layer resolved the remaining identity gap. Players no longer need a Week 1-2 snap row to be PFF identity matched.
- Twenty-four identity-matched players have `snap_data_status=NO_DATA`, meaning no current Week 1-2 participation row was available. This is intentionally different from zero snaps.
- Official injury-report team/player rows remain authoritative for the current injury context. The enrichment does not mark player/team combinations suspicious based on historical football knowledge.
- Candidate comparison versus the true-snap/no-directory enrichment: 162 `YES_TO_YES`, 66 `NO_TO_NO`, and 2 `NO_TO_YES`. The two additions came from identity aliases that exposed true defensive snap data, not threshold changes.

Known limitations:

- Practice dates are schedule-inferred, not source-stated, because the common table headers observed so far expose weekday labels rather than dates.
- Table-team attribution is inferred from surrounding page text. This worked for most clubs after adding word-boundary matching and schedule validation, but should be audited as pages change.
- Some pages show opponent data before or after the club data, and some requested-team tables can contain player rows with no actual report values.
- The current 2026 Week 3 schedule backing source is a saved diagnostics CSV from `power_rankings`; replace it with nflverse or another pure schedule source when available.
- Offensive and defensive snap percentages are derived as player unit snaps divided by inferred team unit snaps for that game/team from PFF summary rows. The source did not expose an equally reliable team special-teams denominator, so special-teams percentage remains unavailable even though raw special-teams snaps are captured.

## Official club roster reserve-state ingestion

Official club roster pages are the current-state authority for whether a player is listed in an injury-related reserve/status bucket. This source is separate from weekly official injury reports: reserve rows are not merged into `official_injury_reports.*`, and a player may legitimately appear in both sources in later canonical layers.

The parser strategy is `official_club_roster_common_table_v1`. It uses the common NFL club roster table structure and preserves every parsed roster bucket in diagnostic source rows. The canonical injury-reserve output focuses on injury-related reserve states.

Run all teams:

```powershell
py -m injury_tracker.scripts.official_roster_reserves --season 2026 --week 3 --all --delay 0.25
```

Raw snapshots write under:

```text
data/raw/official_roster/{season}/week_{WW}/{run_id}/
```

Processed outputs write beside other weekly run outputs:

```text
data/processed/{season}/week_{WW}/{run_id}/
```

Reserve outputs:

- `reserve_players.json`
- `reserve_players.csv`
- `official_roster_source_rows.json`
- `official_roster_source_rows.csv`
- `reserve_manifest.json`

Each parsed row preserves:

```text
team
player_name
source_position
raw_roster_status
canonical_roster_status
injury_related
reserve_list
active_roster
designated_for_return
source_url
fetched_at
player_profile_url
```

Canonical statuses currently supported:

- `ACTIVE`
- `IR`
- `PUP`
- `NFI`
- `OTHER_RESERVE`

The raw bucket label is always retained. `Reserve/Injured; Designated for Return` maps to `canonical_roster_status=IR`, `reserve_list=true`, and `designated_for_return=true`. `Active/Physically Unable to Perform` remains `canonical_roster_status=ACTIVE`, `active_roster=true`, and `reserve_list=false`, with `pup_related=true`; it is intentionally distinct from `Reserve/Physically Unable to Perform`.

Current reserve-state ingestion does not infer or store transaction dates, IR placement dates, practice-window dates, or activation dates. Those belong in a later NFL.com transaction-history layer.

Reserve players are passed through the same PFF identity, position, participation, candidate, and manual-override logic used by official injury rows. PFF remains authoritative for football position after a successful identity match; official club roster remains authoritative for reserve status. Reserve status alone does not automatically make a player a key candidate: existing usage thresholds, special-teams exclusion, QB handling, and manual include/exclude behavior are reused without threshold tuning. `NO_DATA` remains a distinct snap-data state and is not interpreted as zero participation.

## NFL reserve transaction history

NFL.com league transaction pages are the event-history authority for documented reserve-list moves. They do not override current club roster state. The source hierarchy is:

- Official club roster pages: current reserve state.
- NFL.com reserve-list transaction pages: historical event dates and transaction wording.
- PFF: identity, position, and participation.

The transaction-history fetcher reads:

```text
https://www.nfl.com/transactions/league/reserve-list/{year}/{month}
```

Raw monthly bundles are preserved before parsing under:

```text
data/raw/nfl_transactions/{season}/{run_id}/
```

Each bundle preserves requested URL, actual page URLs, fetch timestamps, HTTP metadata, page bodies, and duplicate pagination markers when NFL.com returns identical HTML for a cursor URL. Normalized history is written independently beside the reserve snapshot as:

```text
nfl_reserve_transactions.json/csv
```

The current reserve snapshot is enriched into a separate output:

```text
reserve_players_with_transaction_history.json/csv
reserve_transaction_reconciliation.json/csv
reserve_transaction_summary.json
```

The original `reserve_players.*` files remain the unmodified current-state source.

`reserve_transaction_date` means the documented NFL transaction date associated with entry into the player's current reserve state, when the transaction history explicitly supports it. It is not an injury date. Roster state alone does not create a transaction date.

`designated_for_return=true` can come from the current club roster. `designated_for_return_date` is populated only when the NFL transaction history separately contains a designated-for-return event. It remains blank when no official transaction row documents that date.

Reconciliation statuses:

- `HISTORY_CONFIRMS_CURRENT_STATE`: matched history supports the current reserve state.
- `CURRENT_STATE_WITHOUT_MATCHED_HISTORY`: the player is currently on an injury-related reserve list, but no safe transaction-history match was found.
- `HISTORY_HAS_LATER_ACTIVATION`: official transaction history has an activation after a matched placement; current club roster is still preserved as authoritative and the row is flagged.
- `HISTORY_STATUS_CONFLICT`: matched history points to a different reserve status than the current club roster bucket.
- `HISTORY_UNRESOLVED`: relevant history was found but could not be classified strongly enough to confirm or conflict.

Known gaps from the Week 3 2026 run:

- July, August, and September were required for inspection. August/September covered cutdown and in-season reserve moves; July was included because current PUP/NFI players may have training-camp reserve history.
- The observed NFL reserve-list pages primarily exposed `Reserve/Injured` placement rows. PUP/NFI and designated-for-return dates were not broadly available from this source in the fetched range.
- Historical transaction rows are preserved even when PFF identity is unresolved.

## Manual review philosophy

Automation decides who deserves review. A human decides who gets published.

`data/manual/overrides.csv` stores legacy/source-stage manual overrides used during automated enrichment. It supports `publish` decisions, manual notes, and optional position overrides before the review layer. Automated rebuilds should merge this file in and must not erase it.

`data/manual/manual_players.csv` lets an editor add players missed by automated sources. Review UI "missing player" additions reuse this file instead of creating a competing manual-player system.

`data/manual/review_decisions.csv` stores human review decisions for a specific season/week/player. This is distinct from the automated `key_candidate` field:

- `INCLUDE` means the reviewed publish population includes the player even if automation later says no.
- `EXCLUDE` means the reviewed publish population excludes the player even if automation says yes.
- no row means the automated candidate result controls the default state.

The same file also stores `ft_note`, a human-authored First & Thirty editorial note. The note is independent from INCLUDE/EXCLUDE and can be saved without changing the review decision. It is carried into reviewed outputs as `ft_note` with `ft_note_source=manual_review`.

PFF player ID is preferred for durable identity when available. When no PFF ID exists, the review layer falls back to `season + week + team + normalized player name`.

`data/manual/review_status.csv` stores review-completion state for games and teams. Review completion is explicit: a game is not considered reviewed merely because automated-default INCLUDE rows exist.

Manual position overrides are explicit and win over all other position sources. This is intended for known source mistakes or editorial cleanup, not routine guessing.

## Manual review workflow

The review workflow is:

```text
automated data -> candidate review page -> human decisions -> reviewed dataset
```

Update a current week end to end:

```powershell
py -m injury_tracker.scripts.update_week --season 2026 --week 4
```

The update command refreshes official injury reports, ensures PFF participation through the previous week, refreshes official club reserve state, attaches already-saved transaction history when available, and rebuilds the review outputs. It does not delete manual review decisions, F&T notes, or game/team reviewed state.

Build/regenerate the review population without launching the UI:

```powershell
py -m injury_tracker.scripts.build_review_population --season 2026 --week 3
```

Launch the local review app:

```powershell
py -m injury_tracker.scripts.review_app --season 2026 --week 3
```

Use `--no-browser` if you only want the local server URL printed.

The review app is intentionally small: Python standard-library HTTP server plus embedded HTML/JS. It does not require Node, npm, or a frontend build step.

### Review population

The review layer reads the latest saved weekly inputs:

- `pff_enriched_injuries.json`
- `reserve_players_with_transaction_history.json`
- `manual_players.csv`
- `review_decisions.csv`
- `review_status.csv`

It deduplicates injury-report and reserve rows by stable PFF player ID when present, otherwise by team and normalized name. A player in both the weekly injury report and reserve source appears once, with both source memberships preserved.

The primary review screen defaults to automated `key_candidate=true` players plus any manual INCLUDE players. Candidate-NO players remain searchable in the team-level Add Player workflow, but they are not dumped into the main queue.

Players are organized:

```text
Week -> Game -> Team -> Position Group -> Player
```

Position group order:

```text
QB RB WR TE OL EDGE DL LB CB S ST
```

### Review controls

Each player has INCLUDE and EXCLUDE controls. Automated candidate YES rows initially appear as default included, but `explicitly_reviewed=false` until the human saves a decision. Save actions write immediately to the CSV files and regenerate the reviewed outputs.

Team-level Add Player supports two paths:

1. Search known Week 3 source players, including automated candidate-NO rows, then save manual INCLUDE.
2. Add a truly missing player through `manual_players.csv` with minimal metadata, then save manual INCLUDE.

Game and team review buttons write explicit completion rows to `review_status.csv`. These rows survive automated rebuilds.

### Reviewed outputs

Reviewed outputs are generated under:

```text
data/reviewed/{season}/week_{WW}/
```

Files:

- `review_population.json`
- `review_population.csv`
- `reviewed_players.json`
- `reviewed_players.csv`

`review_population.*` includes every known source/manual player with automated and final review state. `reviewed_players.*` includes the final included population only. Both preserve source memberships, matchup context, identity, injury/practice/designation fields, reserve status, transaction date, participation evidence, automated candidate result/reasons, manual decision/note, and final include/exclude state.

Source files remain immutable. The review layer does not rewrite generated injury-report or reserve source truth.

## Public static tracker

The public page is built only from reviewed outputs and explicit game review state. It does not fetch sources, rebuild candidates, or alter manual review files.

Build the current public static page:

```powershell
py -m injury_tracker.scripts.build_public_site --season 2026 --week 4
```

Outputs:

- `docs/injuries/index.html`
- `docs/injuries/public_view_model.json`
- `docs/injuries/{season}/week_{WW}/index.html`
- `docs/injuries/{season}/week_{WW}/public_view_model.json`

The current path is the stable reader-facing entry point. The season/week path is the archive copy for that exact reviewed week.

Publishing semantics:

- Only games explicitly marked reviewed in `data/manual/review_status.csv` expose player names.
- Unreviewed games render the matchup shell with pending-review messaging, and report-unavailable messaging when the official injury report was not available.
- Within each reviewed team, current weekly injuries render before reserve/IR players.
- Public player cards include only reader-facing fields: name, display position, injury/practice/designation, reserve status, designated-for-return status, transaction date when available, source label, and `F&T Note:` text when present.
- Internal review and relevance fields such as PFF IDs, candidate reasons, snap percentages, review-state labels, and automated/default-review flags are intentionally excluded from both the HTML and sanitized public view model.

Remote deployment remains explicit. The builder prepares static files only. The publish-prep command copies approved HTML into the local Pages subtree, and the final GitHub publish command commits and pushes only a narrow weekly allowlist after Git safety checks pass.

## Weekly Operating Workflow

Current week configuration lives in:

```text
config/current_week.json
```

Set or change the active week:

```powershell
injury_tracker\00_SET_CURRENT_WEEK.bat
```

or edit the JSON directly:

```json
{
  "season": 2026,
  "week": 4
}
```

Normal weekly flow:

1. Update source data and rebuild review outputs:

   ```powershell
   injury_tracker\01_UPDATE_WEEK.bat
   ```

   Equivalent command:

   ```powershell
   py -m injury_tracker.scripts.update_week --config injury_tracker\config\current_week.json
   ```

2. Open the local review app:

   ```powershell
   injury_tracker\02_REVIEW_WEEK.bat
   ```

   In the app, use INCLUDE/EXCLUDE, add F&T notes, add missing players if needed, and mark games reviewed. Team names link to official club injury-report pages from `config/teams.json`.

3. If reports change later in the week, run update again. Previously reviewed games are checked for source-data staleness.

4. Re-review any stale games and click Mark game reviewed again. That stores a fresh source fingerprint.

5. Build a local public preview:

   ```powershell
   injury_tracker\03_BUILD_PUBLIC_SITE.bat
   ```

   Equivalent command:

   ```powershell
   py -m injury_tracker.scripts.build_public_site --config injury_tracker\config\current_week.json
   ```

   Local preview outputs remain under:

   ```text
   injury_tracker/docs/injuries/
   ```

6. Prepare public Pages output:

   ```powershell
   injury_tracker\04_PREPARE_PUBLISH.bat
   ```

   Equivalent command:

   ```powershell
   py -m injury_tracker.scripts.publish_public_site --config injury_tracker\config\current_week.json
   ```

   This validates stale state, rebuilds the local preview, then copies only public HTML into the repository Pages subtree:

   ```text
   injuries/index.html
   injuries/{season}/week_{WW}/index.html
   ```

   It does not copy `public_view_model.json`, and it does not run `git add`, `git commit`, or `git push`.

7. Publish the reviewed weekly update when ready:

   ```powershell
   injury_tracker\05_PUBLISH_TO_GITHUB.bat
   ```

   Equivalent command:

   ```powershell
   py -m injury_tracker.scripts.publish_to_github --config injury_tracker\config\current_week.json
   ```

   This command verifies the repository root, confirms branch `main`, refuses unexpected origin remotes, refuses pre-existing staged changes, runs `git fetch origin`, stops if local `main` is ahead/behind/diverged from `origin/main`, stages only the weekly publication allowlist, verifies the staged set, commits as `Update Week N injury tracker`, re-fetches, then pushes with ordinary `git push origin main`.

   The weekly allowlist is:

   ```text
   injuries/index.html
   injuries/{season}/week_{WW}/index.html
   injury_tracker/config/current_week.json
   injury_tracker/data/manual/manual_players.csv
   injury_tracker/data/manual/overrides.csv
   injury_tracker/data/manual/pff_player_mappings.csv
   injury_tracker/data/manual/review_decisions.csv
   injury_tracker/data/manual/review_status.csv
   ```

   It does not stage raw snapshots, processed outputs, local preview files, source-code changes, tests, README edits, or unrelated dirty monorepo work. If there is nothing to publish, it exits successfully without creating a commit.

Public URL expectations for the current GitHub remote `firstandthirty/nfl-tools`:

```text
Base:    https://firstandthirty.github.io/nfl-tools/
Current: https://firstandthirty.github.io/nfl-tools/injuries/
Week 4:  https://firstandthirty.github.io/nfl-tools/injuries/2026/week_04/
```

The stable injury-tracker URL is:

```text
https://firstandthirty.github.io/nfl-tools/injuries/
```

### Stale-review semantics

When a game is marked reviewed, the review layer stores a deterministic fingerprint of source-derived review state for that game. The fingerprint covers player membership, injury text, practice status, game designation, reserve status, designated-for-return state, reserve transaction date/type, source memberships, candidate flag/reasons, participation source season, snap-data status, and relevant snap percentage.

The fingerprint intentionally ignores output timestamps, HTML formatting, and F&T note edits. Manual INCLUDE/EXCLUDE changes are explicit human actions and are preserved separately.

If source data changes after review, the game becomes stale. The review app labels it as needing re-review. Public build treats stale games conservatively: player content is hidden and the matchup shows that updated injury information is pending First & Thirty review.

Legacy reviewed games that predate fingerprint support are treated as current only when their reviewed timestamp is later than the latest source input timestamp. If source files are updated afterward, they become stale until reviewed again.

## Position policy

PFF is the canonical position source whenever a player can be matched to PFF data. PFF generally distinguishes EDGE, LB, and interior defensive line more reliably than generic team-site labels.

Position priority:

1. Manual override, when explicitly supplied
2. PFF position, when available
3. Official source position, as a fallback

The canonical record preserves enough fields to audit the decision:

```text
pff_position
source_position
canonical_position
position_group
position_source
```

If PFF says `EDGE` and the team report says `LB`, the canonical position remains `EDGE` and `position_source` is `pff`. The official source position is still retained for audit.

## PFF enrichment

PFF enrichment starts after official injury ingestion and does not mutate the official snapshot. It reads canonical meaningful official rows and writes additional diagnostic files beside that run:

```text
pff_enriched_injuries.json
pff_enriched_injuries.csv
pff_match_manifest.json
pff_candidate_report.md
```

It also writes a reusable derived PFF identity index:

```text
data/processed/pff_player_index/{season}_through_week_{WW}.json
data/processed/pff_player_index/{season}_through_week_{WW}.csv
```

The enrichment stage reuses existing processed PFF data under:

```text
pff_content/data/processed/pff/{season}/week_{WW}/
```

For Week 3, it used processed PFF Weeks 1-2 and made no live PFF API calls.

### PFF identity matching

Matching is conservative and auditable:

1. Persisted manual mapping from `data/manual/pff_player_mappings.csv`
2. Existing stable PFF player ID from processed participation data
3. Exact normalized player name plus current PFF team when team metadata is reliable
4. Unique exact normalized identity from the PFF player directory
5. Safe normalized-name alias from the PFF player directory, usually requiring current-team disambiguation
6. Ambiguous normalized-name matches become `REVIEW_REQUIRED`
7. Missing matches become `UNMATCHED`

The official injury report team remains authoritative for the injury context. Historical PFF usage from another team can be retained after a stable player identity is established.

The normalized name routine handles suffixes, punctuation, apostrophes, periods, hyphens, whitespace, and a compact fallback for apostrophe/space variants. Weak fuzzy matches are not auto-accepted.

The PFF player directory comes from:

```text
GET /v1/players
```

Observed contract from the local OpenAPI inventory:

- `league=nfl` is required.
- Either `name` or `id` is required; the endpoint is not a one-call league-wide dump.
- `name` is a free-text search forwarded upstream as `q`.
- Results include stable PFF `id`, first/last name, position, jersey number, current team metadata, college, draft metadata, height, and weight.
- No pagination link is advertised in the OpenAPI notes.

Because `/v1/players` is search/id based, the reusable directory is built from targeted cached searches and stored under:

```text
pff_content/data/processed/pff_player_directory/{season}/week_{WW}/players.csv
pff_content/data/processed/pff_player_directory/{season}/week_{WW}/players.json
```

Automatic deterministic identities are also persisted in the generated injury-tracker PFF index:

```text
data/processed/pff_player_index/{season}_through_week_{WW}.json
data/processed/pff_player_index/{season}_through_week_{WW}.csv
```

`data/manual/pff_player_mappings.csv` remains reserved for human disambiguation. Manual mappings always win.

### PFF position authority

Position-source priority is:

1. Manual `position_override`
2. PFF position
3. Official source position

This lets PFF correct generic official labels such as `DE`, `OLB`, `DL`, `DB`, and `OL` into more useful football labels like `ED`, `DI`, `S`, `C`, `G`, and `T`. The public `position_group` is still mapped to `EDGE`, `DL`, `S`, `OL`, and so on.

### Snap metrics

PFF participation now uses broad weekly summary datasets instead of the older role/facet proof of concept:

- `/v1/facet/offense/summary`
- `/v1/facet/defense/summary`
- `/v1/facet/special/summary`

The PFF content project normalizes those into:

```text
pff_content/data/processed/pff/{season}/week_{WW}/snap_participation.csv
```

The injury tracker consumes that derived table and captures:

- `pff_identity_status`
- `snap_data_status`
- `season_offensive_snaps`
- `season_defensive_snaps`
- `season_special_teams_snaps`
- `season_relevant_snap_pct`
- `previous_game_relevant_snap_pct`
- `recent_healthy_snap_pct`
- `games_appeared`
- `last_week_played`
- `primary_unit`
- `st_only`

Relevant unit means offense for `QB/RB/WR/TE/OL` and defense for `EDGE/DL/LB/CB/S`. Special teams do not inflate ordinary offensive/defensive relevance.

Offensive and defensive percentages are true relevant-unit player snaps divided by the inferred team unit snap count for that game/team. Special-teams rows provide raw phase snaps, but the current summary source has no reliable team special-teams denominator, so `special_teams_snap_pct` is intentionally left blank.

`snap_data_status` values:

- `OFFENSE_DEFENSE`: matched identity has current-season offensive or defensive participation.
- `ST_ONLY`: matched identity has special-teams participation only.
- `NO_DATA`: matched identity has no Week 1-2 participation row. Missing participation data is not interpreted as zero snaps.

### Recent healthy usage

`recent_healthy_snap_pct` uses the maximum available true relevant-unit snap percentage from the player's last three games before the current injury-report week. This simple rule is intentionally explainable: if a normal starter was hurt early in the most recent game, an earlier high-usage game can still preserve the player's normal-role signal.

### Candidate rules

The automated `key_candidate` field is intentionally permissive and is only a recommendation for manual review.

Current rules:

- Injured QBs are candidates.
- Players meeting the configured relevant-unit snap threshold by season, previous-game, or recent-healthy usage are candidates.
- `Out` or `Doubtful` players are candidates under the current config.
- Manual include/exclude always wins.
- `K/P/LS` and special-teams-only profiles are excluded by default.
- `UNMATCHED` players remain visible with `pff_unmatched`, but missing PFF identity alone does not make them candidates.

Public position groups are:

```text
QB RB WR TE OL EDGE DL LB CB S ST
```

Fallback mapping is conservative. Offensive-line and special-teams labels map cleanly, while ambiguous defensive labels should stay easy to review when PFF is unavailable.

## Relevance rules

`config/relevance_rules.json` is intentionally permissive. It defines initial review-candidate concepts such as:

- QB always candidate
- 25% season snap threshold
- 25% previous-game snap threshold
- special teams excluded by default
- manual overrides always win

Final filtering logic is not implemented yet.

## Existing repository infrastructure to reuse

- Team normalization: `power_rankings/scripts/team_mapping.py` has canonical team names and source-specific abbreviation maps for PFF, NFL abbreviations, FTN, and ESPN.
- PFF API client/cache: `pff_content/src/pff_content/client.py`, `cache.py`, `config.py`, and `paths.py` provide Bearer-token auth, safe header handling, raw JSON caching, request hashes, and `week_XX` path helpers.
- PFF weekly datasets: `pff_content/src/pff_content/datasets.py` lists weekly PFF endpoints including games, passing, receiving, rushing, pass blocking, pass rush, run defense, coverage, team defense, and the broad offense/defense/special-teams summary sources used for injury snap participation.
- PFF normalization: `pff_content/src/pff_content/normalize.py` normalizes PFF rows and preserves `player_id`, `player_name`, `team`, `opponent`, and `position` when available.
- PFF documentation: `pff_content/docs/pff_api_discovery.md` documents `/v1/games`, `/v1/players`, `/v2/nfl/teams`, team schedules, raw cache conventions, and observed player-position fields.
- Player-name/team normalization: `player_props/scripts/utils/name_utils.py` and `player_props/scripts/01_ingest/projection_adapters/common.py` include reusable name and team normalization patterns.
- FantasyPros/PFF secret loading: `pff_content/src/pff_content/config.py` checks the process environment, `player_props.env`, and `player_props/.env` without printing secrets. Future FantasyPros code should follow the same pattern and load `FANTASYPROS_API_KEY` from environment or existing env files.
- Weekly directory conventions: `pff_content` and `power_rankings` consistently use `week_XX` folders and timestamped snapshots.
- Tests: existing projects use `unittest` with path insertion for local scripts.
- HTML generation: `power_rankings/scripts/build_power_rankings_html.py` is a useful reference for static HTML output and manual editorial text integration.
- Publishing/workflows: `workflows/bts_picks.yml` and root publishing scripts show existing GitHub/static publishing patterns, but this project does not create a publishing workflow yet.

## PFF player identity notes

The PFF processed tables carry stable `player_id` plus `position`. The injury tracker schema includes `pff_player_id`, and matching supports persisted ID mappings in `data/manual/pff_player_mappings.csv` for future manual disambiguation. No separate injury-tracker PFF registry is created in this phase.

## Running tests

From the repository root:

```powershell
py -m unittest discover -s injury_tracker\tests
```

The tests are offline and do not depend on live websites or APIs.

## Planned phases

1. Foundation: configs, schemas, tests, and documentation.
2. Source ingestion design: official team reports, roster/reserve snapshots, FantasyPros injury/news, and PFF processed-data joins.
3. Candidate generation: combine injury status, roster status, snap shares, and manual overrides into review queues.
4. Manual review workflow: stable CSV or lightweight local UI for publish decisions and notes.
5. Static output: weekly matchup-organized HTML suitable for GitHub Pages.
6. Scheduled collection: preserve raw snapshots during the NFL week so future backtests and audits do not require historical re-fetches.
