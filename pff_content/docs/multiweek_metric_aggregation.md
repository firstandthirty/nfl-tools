# Multiweek Metric Aggregation

This project treats time period as a first-class input. Weekly output remains
`outputs/<season>/week_<WW>/`; season-to-date output uses
`outputs/<season>/season_through_week_<WW>/`.

Implemented period types:

- `week`: one NFL week.
- `season`: Weeks 1 through N inclusive.

The internal `Period` model is ready for a future `range` period because it
already carries `season`, `period_type`, `start_week`, `end_week`,
`display_label`, and `output_slug`.

## Source Strategy

Season-to-date outputs are constructed from frozen processed weekly snapshots
under `data/processed/pff/<season>/week_<WW>/`. The API discovery doc confirms
PFF has v1 weekly facet endpoints and v2 team endpoints with `weekIds`,
`week`, and `weekTo`-style parameters. Those native endpoints may be useful for
validation, but this pipeline does not make mutable season/range API totals the
source of truth.

## Identity

Player aggregation groups by stable PFF `player_id` when present, falling back
to `player_name` only when no ID exists. The displayed `team` is the latest
team in the period, `team_list` records all teams seen, and `team_count`
records how many distinct teams appeared. Multiweek opponent context is
reported as `MULTI`.

Position and rookie fields use the latest row in the period. `games_represented`
is the count of distinct `game_id` values when available, otherwise distinct
weeks with rows.

## Qualifiers

Weekly qualifiers are unchanged:

- QB: 20+ dropbacks.
- Receiving: WR/TE, 15+ routes.
- Rushing: RB/HB/FB, 8+ attempts.
- OL: OL positions with pass-block snaps at least 75% of their team's max OL pass-block snaps.
- Pass rush: 15+ pass-rush snaps.
- Run defense: 15+ run-defense snaps.
- Coverage: 20+ coverage snaps and 4+ targets for target-based efficiency.

Season-to-date qualifiers currently use cumulative opportunities with the same
minimums. This preserves Week 1 reconciliation. The design is intentionally
configurable so later weeks can move to per-team-game or cumulative thresholds
without changing aggregation formulas. Byes and missed games are handled by
cumulative opportunity, not `week * weekly_threshold`.

## Metric Registry

The code registry lives in `src/pff_content/metric_registry.py`.

