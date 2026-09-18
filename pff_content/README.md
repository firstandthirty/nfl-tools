# PFF Content

Reusable PFF data foundation for internal First & Thirty NFL weekly analytics/content research.

This is not a betting model and does not modify `player_props` artifacts. The current phase fetches, caches, normalizes, inventories, and validates PFF data only. It does not build leaderboards, tweet copy, rankings, or subjective content logic.

## Layout

- `src/pff_content/config.py`: API base and key loading.
- `src/pff_content/client.py`: authenticated PFF GET client with retry and sanitized errors.
- `src/pff_content/cache.py`: deterministic raw JSON cache.
- `src/pff_content/normalize.py`: stable CSV normalization and deterministic derived fields.
- `src/pff_content/schemas.py`: schema inventory and validation report helpers.
- `scripts/fetch_week.py`: fetch or reuse raw weekly API responses.
- `scripts/build_processed_week.py`: build processed CSVs from raw cache.
- `scripts/inspect_schemas.py`: summarize processed schema inventory.
- `scripts/build_weekly_analysis.py`: build transparent weekly analysis CSVs and Markdown research report from processed data only.
- `scripts/build_charts.py`: build social-ready PNG charts from weekly analysis CSVs.
- `docs/pff_api_discovery.md`: API discovery findings.
- `docs/processed_data_dictionary.md`: processed table and derived field documentation.
- `docs/analysis_methodology.md`: qualifiers, formulas, ranking direction, story rules, and limitations.

## Auth

Configuration prefers `PFF_API_KEY` from the current process environment. If absent, it loads the existing shared env file from:

```text
../player_props.env
../player_props/.env
```

The key is never printed.

## Week 1 Commands

From this directory:

```bat
..\player_props\props_env\Scripts\python.exe -B scripts\test_pff_connection.py
..\player_props\props_env\Scripts\python.exe -B scripts\fetch_week.py --season 2026 --week 1
..\player_props\props_env\Scripts\python.exe -B scripts\build_processed_week.py --season 2026 --week 1
..\player_props\props_env\Scripts\python.exe -B scripts\inspect_schemas.py --season 2026 --week 1
..\player_props\props_env\Scripts\python.exe -B scripts\build_weekly_analysis.py --season 2026 --week 1
..\player_props\props_env\Scripts\python.exe -B scripts\build_charts.py --season 2026 --week 1
```

Use `--refresh` with `fetch_week.py` to bypass existing cache and rebuild raw responses.

## Cache Behavior

Raw responses are stored under:

```text
data/raw/pff/<season>/week_<WW>/<dataset>/<request_hash>.json
```

The request hash is based on endpoint path and sorted query parameters, so equivalent parameter ordering hits the same cache file. Adjacent metadata records endpoint, sanitized params, fetch time, status, safe headers, table name, row count, and response hash.

## Processed Outputs

Processed CSVs are written to:

```text
data/processed/pff/<season>/week_<WW>/
```

Expected outputs are `games.csv`, `passing.csv`, `receiving.csv`, `rushing.csv`, `pass_blocking.csv`, `pass_rush.csv`, `run_defense.csv`, `coverage.csv`, `coverage_scheme.csv`, `time_in_pocket.csv`, `schema_inventory.csv`, and `validation_report.csv`.

## Analysis Outputs

Weekly content-analysis outputs are written to:

```text
outputs/<season>/week_<WW>/
```

Expected outputs are `qbs.csv`, `receiving.csv`, `rushing.csv`, `pass_blocking.csv`, `pass_rush.csv`, `run_defense.csv`, `coverage.csv`, `team_defense.csv`, `rookies.csv`, `stories.csv`, and `weekly_research_report.md`.

Chart outputs are written under `outputs/<season>/week_<WW>/charts/`. The first chart is `rb_ypa_vs_yaco.png`, with a companion `rb_ypa_vs_yaco.csv` containing the plotted dataframe.

The analysis step uses processed CSVs only. If processed data is missing, run `scripts/fetch_week.py` and `scripts/build_processed_week.py` first.

## Tests

```bat
..\player_props\props_env\Scripts\python.exe -B -m unittest discover
```


