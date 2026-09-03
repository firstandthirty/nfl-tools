# Projection Pipeline Handoff

## Raw Snapshot Convention

Raw provider projection files live under:

```text
data/raw/projections/{source}/{season}/week_{WW}/snapshots/
```

Use zero-padded week folders for raw snapshots, for example `week_01`. PFF snapshot filenames should begin with the capture timestamp in `MM_DD_YY_HHMM` local New York time, for example `08_04_26_1100projections.csv`. If a filename cannot be parsed, ingestion falls back to the file modification time and records `captured_at_source=filesystem_mtime`.

Raw snapshots are append-only evidence. Do not edit them in place after ingestion.

FantasyPros weekly projections can arrive either as two CSV exports for one logical provider snapshot or as a single API JSON response. CSV files sharing the same `MM_DD_YY_HHMM` prefix are ingested together as one `fantasypros` source snapshot. API snapshots are stored as one raw JSON file plus a secret-free `.metadata.json` sidecar. The raw provider files remain untouched, and the registry records component file lists, component hashes, source format, and one logical snapshot hash.

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

## FantasyPros Adapter Flow

FantasyPros CSV ingestion discovers matching QB and FLEX exports under the raw snapshot folder and combines them into one canonical long output. The current Week 1 CSV example is:

```text
08_19_26_1200_FantasyPros_Fantasy_Football_Projections_QB.csv
08_19_26_1200_FantasyPros_Fantasy_Football_Projections_FLX.csv
```

Both files above are treated as one snapshot captured at `2026-08-19T12:00:00-04:00`, with `source=fantasypros`. FantasyPros' internal aggregate providers are not counted as separate sources.

FantasyPros duplicate headers are intentionally parsed after pandas mangles duplicates. The adapter validates the exact expected layouts before mapping stats:

```text
QB:   Player, Team, ATT, CMP, YDS, TDS, INTS, ATT.1, YDS.1, TDS.1, FL, FPTS
FLEX: Player, Team, POS, ATT, YDS, TDS, REC, YDS.1, TDS.1, FL, FPTS
```

FantasyPros CSV market mapping:

```text
QB YDS      -> player_pass_yds
QB YDS.1    -> player_rush_yds
FLEX YDS    -> player_rush_yds
FLEX REC    -> player_receptions
FLEX YDS.1  -> player_reception_yds
```

QB rows emit passing yards and rushing yards when numeric, including legitimate zero rushing projections. FLEX rows emit RB rushing yards, receptions, and receiving yards; WR/TE receptions and receiving yards; and non-RB rushing only when meaningfully nonzero. Structural zero rush rows from the wide fantasy-football export are rejected as `not_applicable`. Receptions remain archived even though receptions betting is disabled elsewhere.

FantasyPros processed outputs are written under:

```text
data/processed/projections/fantasypros/{season}/week_{WW}/
```

For one logical snapshot, the adapter writes a combined long file plus rejected and validation outputs:

```text
08_19_26_1200_projections_long.csv
08_19_26_1200_projections_rejected.csv
08_19_26_1200_projections_validation.csv
projections_long.csv
```

FantasyPros API ingestion uses:

```text
GET https://api.fantasypros.com/public/v2/json/nfl/{season}/projections
header: x-api-key: <FANTASYPROS_API_KEY>
params: week, positions=QB:RB:WR:TE, scoring=STD
```

Run it with:

```powershell
.venv\Scripts\python.exe scripts\01_ingest\download_fantasypros_projections.py --season 2026 --week 1
```

The downloader fails clearly if `FANTASYPROS_API_KEY` is missing, sends the key only in the `x-api-key` header, and never writes the key to URLs, metadata, logs, or registry rows. It captures the actual completed request time in America/New_York with `captured_at_source=api_request`, then writes raw JSON under:

```text
data/raw/projections/fantasypros/{season}/week_{WW}/snapshots/{MM_DD_YY_HHMM}_api_projections.json
```

The processed API outputs use the same `fantasypros` source and the same canonical long schema, with additional lineage columns such as `source_format=api`, `fantasypros_player_id`, `source_json_path`, and `endpoint_component`. The API field mapping is:

```text
stats.pass_yds -> player_pass_yds
stats.rush_yds -> player_rush_yds
stats.rec_rec  -> player_receptions
stats.rec_yds  -> player_reception_yds
```

