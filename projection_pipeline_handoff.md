[1mdiff --git a/player_props/docs/projection_pipeline_handoff.md b/player_props/docs/projection_pipeline_handoff.md[m
[1mnew file mode 100644[m
[1mindex 0000000..c12af1e[m
[1m--- /dev/null[m
[1m+++ b/player_props/docs/projection_pipeline_handoff.md[m
[36m@@ -0,0 +1,175 @@[m
[32m+[m[32m# Projection Pipeline Handoff[m
[32m+[m
[32m+[m[32m## Raw Snapshot Convention[m
[32m+[m
[32m+[m[32mRaw provider projection files live under:[m
[32m+[m
[32m+[m[32m```text[m
[32m+[m[32mdata/raw/projections/{source}/{season}/week_{WW}/snapshots/[m
[32m+[m[32m```[m
[32m+[m
[32m+[m[32mUse zero-padded week folders for raw snapshots, for example `week_01`. PFF snapshot filenames should begin with the capture timestamp in `MM_DD_YY_HHMM` local New York time, for example `08_04_26_1100projections.csv`. If a filename cannot be parsed, ingestion falls back to the file modification time and records `captured_at_source=filesystem_mtime`.[m
[32m+[m
[32m+[m[32mRaw snapshots are append-only evidence. Do not edit them in place after ingestion.[m
[32m+[m
[32m+[m[32m## PFF Adapter Flow[m
[32m+[m
[32m+[m[32mThe PFF ingestion CLI discovers or accepts a raw CSV, parses snapshot metadata, validates required PFF columns, transforms each applicable player stat into canonical long rows, writes validation and rejection outputs, appends rows into the weekly long file without duplicating identical canonical keys, and optionally rebuilds the snapshot registry.[m
[32m+[m
[32m+[m[32mPFF input columns currently required:[m
[32m+[m
[32m+[m[32m```text[m
[32m+[m[32mplayerName, teamName, position, passYds, rushYds, recvYds, recvReceptions[m
[32m+[m[32m```[m
[32m+[m
[32m+[m[32mPFF market mapping:[m
[32m+[m
[32m+[m[32m```text[m
[32m+[m[32mpassYds -> player_pass_yds[m
[32m+[m[32mrushYds -> player_rush_yds[m
[32m+[m[32mrecvYds -> player_reception_yds[m
[32m+[m[32mrecvReceptions -> player_receptions[m
[32m+[m[32m```[m
[32m+[m
[32m+[m[32mStructural zeroes are filtered where the position-market combination is not applicable, while nontraditional nonzero values are retained.[m
[32m+[m
[32m+[m[32m## Canonical Long Projection Schema[m
[32m+[m
[32m+[m[32mProjection adapters should emit one row per source, season, week, captured snapshot, player, and market. The core schema is:[m
[32m+[m
[32m+[m[32m```text[m
[32m+[m[32mplayer[m
[32m+[m[32mplayer_normalized[m
[32m+[m[32mteam[m
[32m+[m[32mposition[m
[32m+[m[32mseason[m
[32m+[m[32mweek[m
[32m+[m[32msource[m
[32m+[m[32mmarket[m
[32m+[m[32mprojection[m
[32m+[m[32mcaptured_at[m
[32m+[m[32mcaptured_at_source[m
[32m+[m[32mraw_file[m
[32m+[m[32m```[m
[32m+[m
[32m+[m[32mCurrent PFF rows also include source/audit columns such as `team_raw`, `source_player_id`, `source_row_number`, and `source_column`.[m
[32m+[m
[32m+[m[32mThe canonical identity is:[m
[32m+[m
[32m+[m[32m```text[m
[32m+[m[32msource, season, week, captured_at, player_normalized, market[m
[32m+[m[32m```[m
[32m+[m
[32m+[m[32m## Snapshot Registry[m
[32m+[m
[32m+[m[32mThe registry turns processed snapshots into a source-agnostic inventory with hashes, row counts, quality fields, coverage summaries, and conflict detection. Its primary output is:[m
[32m+[m
[32m+[m[32m```text[m
[32m+[m[32mdata/processed/projections/snapshot_registry.csv[m
[32m+[m[32m```[m
[32m+[m
[32m+[m[32mRelated outputs:[m
[32m+[m
[32m+[m[32m```text[m
[32m+[m[32mdata/processed/projections/registry_conflicts.csv[m
[32m+[m[32mdata/processed/projections/coverage_reports/weekly_coverage.csv[m
[32m+[m[32mdata/processed/projections/coverage_reports/snapshot_changes.csv[m
[32m+[m[32mdata/processed/projections/coverage_reports/{source}_{season}_week_{WW}_{captured_at}_coverage.csv[m
[32m+[m[32m```[m
[32m+[m
[32m+[m[32m## As-Of Selection[m
[32m+[m
[32m+[m[32mConsensus is built from the latest eligible snapshot per requested source for a given season, week, and as-of time.[m
[32m+[m
[32m+[m[32mRules:[m
[32m+[m
[32m+[m[32m- Naive `--as-of` values are localized to America/New_York.[m
[32m+[m[32m- Timezone-aware `--as-of` values preserve the same instant.[m
[32m+[m[32m- A snapshot is eligible when `captured_at <= as_of`.[m
[32m+[m[32m- Future snapshots are excluded.[m
[32m+[m[32m- Exact timestamp equality is eligible.[m
[32m+[m[32m- Missing sources are reported as `source_not_available`.[m
[32m+[m[32m- Sources with no snapshot before as-of are reported as `no_snapshot_before_as_of`.[m
[32m+[m[32m- Multiple eligible snapshots with the same latest timestamp are flagged as a conflict.[m
[32m+[m
[32m+[m[32m## Consensus Aggregation[m
[32m+[m
[32m+[m[32mConsensus groups selected source rows by:[m
[32m+[m
[32m+[m[32m```text[m
[32m+[m[32mplayer_normalized, market[m
[32m+[m[32m```[m
[32m+[m
[32m+[m[32mFor each group it calculates count, mean, median, sample standard deviation, min, max, range, coefficient of variation, source list, source values, snapshot age, source time range, player/team/position conflicts, and deviation metrics.[m
[32m+[m
[32m+[m[32mPairwise outputs are generated for overlapping player-market keys between selected sources. Source names and source value strings are sorted deterministically.[m
[32m+[m
[32m+[m[32m## Eligibility Rules[m
[32m+[m
[32m+[m[32mRows are marked `consensus_eligible` only when all configured checks pass:[m
[32m+[m
[32m+[m[32m- `projection_count >= --min-sources`, default `3`.[m
[32m+[m[32m- `projection_std <= --max-projection-std`, when configured.[m
[32m+[m[32m- `projection_range <= --max-projection-range`, when configured.[m
[32m+[m[32m- all `--required-sources` are present, when configured.[m
[32m+[m[32m- snapshot age is below `--max-snapshot-age-hours`, when configured.[m
[32m+[m[32m- selected source timestamp gap is within `--max-source-time-gap-hours`, when configured.[m
[32m+[m
[32m+[m[32mSingle-source rows are retained for visibility but are not treated as true multi-source consensus when `--min-sources` remains at the default.[m
[32m+[m
[32m+[m[32m## Current Live Status[m
[32m+[m
[32m+[m[32mThe live projection infrastructure currently has PFF as the only ingested provider. For 2026 week 1, the current processed PFF snapshot produces 1,286 canonical long rows. Because only PFF is live, consensus outputs are intentionally PFF-only and ineligible under the default three-source rule.[m
[32m+[m
[32m+[m[32m## Commands[m
[32m+[m
[32m+[m[32mIngest one new PFF snapshot:[m
[32m+[m
[32m+[m[32m```powershell[m
[32m+[m[32m.venv\Scripts\python.exe scripts\01_ingest\ingest_projection_snapshots.py --source pff --season 2026 --week 1 --input data\raw\projections\pff\2026\week_01\snapshots\08_04_26_1100projections.csv[m
[32m+[m[32m```[m
[32m+[m
[32m+[m[32mDiscover and ingest all PFF snapshots for a week:[m
[32m+[m
[32m+[m[32m```powershell[m
[32m+[m[32m.venv\Scripts\python.exe scripts\01_ingest\ingest_projection_snapshots.py --source pff --season 2026 --week 1[m
[32m+[m[32m```[m
[32m+[m
[32m+[m[32mRebuild the registry:[m
[32m+[m
[32m+[m[32m```powershell[m
[32m+[m[32m.venv\Scripts\python.exe scripts\01_ingest\build_projection_registry.py --source pff --season 2026 --week 1 --rebuild[m
[32m+[m[32m```[m
[32m+[m
[32m+[m[32mBuild consensus:[m
[32m+[m
[32m+[m[32m```powershell[m
[32m+[m[32m.venv\Scripts\python.exe scripts\02_processing\build_projection_consensus.py --season 2026 --week 1 --as-of 2026-08-04T13:30:00-04:00 --sources pff --overwrite[m
[32m+[m[32m```[m
[32m+[m
[32m+[m[32m## Future Source Adapter Integration[m
[32m+[m
[32m+[m[32mA future adapter should:[m
[32m+[m
[32m+[m[32m- Place immutable raw files in the same `data/raw/projections/{source}/{season}/week_{WW}/snapshots/` convention.[m
[32m+[m[32m- Parse or derive `captured_at` and record `captured_at_source`.[m
[32m+[m[32m- Validate provider-speci