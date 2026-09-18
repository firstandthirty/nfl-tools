# PFF Weekly Analysis Methodology

This layer reads only processed PFF CSVs from `data/processed/pff/<season>/week_<WW>/`. It does not call the PFF API and does not create betting signals, polished tweets, arbitrary labels, or opaque scores.

## Qualifiers

- QB: `dropbacks >= 20`.
- Receiving route-rate views: `routes >= 15`.
- Rushing rate views: `attempts >= 8`.
- Pass blocking: normal offensive-line positions only (`C`, `G`, `T`, `LG`, `RG`, `LT`, `RT`) and `pass_block_snaps / team_max_ol_pass_block_snaps >= 0.75`.
- Pass rush rate views: `pass_rush_snaps >= 15`.
- Run defense rate views: `run_defense_snaps >= 15`.
- Coverage rate/rating views: `coverage_snaps >= 20` and `targets >= 4`.
- Team defense: every team with valid man/zone coverage-scheme data.

## Formulas

- `pressure_rate_faced`: `def_gen_pressures / dropbacks`.
- `twp_per_dropback`: `turnover_worthy_plays / dropbacks`.
- `btt_per_dropback`: `big_time_throws / dropbacks`.
- `int_minus_twp`: `interceptions - turnover_worthy_plays`.
- `targets_per_route_run`: `targets / routes`.
- `catch_rate_derived`: `receptions / targets`.
- `yards_per_target`: `yards / targets`.
- `yards_after_contact_per_attempt`: `yards_after_contact / attempts`.
- `missed_tackles_forced_per_attempt`: `avoided_tackles / attempts` when `avoided_tackles` is present.
- `yards_per_carry`: `yards / attempts`.
- `pressure_rate_allowed`: `pressures_allowed / pass_block_snaps`.
- `pressure_rate`: `total_pressures / pass_rush_snaps`.
- `run_stop_rate`: `stops / run_defense_snaps`.
- `catch_rate_allowed`: `receptions / targets`.
- `yards_per_target_allowed`: `yards / targets`.
- `forced_incompletion_rate`: `forced_incompletes / targets`.
- `man_coverage_rate`: `sum(man_snap_counts_coverage) / (sum(man_snap_counts_coverage) + sum(zone_snap_counts_coverage))`.
- `zone_coverage_rate`: `sum(zone_snap_counts_coverage) / (sum(man_snap_counts_coverage) + sum(zone_snap_counts_coverage))`.

Division by zero leaves the derived field missing.

## Ranking Direction

- Higher ranks better or more notable for: pressures, pressure rate, targets, targets per route, YPRR, rushing YAC/attempt, missed tackles forced/attempt, sacks allowed, pressures allowed, pass-rush win rate, run stops, stop rate, forced incompletion rate, man coverage rate, and zone coverage rate.
- Lower ranks better for: pass-blocking efficiency, passer rating allowed, yards per target allowed, and man/zone balance delta.
- Volume leaderboards may include low-sample players, but rate leaderboards use qualifiers.

## Story Rules

- QB: high pressure rate; high pressure rate plus time-to-throw context; at least 2 turnover-worthy plays with 0 interceptions; interceptions greater than turnover-worthy plays.
- Receiving: top targets per route; top YPRR; high target volume despite modest routes.
- Rushing: top yards after contact per attempt; top missed tackles forced per attempt.
- Pass blocking: zero pressures on qualified high snap volume; multiple pressures allowed on qualified high snap volume.
- Pass rush: top pressure total plus top-quartile win rate; top-quartile win rate with below-median pressure total.
- Run defense: top stop volume plus top stop rate.
- Coverage: low passer rating allowed on meaningful target volume; high target volume with low efficiency allowed; strong forced incompletion rate.
- Rookie: rookie ranked top 10 in a qualified category.
- Team defense: extreme man/zone usage.

## Known Limitations

- Blitz rate is unavailable from the current PFF API dataset.
- Cover 0/1/2/3/4/6 usage is unavailable from the current PFF API dataset.
- Receiving alignment route counts are unavailable; the processed data has alignment snaps and rates.
- Pressure is not blitzing. A defense can generate pressure with four rushers, and a blitz can fail to create pressure, so this layer does not infer blitz rate from pressure.
- Turnover-worthy plays versus interceptions is only a heuristic research flag. Interceptions are affected by many factors, but not purely luck.
