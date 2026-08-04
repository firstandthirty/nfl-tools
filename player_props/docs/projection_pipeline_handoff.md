# Projection Pipeline Handoff

## Raw Snapshot Convention

Raw provider projection files live under:

```text
data/raw/projections/{source}/{season}/week_{WW}/snapshots/
```

Use zero-padded week folders for raw snapshots, for example `week_01`. PFF snapshot filenames should begin with the capture timestamp in `MM_DD_YY_HHMM` local New York time, for example `08_04_26_1100projections.csv`. If a filename cannot be parsed, ingestion falls back to the file modification time and records `captured_at_source=filesystem_mtime`.

Raw snapshots are append-only evidence. Do not edit them in place after ingestion.

## PFF Adapter Flow

The PFF ingestion CLI discovers or accepts a raw CSV, parses snapshot metadata, validates required PFF columns, transforms each applicable player stat into canonical long rows, writes validation and rejection outputs, appends rows into the weekly long file without duplicating identical canonical keys, and optionally rebuilds the snapshot registry.

PFF input columns currently required:

```text
playerName, teamName, position, passYds, rushYds, recvYds, recvReceptions
```

PFF market mapping:

```text
passYds -> player_pass_yds
rushYds -> player_rush_yds
recvYds -> player_reception_yds
recvReceptions -> player_receptions
```

Structural zeroes are filtered where the position-market combination is not applicable, while nontraditional nonzero values are retained.

## Canonical Long Projection Schema

Projection adapters should emit one row per source, season, week, captured snapshot, player, and market. The core schema is:

```text
player
player_normalized
team
position
season
week
source
market
projection
captured_at
captured_at_source
raw_file
```

Current PFF rows also include source/audit columns such as `team_raw`, `source_player_id`, `source_row_number`, and `source_column`.

The canonical identity is:

```text
source, season, week, captured_at, player_normalized, market
```

## Snapshot Registry

The registry turns processed snapshots into a source-agnostic inventory with hashes, row counts, quality fields, coverage summaries, and conflict detection. Its primary output is:

```text
data/processed/projections/snapshot_registry.csv
```

Related outputs:

```text
data/processed/projections/registry_conflicts.csv
data/processed/projections/coverage_reports/weekly_coverage.csv
data/processed/projections/coverage_reports/snapshot_changes.csv
data/processed/projections/coverage_reports/{source}_{season}_week_{WW}_{captured_at}_coverage.csv
```

## As-Of Selection

Consensus is built from the latest eligible snapshot per requested source for a given season, week, and as-of time.

Rules:

- Naive `--as-of` values are localized to America/New_York.
- Timezone-aware `--as-of` values preserve the same instant.
- A snapshot is eligible when `captured_at <= as_of`.
- Future snapshots are excluded.
- Exact timestamp equality is eligible.
- Missing sources are reported as `source_not_available`.
- Sources with no snapshot before as-of are reported as `no_snapshot_before_as_of`.
- Multiple eligible snapshots with the same latest timestamp are flagged as a conflict.

## Consensus Aggregation

Consensus groups selected source rows by:

```text
player_normalized, market
```

For each group it calculates count, mean, median, sample standard deviation, min, max, range, coefficient of variation, source list, source values, snapshot age, source time range, player/team/position conflicts, and deviation metrics.

Pairwise outputs are generated for overlapping player-market keys between selected sources. Source names and source value strings are sorted deterministically.

## Eligibility Rules

Rows are marked `consensus_eligible` only when all configured checks pass:

- `projection_count >= --min-sources`, default `3`.
- `projection_std <= --max-projection-std`, when configured.
- `projection_range <= --max-projection-range`, when configured.
- all `--required-sources` are present, when configured.
- snapshot age is below `--max-snapshot-age-hours`, when configured.
- selected source timestamp gap is within `--max-source-time-gap-hours`, when configured.

Single-source rows are retained for visibility but are not treated as true multi-source consensus when `--min-sources` remains at the default.

## Current Live Status

The live projection infrastructure currently has PFF as the only ingested provider. For 2026 week 1, the current processed PFF snapshot produces 1,286 canonical long rows. Because only PFF is live, consensus outputs are intentionally PFF-only and ineligible under the default three-source rule.

## Commands

Ingest one new PFF snapshot:

```powershell
.venv\Scripts\python.exe scripts\01_ingest\ingest_projection_snapshots.py --source pff --season 2026 --week 1 --input data\raw\projections\pff\2026\week_01\snapshots\08_04_26_1100projections.csv
```

Discover and ingest all PFF snapshots for a week:

```powershell
.venv\Scripts\python.exe scripts\01_ingest\ingest_projection_snapshots.py --source pff --season 2026 --week 1
```

Rebuild the registry:

```powershell
.venv\Scripts\python.exe scripts\01_ingest\build_projection_registry.py --source pff --season 2026 --week 1 --rebuild
```

Build consensus:

```powershell
.venv\Scripts\python.exe scripts\02_processing\build_projection_consensus.py --season 2026 --week 1 --as-of 2026-08-04T13:30:00-04:00 --sources pff --overwrite
```

## Future Source Adapter Integration

A future adapter should:

- Place immutable raw files in the same `data/raw/projections/{source}/{season}/week_{WW}/snapshots/` convention.
- Parse or derive `captured_at` and record `captured_at_source`.
- Validate provider-specific required columns with clear errors.
- Normalize player names and teams using existing utilities.
- Map provider stats into the canonical market names.
- Emit the canonical long schema and maintain one row per canonical identity.
- Write per-snapshot long, rejected, and validation CSVs under `data/processed/projections/{source}/{season}/week_{W}/`.
- Use `schema_version=projection_long_v1` and a source-specific adapter version.
- Add focused adapter tests, registry tests for source discovery, and consensus tests with that source selected alongside PFF.

## Known Limitations

- Only PFF is live, so current consensus output is a source-normalized projection layer rather than a true multi-source consensus.
- There is no sportsbook main-line or alternate-line ingestion connected to this pipeline yet.
- Eligibility does not evaluate market prices, odds, line availability, or bet EV.
- Snapshot stage and days-before-week-start are reserved fields and currently default to unknown/blank.
- Name/team conflicts are flagged, not resolved by an identity mapping service.
- Existing holdout autopsy regression tests require `scipy` for Spearman correlation.

## Recommended Next Task

Build sportsbook main-line and alternate-line ingestion/evaluation as the next layer. That work should join book lines to canonical player-market projections, evaluate main-line and alternate-line pricing separately, and keep backtest generation isolated from the projection snapshot registry and consensus source-selection logic.