| Dataset | Metric | Fields | Class | Multiweek Formula | Exact | Season Supported | Caveat |
| --- | --- | --- | --- | --- | --- | --- | --- |
| passing | dropbacks, attempts, completions, yards, touchdowns, interceptions, turnover_worthy_plays, big_time_throws, def_gen_pressures, sacks | same fields | ADDITIVE | SUM(field) | yes | yes | Counting fields only. |
| passing | pressure_rate_faced | def_gen_pressures, dropbacks | RATIO_RECOMPUTABLE | SUM(def_gen_pressures) / SUM(dropbacks) | yes | yes | Uses current validated pressure numerator. |
| passing | twp_per_dropback | turnover_worthy_plays, dropbacks | RATIO_RECOMPUTABLE | SUM(TWP) / SUM(dropbacks) | yes | yes | TWP/INT card also uses raw TWP and INT counts. |
| passing | btt_per_dropback | big_time_throws, dropbacks | RATIO_RECOMPUTABLE | SUM(BTT) / SUM(dropbacks) | yes | yes |  |
| passing | avg_time_to_throw | avg_time_to_throw, dropbacks | WEIGHTED_RECOMPUTABLE | SUM(avg_time_to_throw * dropbacks) / SUM(dropbacks) | approximate | yes | PFF exposes weekly average; no raw throw-time sum is present. |
| passing | avg_depth_of_target | avg_depth_of_target, attempts | WEIGHTED_RECOMPUTABLE | SUM(aDOT * attempts) / SUM(attempts) | approximate | yes | Target/attempt weighting is used because raw air-yard sum is absent. |
| receiving | targets, routes, receptions, yards, yards_after_catch, slot_snaps, wide_snaps, inline_snaps | same fields | ADDITIVE | SUM(field) | yes | yes |  |
| receiving | targets_per_route_run | targets, routes | RATIO_RECOMPUTABLE | SUM(targets) / SUM(routes) | yes | yes | Never average weekly TPRR. |
| receiving | yprr | yards, routes | RATIO_RECOMPUTABLE | SUM(yards) / SUM(routes) | yes | yes | Week 1 native PFF YPRR differs only by PFF rounding. |
| receiving | slot_rate, wide_rate, inline_rate | alignment snaps, routes | RATIO_RECOMPUTABLE | SUM(alignment snaps) / SUM(routes) | yes | yes |  |
| receiving | caught_percent, drop_rate, contested_catch_rate, grades | native fields | NATIVE_NONADDITIVE | unsupported | no | no | Not used by official charts/leaderboards. |
| rushing | attempts, yards, yards_after_contact, avoided_tackles, touchdowns | same fields | ADDITIVE | SUM(field) | yes | yes |  |
| rushing | yards_per_carry | yards, attempts | RATIO_RECOMPUTABLE | SUM(yards) / SUM(attempts) | yes | yes |  |
| rushing | yards_after_contact_per_attempt | yards_after_contact, attempts | RATIO_RECOMPUTABLE | SUM(yards_after_contact) / SUM(attempts) | yes | yes |  |
| rushing | missed_tackles_forced_per_attempt | avoided_tackles, attempts | RATIO_RECOMPUTABLE | SUM(avoided_tackles) / SUM(attempts) | yes | yes | Falls back to `elu_rush_mtf` where existing weekly code does. |
| pass_blocking | pass_block_snaps, pressures_allowed, sacks_allowed, hits_allowed, hurries_allowed | same fields | ADDITIVE | SUM(field) | yes | yes |  |
| pass_blocking | pressure_rate_allowed | pressures_allowed, pass_block_snaps | RATIO_RECOMPUTABLE | SUM(pressures_allowed) / SUM(pass_block_snaps) | yes | yes |  |
| pass_blocking | pass_blocking_efficiency, true_pass_set_pbe | native fields | NATIVE_NONADDITIVE | unsupported | no | no | Current fields do not expose all PBE penalty components safely. |
| pass_rush | pass_rush_snaps, total_pressures, sacks, hits, hurries, pass_rush_wins, pass_rush_opp | same fields | ADDITIVE | SUM(field) | yes | yes |  |
| pass_rush | pressure_rate | total_pressures, pass_rush_snaps | RATIO_RECOMPUTABLE | SUM(total_pressures) / SUM(pass_rush_snaps) | yes | yes |  |
| pass_rush | pass_rush_win_rate | pass_rush_wins, pass_rush_opp | RATIO_RECOMPUTABLE | SUM(pass_rush_wins) / SUM(pass_rush_opp) | yes | yes | Week 1 native value differs only by PFF one-decimal percent rounding. |
| pass_rush | pass_rush_productivity, PRP, true_pass_set_prp | native fields | NATIVE_NONADDITIVE | unsupported | no | no | PRP formula is not reconstructed from current components. |
| run_defense | run_defense_snaps, run_stop_opp, stops, tackles, missed_tackles | same fields | ADDITIVE | SUM(field) | yes | yes |  |
| run_defense | run_stop_rate | stops, run_defense_snaps | RATIO_RECOMPUTABLE | SUM(stops) / SUM(run_defense_snaps) | yes | yes | PFF native stop percent is not averaged. |
| coverage | coverage_snaps, targets, receptions, yards, touchdowns_allowed, interceptions, forced_incompletes | same fields | ADDITIVE | SUM(field) | yes | yes |  |
| coverage | forced_incompletion_rate | forced_incompletes, targets | RATIO_RECOMPUTABLE | SUM(forced_incompletes) / SUM(targets) | yes | yes |  |
| coverage | passer_rating_when_targeted | receptions, targets, yards, TD, INT | RATIO_RECOMPUTABLE | NFL passer rating from cumulative components | yes | yes | Reconciles to Week 1 PFF within 0.05 rating points, PFF rounding. |
| coverage | yards_per_coverage_snap | yards, coverage_snaps | RATIO_RECOMPUTABLE | SUM(yards) / SUM(coverage_snaps) | yes | yes |  |
| coverage | aDOT | avg_depth_of_target, targets | WEIGHTED_RECOMPUTABLE | SUM(aDOT * targets) / SUM(targets) | approximate | not used | Raw air-yards not exposed in current weekly table. |
| team_defense | man_coverage_assignment_share | man and zone assignment counts | RATIO_RECOMPUTABLE | SUM(man assignments) / SUM(man + zone assignments) | yes | yes | Assignment shares only; not team defensive play rates. |

## Official Outputs Supported For Season-To-Date

Charts:

- RB YPC vs YAC/attempt.
- RB before vs after contact.
- Receiving TPRR vs YPRR.
- Pass-rush win rate vs pressure rate.
- QB pressure rate faced vs time to throw.
- Coverage targets vs passer rating allowed.
- QB TWP vs interceptions.

Leaderboards:

- Target earners.
- YPRR leaders.
- YAC/attempt leaders.
- Pressure leaders.
- Pass-rush win rate leaders.

Discovery:

- Season discovery uses the same section builders over season-qualified
  cumulative tables and writes period fields: `period_type`, `start_week`,
  `end_week`, `period_label`.

Unsupported native metrics are not approximated in season-to-date discovery.
This reduces season-through-Week-1 discovery rows for OL/pass-rush/rookie
sections because PBE/PRP rows are intentionally absent.

## Week 1 Reconciliation

Week 1 and season-through-Week-1 row counts match for primary analysis tables:

- qbs: 37
- receiving: 249
- rushing: 124
- pass_blocking: 353
- pass_rush: 449
- run_defense: 585
- coverage: 415
- team_defense: 32

Supported additive and recomputed metrics reconcile exactly except for native
rounded fields that are now recomputed from components:

- receiving `yprr`: max delta 0.005 from PFF weekly rounding.
- pass-rush `pass_rush_win_rate`: max delta 0.05 percentage points from PFF weekly rounding.
- coverage `passer_rating_when_targeted`: max delta 0.05 rating points from PFF weekly rounding.

These differences are expected and documented; no unexplained mismatches remain.
