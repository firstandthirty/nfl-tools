# Team Coverage Tendency Audit

## Summary

Classification: `VALID_PLAYER_ASSIGNMENT_RATE_ONLY`

The current PFF data supports team-level shares of recorded player coverage assignments classified as man or zone. It does not support a reliable team defensive coverage-play rate from the available endpoint.

Do not describe the current values as "percentage of defensive pass plays using man coverage." Safer public language is "man coverage assignment share" or "share of recorded coverage assignments classified as man."

## Endpoint

Endpoint: `/v1/facet/defense/coverage_scheme`

Configured dataset: `coverage_scheme`

Cached raw file inspected:

`data/raw/pff/2026/week_01/coverage_scheme/cd84ac8bee19d7ee.json`

Processed file inspected:

`data/processed/pff/2026/week_01/coverage_scheme.csv`

Weekly analysis aggregate inspected:

`outputs/2026/week_01/team_defense.csv`

## Endpoint Grain

The raw endpoint grain is player-level for a week/team/game context, with separate man and zone splits on each row.

It is best described as:

`player-game coverage-scheme split`

Each row contains one player and includes fields such as:

- `player`
- `player_id`
- `team`
- `position`
- `man_snap_counts_coverage`
- `zone_snap_counts_coverage`
- `man_targets`
- `zone_targets`
- `man_qb_rating_against`
- `zone_qb_rating_against`
- `man_forced_incompletes`
- `zone_forced_incompletes`

It is not a team-play table. It is not one row per defensive pass play. It is not one row per team coverage call.

## Representative Raw Rows

IND examples:

| player | position | man snaps | zone snaps | man targets | zone targets |
| --- | --- | ---: | ---: | ---: | ---: |
| Akeem Davis-Gaither | LB | 13 | 10 | 1 | 1 |
| Camryn Bynum | S | 16 | 10 | 3 | 0 |
| Charvarius Ward | CB | 18 | 10 | 2 | 2 |
| Sauce Gardner | CB | 19 | 10 | 2 | 0 |

CHI examples:

| player | position | man snaps | zone snaps | man targets | zone targets |
| --- | --- | ---: | ---: | ---: | ---: |
| Devin Bush | LB | 14 | 18 | 1 | 1 |
| T.J. Edwards | LB | 13 | 19 | 0 | 2 |
| Cam Lewis | S | 19 | 18 | 1 | 1 |
| Jaylon Johnson | CB | 22 | 18 | 2 | 5 |

DET examples:

| player | position | man snaps | zone snaps | man targets | zone targets |
| --- | --- | ---: | ---: | ---: | ---: |
| D.J. Reed | CB | 20 | 40 | 1 | 6 |
| Rock Ya-Sin | CB | 20 | 39 | 5 | 4 |
| Avonte Maddox | S | 19 | 36 | 3 | 3 |
| Derrick Barnes | LB | 10 | 28 | 2 | 4 |

PIT examples:

| player | position | man snaps | zone snaps | man targets | zone targets |
| --- | --- | ---: | ---: | ---: | ---: |
| Jalen Ramsey | S | 0 | 24 | 0 | 3 |
| Jamel Dean | CB | 0 | 25 | 0 | 1 |
| Patrick Queen | LB | 0 | 25 | 0 | 2 |
| Payton Wilson | LB | 0 | 25 | 0 | 5 |

## Current Aggregation Before This Audit

`src/pff_content/analysis/team_defense.py` grouped processed `coverage_scheme.csv` by:

`season`, `week`, `team`, `opponent`

It summed player-level fields:

- `man_snap_counts_coverage`
- `zone_snap_counts_coverage`
- target/reception/yard/forced-incompletion split fields

It then calculated:

`total_scheme_coverage_snaps = sum(player man coverage snaps) + sum(player zone coverage snaps)`

`man_coverage_rate = sum(player man coverage snaps) / total_scheme_coverage_snaps`

`zone_coverage_rate = sum(player zone coverage snaps) / total_scheme_coverage_snaps`

## Why Denominators Exceed Game Play Counts

The denominator is a sum of player coverage assignments/snaps, not team defensive pass plays.

Week 1 examples:

| team | opponent | summed man assignments | summed zone assignments | total assignments |
| --- | --- | ---: | ---: | ---: |
| IND | BLT | 116 | 72 | 188 |
| CHI | CAR | 132 | 130 | 262 |
| DET | NO | 118 | 272 | 390 |
| PIT | ATL | 0 | 174 | 174 |

Those totals can exceed a single-game defensive pass-play count because multiple defenders can record coverage assignments on the same play.

## Mathematical Defensibility

The ratio:

`sum(player man coverage assignments) / (sum(player man assignments) + sum(player zone assignments))`

is mathematically defensible as a player-assignment share.

It is not necessarily mathematically equivalent to:

`team defensive pass plays in man coverage / total team defensive pass plays`

because the endpoint does not provide one team-level scheme label per play or a team-level scheme-play denominator. Different coverage calls can involve multiple player assignments, and player participation can vary by package, role, and charting rules.

## Code Change From This Audit

The analysis now writes explicit assignment terminology:

- `total_scheme_coverage_assignments`
- `man_coverage_assignment_share`
- `zone_coverage_assignment_share`
- `man_zone_assignment_balance_delta`
- `coverage_tendency_classification`
- `coverage_tendency_note`

Backward-compatible aliases remain:

- `total_scheme_coverage_snaps`
- `man_coverage_rate`
- `zone_coverage_rate`
- `man_zone_balance_delta`

Those aliases should be treated as deprecated public language because they are assignment shares, not literal team play rates.

## Public Usage Recommendation

Safe:

- "IND had the highest man coverage assignment share in Week 1."
- "PIT had all recorded coverage assignments classified as zone in this endpoint."

Avoid:

- "IND played man coverage on 61.7% of defensive pass plays."
- "PIT played zone on 100% of pass plays."

## Better Calculation Availability

No better team defensive coverage-play-rate calculation is currently available from the inspected weekly PFF data.

The project has:

- player-level `coverage_scheme`
- processed team aggregation of player assignment splits
- team/opponent context from games normalization

The project does not currently have:

- play-level coverage scheme labels
- a team-level man/zone play count denominator
- a reliable team blitz-rate field

Final classification: `VALID_PLAYER_ASSIGNMENT_RATE_ONLY`
