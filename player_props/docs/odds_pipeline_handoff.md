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

When multiple raw outcomes map to the same canonical betting key:

```text
source, sportsbook, season, week, captured_at, event_id,
player_normalized, market, line, side
```

the adapter retains the best available American price for the bettor. Numerically higher American odds are better (`+104` beats `+102`, `-105` beats `-115`). If prices are equal, the stable tie-breaker prefers the main market over the alternate market; otherwise it keeps raw/source order. Consolidated duplicates are recorded as `consolidated_duplicate_price` diagnostics and are not data-quality rejections. The retained row preserves contributing raw market keys, raw prices, alternate flags, and source locations.

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

Offline ingestion still makes no live Odds API requests. The controlled live downloader is:

```powershell
py scripts\01_ingest\download_odds_api_player_props.py --season 2026 --week 1 --execute-live-request
```

The downloader makes no HTTP requests unless `--execute-live-request` is present. Without the flag, it only prints the configured sport, endpoints, market keys, bookmaker policy, week window, and already archived ingestable snapshots.

The live downloader uses:

```text
sport=americanfootball_nfl
events endpoint=/sports/americanfootball_nfl/events
event odds endpoint=/sports/americanfootball_nfl/events/{event_id}/odds
regions=us
oddsFormat=american
dateFormat=iso
```

It requests these canonical/model markets:

```text
player_pass_yds
player_rush_yds
player_reception_yds
player_receptions
player_pass_yds_alternate
player_rush_yds_alternate
player_reception_yds_alternate
player_receptions_alternate
```

Bookmaker request policy: the downloader requests `regions=us` and does not send a `bookmakers` filter. This keeps all available US-region books in the raw response and avoids arbitrarily limiting downstream market coverage. The Odds API current-event odds credit formula is based on unique markets returned multiplied by requested regions, not the number of bookmakers. The `/events` call does not count against quota, while event-odds calls report `x-requests-last`, `x-requests-used`, and `x-requests-remaining` headers.

Week filtering: event discovery is still the unchanged NFL events request. After events return, the downloader keeps only events whose UTC `commence_time` falls inside the configured regular-season week window after timezone-aware conversion to America/New_York local dates. For 2026 Week 1, the configured window starts `2026-09-09T00:00:00-04:00` and ends before `2026-09-16T00:00:00-04:00`, excluding preseason and Week 2+.

Raw archive convention for live pulls:

```text
data/raw/odds/odds_api/{season}/week_{WW}/snapshots/{captured_at}_events.json
data/raw/odds/odds_api/{season}/week_{WW}/snapshots/{captured_at}_event_{NN}_{event_id}_odds.json
data/raw/odds/odds_api/{season}/week_{WW}/snapshots/{captured_at}_manifest.json
data/raw/odds/odds_api/{season}/week_{WW}/snapshots/{captured_at}_odds_bundle.json
```

The events response and per-event odds responses are saved first and are the untouched API responses. The bundle is an ingest helper built afterward from the archived event-odds files so the existing registry can treat the full Week 1 retrieval as one logical snapshot. The manifest records component file lineage, request settings, counts, and credit headers. Raw component files should be treated as append-only.

After a successful live retrieval, the downloader ingests the bundle, rebuilds the odds registry, selects odds as of the retrieval timestamp, and writes a projection-odds join smoke test against the latest selected source projection rows. It does not select bets, calculate EV, or change projection consensus `min_sources`.

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

## Known Limitations

- Alternate market key support is explicit for the current Odds API-style keys and should be validated against each live run's returned raw market coverage.
- Existing archived FanDuel payloads include real Odds API structure, but a sampled pass-yard archive used decimal odds; the new framework expects saved American odds for the canonical production path.
- There is no player fuzzy matching.
- There is no sportsbook availability polling.
- There is no production bet generation, model probability calculation, alt-line selection, CLV calculation, or database layer.
- Receptions odds can be stored, but `player_receptions` remains disabled for production betting unless re-enabled separately.

## Next Step

Build distribution-based alt-line probability and EV evaluation. That next layer should consume selected odds and projection/consensus rows, estimate probabilities outside the storage layer, evaluate main and alternate lines separately, and keep CLV tracking as a later audit layer.