Structural zeroes are filtered by position-market applicability. Legitimate zero projections remain valid for applicable player/market rows.

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

FantasyPros CSV rows additionally include `source_file_type` (`qb` or `flex`) while preserving `raw_file`, `source_row_number`, and `source_column` lineage back to the component export. FantasyPros API rows include `source_format=api`, `source_file_type=api`, `fantasypros_player_id`, `source_json_path`, and endpoint component lineage.

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

Single-file providers such as PFF and FantasyPros API JSON use the raw file hash as the snapshot hash. Multi-file logical snapshots such as FantasyPros CSV use a deterministic logical hash derived from the sorted component file names and SHA-256 hashes. The registry keeps the legacy `raw_file` and `raw_file_sha256` columns populated for compatibility and adds component metadata columns for multi-file sources. FantasyPros API registry rows include `source_format=api`, endpoint path, HTTP status, and safe rate-limit headers when present.

## As-Of Selection

Consensus is built from the latest eligible snapshot per requested source for a given season, week, and as-of time. A FantasyPros QB/FLEX CSV pair and a FantasyPros API JSON file both enter as `source=fantasypros`; they are separate historical snapshots, not separate consensus sources. The latest eligible FantasyPros snapshot wins, regardless of CSV/API format.

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

The live projection infrastructure currently has PFF and FantasyPros ingested for 2026 week 1. PFF produces 1,286 canonical long rows, and FantasyPros produces 1,505 canonical long rows from one QB/FLEX logical snapshot. Two-source overlap rows are retained for audit, but they remain ineligible under the default three-source rule.

## Commands

Ingest one new PFF snapshot:

```powershell
.venv\Scripts\python.exe scripts\01_ingest\ingest_projection_snapshots.py --source pff --season 2026 --week 1 --input data\raw\projections\pff\2026\week_01\snapshots\08_04_26_1100projections.csv
```

Discover and ingest all PFF snapshots for a week:

```powershell
.venv\Scripts\python.exe scripts\01_ingest\ingest_projection_snapshots.py --source pff --season 2026 --week 1
```

Discover and ingest the FantasyPros QB/FLEX logical snapshot for a week:

```powershell
.venv\Scripts\python.exe scripts\01_ingest\ingest_projection_snapshots.py --source fantasypros --season 2026 --week 1
```

Rebuild the registry:

```powershell
.venv\Scripts\python.exe scripts\01_ingest\build_projection_registry.py --season 2026 --week 1 --rebuild
```

Build PFF + FantasyPros consensus:

```powershell
.venv\Scripts\python.exe scripts\02_processing\build_projection_consensus.py --season 2026 --week 1 --as-of 2026-08-19T13:00:00-04:00 --sources pff fantasypros --overwrite
```

Audit FantasyPros CSV/API snapshot changes:

```powershell
.venv\Scripts\python.exe scripts\04_analysis\audit_fantasypros_api_vs_csv.py --season 2026 --week 1
```

Use an as-of before the API capture and after the August 19 CSV capture to select the CSV snapshot. Use an as-of after the API capture to select the API snapshot. With only PFF and FantasyPros available, `projection_count` should not exceed 2, and the default `--min-sources 3` should leave rows ineligible.

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

- Only PFF and FantasyPros are live, so current consensus output is a two-source projection layer rather than a three-source eligible consensus under the default rule.
- There is no sportsbook main-line or alternate-line ingestion connected to this pipeline yet.
- Eligibility does not evaluate market prices, odds, line availability, or bet EV.
- Snapshot stage and days-before-week-start are reserved fields and currently default to unknown/blank.
- Name/team conflicts are flagged, not resolved by an identity mapping service.
- Existing holdout autopsy regression tests require `scipy` for Spearman correlation.
- FantasyPros API errors are not retried aggressively. HTTP 401/403, 404, 429, 5xx, malformed JSON, and empty projection payloads fail clearly without saving secret-bearing data.

## Recommended Next Task

Build sportsbook main-line and alternate-line ingestion/evaluation as the next layer. That work should join book lines to canonical player-market projections, evaluate main-line and alternate-line pricing separately, and keep backtest generation isolated from the projection snapshot registry and consensus source-selection logic.
