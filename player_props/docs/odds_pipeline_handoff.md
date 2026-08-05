# Odds Pipeline Handoff

## Raw Odds Snapshot Convention

Saved sportsbook responses should be stored without renaming or in-place edits under:

```text
data/raw/odds/{source}/{season}/week_{WW}/snapshots/{provider_or_user_filename}.json
```

Example:

```text
data/raw/odds/odds_api/2026/week_01/snapshots/20260901T130000_sample_odds_snapshot.json
```

Capture time is resolved in this order:

1. Explicit `--captured-at`
2. Recognized filename timestamp
3. Filesystem modification time

The resolved method is recorded as `captured_at_source`.

## Canonical Odds Schema

The canonical long table has one row per:

```text
sportsbook + event + player + market + line + side + captured_at
```

Required/audit columns:

```text
sportsbook, source, event_id, commence_time, home_team, away_team,
player, player_normalized, market, line, side, price,
captured_at, captured_at_source, season, week, is_alternate,
market_source_key, outcome_description, raw_file,
source_event_index, source_market_index, source_outcome_index,
bookmaker_key, bookmaker_title, last_update, market_last_update,
point_raw, price_raw
```

Player names use the existing conservative `clean_player_name` normalization. Sides are canonical lowercase `over` or `under`. Lines are numeric. Prices retain American odds in the raw-derived canonical table.

## Main And Alternate Lines

Main and alternate props use the same long schema. Alternate rows are marked with `is_alternate=True`; they are not stored as a separate object type.

Market mapping is explicit and source-specific. Current Odds API mappings include:

```text
player_pass_yds -> player_pass_yds, main
player_rush_yds -> player_rush_yds, main
player_reception_yds -> player_reception_yds, main
player_receptions -> player_receptions, main
player_pass_yds_alternate -> player_pass_yds, alternate
player_rush_yds_alternate -> player_rush_yds, alternate
player_reception_yds_alternate -> player_reception_yds, alternate
player_receptions_alternate -> player_receptions, alternate
```

Each distinct line and side remains a separate row.

## Snapshot Ingestion

Per-snapshot outputs:

```text
data/processed/odds/odds_api/{season}/week_{WW}/{snapshot_stem}_odds_long.csv
data/processed/odds/odds_api/{season}/week_{WW}/{snapshot_stem}_odds_rejected.csv
data/processed/odds/odds_api/{season}/week_{WW}/{snapshot_stem}_odds_validation.csv
data/processed/odds/odds_api/{season}/week_{WW}/{snapshot_stem}_odds_conflicts.csv
```

Weekly rollup:

```text
data/processed/odds/odds_api/{season}/week_{WW}/odds_long.csv
```

The weekly rollup retains all snapshots and deduplicates by:

```text
source, sportsbook, season, week, captured_at, event_id,
player_normalized, market, line, side
```

Conflicting duplicate identities are audited instead of silently chosen.

## Registry Identity

The odds registry is:

```text
data/processed/odds/snapshot_registry.csv
```

It uses SHA-256 raw content identity and records raw file metadata, processed output hashes, row counts, coverage, rejections, warnings, and schema version.

Conflicts are written to:

```text
data/processed/odds/registry_conflicts.csv
```

The registry audits same raw content under conflicting metadata, same timestamp with different content, and processed hash conflicts.

## As-Of Selection

As-of selection is independent by sportsbook:

1. Filter snapshots to `captured_at <= as_of`.
2. Pick the latest eligible snapshot per sportsbook.
3. Exclude future snapshots.
4. Report unavailable sportsbooks and same-timestamp conflicts.

Outputs:

```text
data/processed/odds_asof/{season}/week_{WW}/asof_{timestamp}/selected_snapshots.csv
data/processed/odds_asof/{season}/week_{WW}/asof_{timestamp}/selected_odds.csv
data/processed/odds_asof/{season}/week_{WW}/asof_{timestamp}/odds_coverage.csv
data/processed/odds_asof/{season}/week_{WW}/asof_{timestamp}/odds_asof_report.md
```

Odds are not averaged across snapshots or sportsbooks.

## Projection Join Contract

`scripts/02_processing/odds_join.py` joins projection or consensus rows to selected odds on:

```text
season, week, player_normalized, market
```

The join preserves multiple sportsbooks, sides, main lines, and alternate lines. No fuzzy matching is performed. Audit outputs include matched rows, unmatched projections, unmatched odds, player match status, market match status, projection match status, and team conflict when both sides provide team fields.

## Odds Math

`scripts/02_processing/odds_math.py` contains pure helpers for:

- American odds to decimal odds
- American odds to raw implied probability
- Decimal odds to American odds
- Profit per 1 unit risked
- Expected value per 1 unit risked
- Break-even probability

These functions do not estimate model probabilities, select bets, or calculate Kelly staking.

## API-Credit Safeguards

This framework does not make live Odds API requests. It only reads saved JSON. Existing live-download scripts were inspected but not executed or modified.

Future live retrieval should be a separate task and should require an explicit opt-in flag such as:

```powershell
--execute-live-request
```

The user should manually confirm player-prop availability before any live request is executed. Do not add schedules, polling, or automatic availability checks without another explicit task.

## Commands

Ingest a saved response:

```powershell
.venv\Scripts\python.exe scripts\01_ingest\ingest_odds_snapshots.py --source odds_api --input data\raw\odds\odds_api\2026\week_01\snapshots\20260901T130000_sample_odds_snapshot.json --season 2026 --week 1 --overwrite
```

Discover and ingest all saved snapshots for a week:

```powershell
.venv\Scripts\python.exe scripts\01_ingest\ingest_odds_snapshots.py --source odds_api --season 2026 --week 1
```

Rebuild the odds registry:

```powershell
.venv\Scripts\python.exe scripts\01_ingest\build_odds_registry.py --source odds_api --season 2026 --week 1 --rebuild
```

Select odds as of a timestamp:

```powershell
.venv\Scripts\python.exe scripts\02_processing\select_odds_asof.py --season 2026 --week 1 --as-of 2026-09-01T13:30:00-04:00 --sportsbooks fanduel draftkings --overwrite
```

## Future Live Workflow

When the user confirms props are available, add or wrap a live downloader in a separate task. It should require `--execute-live-request`, print expected markets and sportsbooks before requesting, save raw JSON first, and then call the offline ingestion CLI on the saved response.

## Known Limitations

- Alternate market key support is explicit for the current Odds API-style keys but has not been validated against a live 2026 alternate-line response.
- Existing archived FanDuel payloads include real Odds API structure, but a sampled pass-yard archive used decimal odds; the new framework expects saved American odds for the canonical production path.
- There is no player fuzzy matching.
- There is no sportsbook availability polling.
- There is no production bet generation, model probability calculation, alt-line selection, CLV calculation, or database layer.
- Receptions odds can be stored, but `player_receptions` remains disabled for production betting unless re-enabled separately.

## Next Step

Build distribution-based alt-line probability and EV evaluation. That next layer should consume selected odds and projection/consensus rows, estimate probabilities outside the storage layer, evaluate main and alternate lines separately, and keep CLV tracking as a later audit layer.
