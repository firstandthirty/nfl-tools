# Player Props Model Notes

## Current scope

* NFL player props
* FanDuel primary book
* Markets currently covered:

  * `player_pass_yds`
  * `player_receptions`
  * `player_reception_yds`
  * `player_rush_yds`
* Generalized config-driven modeling workflow is now in place.
* Historical market analysis remains separate from projection-driven betting recommendations.
* Existing market-specific scripts are still retained as reference implementations until the generalized workflow is fully trusted.

## Current market status

| Market          | Projection engine | Backtest / historical validation | Current status                                        |
| --------------- | ----------------: | -------------------------------: | ----------------------------------------------------- |
| Passing yards   |         Validated |                        Validated | V1 complete                                           |
| Receiving yards |         Validated |                        Validated | V1 complete                                    |
| Rushing yards   |         Validated |                        Validated | Tested; paused                                        |
| Receptions      |         Validated |            Blocked intentionally | Projection V1 complete; backtest requires stable keys |

## Architecture / workflow

### Core principle

Historical diagnostics and projection-driven recommendations should stay separate.

* Historical market analysis answers: “How has this market behaved historically?”
* Projection engines answer: “Given current lines and projections, what looks +EV?”
* Backtests answer: “Did the projection-driven recommendation logic work historically?”

### Market config

Market-specific behavior is centralized in:

```text
scripts/00_config/market_config.py
```

The goal of this config is to avoid copy/paste contamination across markets. It should control market-specific details such as:

* market key
* display name
* projection column
* actual/stat column
* line column
* output slug
* input/output paths
* odds format
* distribution/model type
* variance buckets
* simulation settings
* EV filters
* side filters
* recommendation thresholds
* backtest merge keys

### Generalized modeling scripts

Primary generalized scripts:

```text
scripts/03_modeling/build_market_projection_engine.py
scripts/03_modeling/backtest_market_model.py
```

These now support:

```text
--market player_pass_yds
--market player_receptions
--market player_reception_yds
--market player_rush_yds
```

CLI arguments should override config defaults, but market-specific defaults should come from `MARKET_CONFIG` wherever possible.

### Legacy/reference scripts

Market-specific scripts remain in the repo for parity validation and reference behavior. Do not delete these yet.

Important reference scripts include:

```text
scripts/03_modeling/build_receiving_yds_projection_engine.py
scripts/03_modeling/backtest_receiving_yds_model.py
scripts/03_modeling/build_rush_yds_projection_engine.py
scripts/03_modeling/backtest_rush_yds_model.py
scripts/03_modeling/build_receptions_projection_engine.py
scripts/03_modeling/build_projection_ensemble_engine.py
scripts/03_modeling/simulate_pass_yds.py
```

Some older notes/scripts may still reference `scripts/04_analysis/`; the active modeling path is now under `scripts/03_modeling/`.

## Validation status of generalized workflow

### Receiving yards

Generalized workflow:

```text
python scripts/03_modeling/build_market_projection_engine.py --market player_reception_yds
python scripts/03_modeling/backtest_market_model.py --market player_reception_yds
```

Validation:

* Projection parity: validated against the receiving-yards reference script.
* Backtest parity: validated against the receiving-yards reference backtest.
* Backtest summary remained unchanged after later migrations:

  * Bets: `659`
  * Wins: `334`
  * ROI: `-3.2327%`
  * Profit units: `-21.303511`

### Receiving Yards Improvement

Added one receiving-only suppression rule after diagnostic and holdout testing:

Suppress `player_reception_yds` recommendations when:

- side = over
- position = WR
- team is favorite
- line >= 50

Rationale: historical diagnostics showed consistent overconfidence and projection inflation on high-line favorite WR overs. This segment was the clearest structural failure and survived chronological 2024 holdout checks.

Before / after:

| Metric | Before | After |
|---|---:|---:|
| Bets | 659 | 568 |
| Wins | 334 | 299 |
| Hit Rate | 50.68% | 52.64% |
| Profit Units | -21.30 | +2.88 |
| ROI | -3.23% | +0.51% |

No variance, STD inflation, EV threshold, totals, edge bucket, generalized workflow, or backtest logic was changed.

### 2023 Receiving Yards Validation Status

Attempted to expand receiving-yards validation to 2023.

Prep-layer work completed:
- 2023 historical props can be assigned season/week.
- 2023 receiving props can join to PFF actuals.
- 2023 game context can be built and merged.
- Season-scoped outputs prevent overwriting validated 2024 files.
- Projection source audit script added.

Current blocker:
- No valid local 2023 `fp_receiving_yds` projection source exists.
- Existing FantasyPros receiving files are hindsight-contaminated with later roster assignments.
  - Example: Derrick Henry listed as BAL in 2023 Week 1.
  - Saquon Barkley listed as PHI in 2023 Week 1.
  - Davante Adams listed as LAR in 2023 Week 1.
- Therefore, a clean 2023 receiving-yards model validation cannot be run yet.

Usable 2023 components:
- Historical receiving props
- Actual receiving yards
- Game context
- Team/favorite context for most rows

Not usable yet:
- 2023 FantasyPros receiving-yard projections

Decision:
- Do not generate 2023 receiving model picks from contaminated projections.
- Keep 2023 prep/audit infrastructure.
- Future path requires true point-in-time 2023 receiving-yard projections or another validated projection source.

### Rushing yards

Generalized workflow:

```text
python scripts/03_modeling/build_market_projection_engine.py --market player_rush_yds
python scripts/03_modeling/backtest_market_model.py --market player_rush_yds
```

Validation:

* Projection parity: validated against the rushing-yards reference script.
* Backtest parity: validated against the rushing-yards reference backtest.
* Backtest summary remained unchanged after later migrations:

  * Bets: `15`
  * Wins: `12`
  * ROI: `52.9560%`
  * Profit units: `7.943396`

Important caveat:

* The positive rushing result is based on only 15 under recommendations.
* Treat this as interesting, not proven.

### Receptions

Generalized workflow:

```text
python scripts/03_modeling/build_market_projection_engine.py --market player_receptions
```

Validation:

* Projection parity: validated against the existing receptions projection script.
* Rows: `102,482`
* Columns: `41`
* CSV contents matched byte-for-byte in parity validation.

Preserved behavior:

* Negative Binomial simulation
* player_norm-only merge
* no `min_line` filter, matching the legacy script
* same probability, EV, side choice, and recommendation behavior

Backtest status:

```text
python scripts/03_modeling/backtest_market_model.py --market player_receptions
```

This is intentionally blocked.

Reason:

* The parity-preserving receptions projection output lacks stable `season` and `week` keys.
* A historical backtest merge using only `player_norm` and `line` creates a many-to-many explosion.
* An earlier invalid run expanded 15,120 filtered picks into 223,844 matched rows.
* That output is not valid and should not be used.

Current behavior:

* The generalized backtest now fails loudly for receptions until stable join keys exist.
* Receptions backtesting requires a separate backtest-safe output or pipeline that preserves `season`, `week`, `player_norm`, and `line` without breaking projection parity.

Odds caveat fixed:

* Receptions uses decimal odds.
* Yardage backtests use American odds.
* `backtest_market_model.py` now supports config-driven odds handling.

### Passing yards

Generalized workflow:

```text
python scripts/03_modeling/build_market_projection_engine.py --market player_pass_yds
python scripts/03_modeling/backtest_market_model.py --market player_pass_yds
```

Validation:

* Projection parity: validated against `build_projection_ensemble_engine.py`.
* Historical simulation/backtest parity: validated against `simulate_pass_yds.py`.

Passing projection parity:

* Rows: `3`
* Columns: `23`
* CSV contents matched byte-for-byte.

Passing simulation parity:

* Rows: `444`
* Columns: `42`
* CSV contents matched byte-for-byte.

Important difference:

* Passing yards does not use the same projection/market merge contract as receiving and rushing yards.
* The reference passing ensemble reads one combined weekly input file and emits recommendations directly.
* The passing historical simulator operates on already-aligned historical prediction rows.

Legacy passing candidate policies:

| Candidate policy         | Bets | Wins |    ROI | Profit units |
| ------------------------ | ---: | ---: | -----: | -----------: |
| Over probability >= 55%  |  187 |  140 | 42.93% |    80.276492 |
| Under probability >= 55% |  142 |  118 | 58.64% |    83.272727 |

## Current scripts

### Backfills

```text
scripts/01_build/backfill_fanduel_pass_yds_history.py
scripts/01_build/backfill_fanduel_receptions_history.py
```

Additional backfills may exist or be needed for receiving/rushing yards depending on the current historical source setup.

### Market analysis

```text
scripts/04_analysis/analyze_market.py
```

Purpose:

* Historical market behavior
* residuals
* line buckets
* juice buckets
* ROI splits
* plots
* contextual splits where available

Supported / intended markets include:

```text
player_pass_yds
player_receptions
player_reception_yds
player_rush_yds
```

This script should remain a diagnostics tool, not a forward-looking recommendation engine.

### Projection / modeling

Primary generalized scripts:

```text
scripts/03_modeling/build_market_projection_engine.py
scripts/03_modeling/backtest_market_model.py
```

Legacy scripts remain reference implementations for now.

## Data / context notes

### FanDuel

* FanDuel remains the primary book for historical backfills and current-market evaluation.
* Side-specific prices matter.
* Do not evaluate edges using hit rate alone.
* A line at `Over +125 / Under -160` is fundamentally different from `-110 / -110`.

### Game context enrichment

Game context enrichment exists for historical receptions and should be reused downstream when possible:

* `home_spread`
* `away_spread`
* `game_total`
* `home_moneyline`
* `away_moneyline`
* `game_context_book`

Team-specific context is derived after the PFF join inside `analyze_market.py`, because PFF provides the player team/position mapping.

### PFF team abbreviations

PFF team abbreviations are nonstandard and require mapping before comparing to full home/away team names.

Examples:

```text
ARZ
BLT
CLV
HST
LA
```

Use abbreviation mapping before comparing PFF team to full `home_team` / `away_team`.

## Key findings: passing yards

### Historical behavior

* Market line behaves like a median.
* Over hit rate is close to 50%.
* Avg actual minus line is small and slightly positive.
* Clean residual sigma is approximately `68.5` yards.
* Residual shape is close enough to normal for a V1 probability model.

### Modeling interpretation

* Passing yards can use an analytic normal-CDF probability model.
* Around `+10` yards versus line starts becoming interesting.
* Around `+15` yards is stronger.
* Projection consensus matters. One-source hero ball is dangerous.

### Current status

* Passing yards V1 is complete.
* Generalized entry points now delegate to the validated legacy behavior.
* Projection and historical simulation parity are confirmed.

## Key findings: receptions

### Overall receptions market

Historical FanDuel receptions backfill:

* 2023: `2,005` rows
* 2024: `2,175` rows
* 2025: `2,721` rows
* Total: `6,901` raw rows
* Matched rows after PFF actuals join: `6,250`

Overall market behavior:

* Avg line: approximately `3.42` receptions
* Avg actual: approximately `3.59` receptions
* Avg actual minus line: approximately `+0.18`
* Median actual minus line: approximately `-0.5`
* Over hit rate: approximately `48.4%`
* Under hit rate: approximately `51.6%`

Interpretation:

* The typical player goes under.
* The distribution is right-skewed.
* Mean can sit above the line even when median and hit rate favor unders.
* This reinforces the core mean-projection-versus-median-line problem.

### Position-level receptions findings

* WR reception overs have been consistently poor historically.
* WR over ROI by line bucket was roughly `-11%` to `-14%` across most lines.
* WR unders were closer to breakeven, meaning much of the edge is eaten by vig.
* HB/RB low reception lines showed some over potential, especially `<= 2.5` receptions.
* TEs behave differently from WRs/RBs and may need separate treatment.

### Receptions + total bucket findings

WR high-total games were the strongest structural signal found:

WRs in games with total `47+`:

* Over ROI: approximately `-18.4%`
* Under ROI: approximately `+5.0%`
* Sample: approximately `874`

TEs in low-total games showed positive over ROI:

TE total `< 42`:

* Over ROI: approximately `+6.7%`
* Sample: approximately `450`

Interpretation:

* Public likely overbets WR reception overs in projected shootouts.
* TE behavior may be different in low-total games, possibly due to safety-valve or compressed passing-game dynamics.
* Needs further validation before being turned into a betting rule.

### WR underdog + high-total finding

Strongest discovered receptions angle:

* WR
* Underdog
* Game total `47+`
* Reception unders

Split:

WR underdog, total `47+`:

* Over ROI: approximately `-23.6%`
* Under ROI: approximately `+8.4%`
* Sample: approximately `431`

WR favorite, total `47+`:

* Over ROI: approximately `-13.3%`
* Under ROI: approximately `+1.6%`
* Sample: approximately `443`

Interpretation:

* The signal appears mostly concentrated in underdog WRs in high-total games.
* Public narrative is probably: trailing script + shootout = more WR catches.
* Books appear to tax that assumption heavily.

### WR underdog + high-total + line bucket

The signal is not uniform by line:

WR underdog, total `47+`, line `3.5`:

* Under ROI: approximately `+27.7%`
* Sample: approximately `81`

WR underdog, total `47+`, line `4.5`:

* Under ROI: approximately `+6.5%`
* Sample: approximately `78`

WR underdog, total `47+`, line `5.5`:

* Under ROI: approximately `-3.5%`
* Sample: approximately `81`

WR underdog, total `47+`, line `6.5`:

* Under ROI: approximately `+5.8%`
* Sample: approximately `55`

WR underdog, total `47+`, line `7+`:

* Under ROI: approximately `+9.7%`
* Sample: approximately `79`

Interpretation:

* Possible WR2/WR3 narrative trap at `3.5` to `4.5`.
* Books may be sharper on true WR1 reception lines around `5.5`.
* Higher star-WR lines can still show under value, but samples get thin.

### Juice-specific receptions note

Receptions must always be evaluated with side-specific juice.

* Lines are rarely priced symmetrically.
* A `3.5` reception line at `Over +125 / Under -160` is a different bet from `-110 / -110`.
* Any edge must survive the actual over/under prices, not just hit-rate assumptions.
* The WR underdog + high-total signal partially survived juice splits, but sample sizes get thin after slicing.

## Receptions model

### V1 approach

* Use fantasy/ensemble projected receptions as the mean input.
* Use a Negative Binomial simulation rather than normal distribution or plain Poisson.
* Receptions are discrete and overdispersed:

  * Poisson assumes variance equals mean.
  * NFL receptions have variance greater than mean due to game script, role volatility, injuries, target distribution, and play volume.
* Simulate integer reception outcomes.
* Compare:

  * `P(over)`
  * `P(under)`
  * fair odds
  * market odds
  * EV over
  * EV under

### V1 inputs

Projection file includes:

* player
* projected receptions or configured projection column
* position if available

Market file includes:

* player
* line
* over price
* under price
* position if available

Historical analysis file:

```text
data/analysis/receptions_market_analysis_rows.csv
```

### V1 output

```text
data/analysis/receptions_model_bets.csv
```

Important output columns:

* player
* position
* line
* projection
* projection_minus_line
* over_price
* under_price
* p_over
* p_under
* fair_over_price
* fair_under_price
* ev_over
* ev_under
* recommended_side
* recommended_prob
* recommended_ev_percent
* recommendation

### Current limitation

Projection parity is validated, but historical backtesting is intentionally blocked until a backtest-safe output exists.

Required future fix:

* Preserve stable historical keys such as:

  * `season`
  * `week`
  * `player_norm`
  * `line`
* Avoid many-to-many merges.
* Keep projection parity test separate from backtest-safe historical output if needed.

## Receiving yards model

### Historical setup

Historical receiving yards market analyzed:

* Approximately `2,424` historical rows.

Historical market characteristics:

* Avg line: approximately `32.2`
* Avg actual: approximately `36.5`
* Avg actual minus line: approximately `+4.3`
* Over hit rate: approximately `48.7%`
* Under hit rate: approximately `51.3%`

Interpretation:

* Distribution is right-skewed due to spike weeks.
* Mean tends to sit above the median/market line.
* Blind overs are not profitable despite average actual yards exceeding average line.

### Projection source

FantasyPros API:

```text
/public/v2/json/nfl/{season}/projections
```

Weekly ingestion script:

```text
scripts/01_build/ingest_fantasypros_weekly_projections_api.py
```

Projection column:

```text
fp_receiving_yds
```

### Model setup

Primary workflow:

```text
python scripts/03_modeling/build_market_projection_engine.py --market player_reception_yds
python scripts/03_modeling/backtest_market_model.py --market player_reception_yds
```

Legacy reference scripts:

```text
scripts/03_modeling/build_receiving_yds_projection_engine.py
scripts/03_modeling/backtest_receiving_yds_model.py
```

Methodology:

* Projection mean: FantasyPros `fp_receiving_yds`
* Simulation: Normal distribution
* Variance: historical variance by `position` and `line_bucket`
* Historical context included where available:

  * `game_total`
  * `team_spread`
  * `is_favorite`
  * `is_underdog`

### Tuned settings

```python
STD_INFLATION_FACTOR = 1.15
```

### Backtest result

Validated generalized backtest:

* Bets: `659`
* Wins: `334`
* ROI: `-3.2327%`
* Profit units: `-21.303511`

Interpretation:

* Baseline receiving-yards model was near breakeven but structurally overconfident in specific segments.
* Diagnostic + holdout analysis identified high-line favorite WR overs as the clearest failure pocket.
* A receiving-only suppression rule was added behind config:

  * side = over
  * position = WR
  * favorite
  * line >= 50

Post-filter validated backtest:

* Bets: `568`
* Wins: `299`
* ROI: `+0.51%`
* Profit units: `+2.88`

Interpretation:

* Improvement appears driven by reducing projection inflation and overconfidence on high-line favorite WR overs.
* Rule survived multiple chronological holdout splits in 2024.
* Treated as an experimental but explainable production filter pending additional seasons.

## Experimental production filters

### Receiving yards

Enabled (config controlled):

Exclude:

* `player_reception_yds`
* `recommended_side = over`
* `position = WR`
* `favorite`
* `line >= 50`

Status:

* Chronological holdout improvement observed in all 2024 splits.
* Still awaiting multi-season validation.
* Can be disabled via config.

## Rushing yards model

### Historical setup

Historical rushing yards market analyzed:

* Approximately `1,103` historical rows.

Historical market characteristics:

* Avg line: approximately `37.2`
* Avg actual: approximately `40.9`
* Avg actual minus line: approximately `+3.7`
* Over hit rate: approximately `48.9%`
* Under hit rate: approximately `51.1%`

Interpretation:

* Market appears more efficient than receiving yards.
* Distribution is right-skewed with fat tails due to explosive games.
* Books appear to shade rushing overs somewhat aggressively.

### Historical findings

#### QB vs RB matters

QB rushing and RB rushing behaved differently historically.

QB rushing:

* Roughly efficient market.
* Blind overs/unders showed little edge.

RB rushing:

* More exploitable behavior.
* Greater sensitivity to workload and game script.

Decision:

* Model variance separately by:

  * `position`
  * `line_bucket`

#### Line bucket observations

RB rushing overs struggled historically in the `20–40` rushing line bucket.

Possible interpretation:

* committee backs
* uncertain workloads
* books shading optimistic rushing outcomes

High rushing lines, especially `80+`, showed stronger over performance historically, but sample size was small.

### Projection source

FantasyPros API:

```text
/public/v2/json/nfl/{season}/projections
```

Weekly ingestion script:

```text
scripts/01_build/ingest_fantasypros_weekly_projections_api.py
```

Projection column:

```text
fp_rush_yds
```

### Model setup

Primary workflow:

```text
python scripts/03_modeling/build_market_projection_engine.py --market player_rush_yds
python scripts/03_modeling/backtest_market_model.py --market player_rush_yds
```

Legacy reference scripts:

```text
scripts/03_modeling/build_rush_yds_projection_engine.py
scripts/03_modeling/backtest_rush_yds_model.py
```

Methodology:

* Projection mean: FantasyPros `fp_rush_yds`
* Simulation: Normal distribution
* Variance: historical variance by `position` and `line_bucket`
* Historical context included where available:

  * `game_total`
  * `team_spread`
  * `is_favorite`
  * `is_underdog`

### Tuned settings

```python
STD_INFLATION_FACTOR = 1.25
```

### Backtest observations

Overs only, EV `2–10%`:

* Approximately `244` bets
* Hit rate: approximately `46.3%`
* ROI: approximately `-11.6%`

All sides, EV `2–10%`:

* Approximately `259` bets
* ROI: approximately `-7.8%`

Higher-confidence bets, EV `5–10%`, performed worse than lower-confidence bets, suggesting model overconfidence on rushing overs.

Increasing variance to `STD_INFLATION_FACTOR = 1.40` did not improve results.

### Unders experiment

Validated generalized under-filter result:

* Bets: `15`
* Wins: `12`
* ROI: approximately `+53%`
* Profit units: `7.943396`

Caveats:

* Sample is extremely small.
* No clear repeatable pattern emerged.
* Recommendations were sparse and inconsistent.
* Mix included backup RBs, committee backs, gadget players, and bell cows.

### Current status

Rushing yards is paused for now.

Conclusion:

* FantasyPros rushing projections do not currently appear predictive enough versus sportsbook lines.
* Overs showed strongly negative results.
* Unders may contain niche signal, but evidence is too sparse to trust.
* Better opportunity likely exists in other markets unless additional rushing context is added.

Potential future features:

* rush attempts projections
* snap share
* injury/workload signals
* team run rate
* RB usage splits
* offensive line / defensive front matchup

## Important implementation notes

* `analyze_market.py` should remain the historical-market-analysis script.
* Monte Carlo/projection scripts should not become historical-market-analysis scripts.
* Historical backfills should capture game context once and reuse it downstream.
* Player team context is best derived after joining PFF actuals because PFF supplies team/position.
* Market-specific behavior should live in `market_config.py` where practical.
* Generalized scripts should not hardcode projection columns, line columns, output paths, distributions, EV filters, or market-specific error messages.
* Preserve legacy scripts until generalized parity has been validated and enough future runs prove the new workflow is stable.

## Known limitations / blockers

### Receptions backtesting

Status: blocked intentionally.

Reason:

* Projection output is parity-preserving but lacks `season` and `week`.
* Historical joins on only `player_norm` and `line` create invalid many-to-many expansion.
* Any previous receptions backtest files created from that bad merge are invalid and should be ignored.

Future fix:

* Create a backtest-safe receptions output that carries stable keys.
* Keep the parity-preserving projection output separate if needed.
* Then validate a real receptions backtest.

### Projection source quality

FantasyPros projections are useful but imperfect.

Receiving and rushing yardage results suggest:

* Mean projections alone are not enough.
* Market lines behave more like medians.
* Right-skewed stat distributions create mean-vs-median traps.
* Extra context is likely needed for durable edges.

### Market-specific model differences

Not all markets should be forced into the same shape.

Examples:

* Passing yards uses an analytic normal-CDF ensemble style.
* Receiving and rushing yards use normal simulation with historical variance by position and line bucket.
* Receptions uses Negative Binomial count simulation.
* Receptions backtesting requires better keys before ROI can be trusted.

The generalized workflow should centralize orchestration and config, not pretend every market has the exact same statistical structure.

## Next work

### Immediate

1. Commit receiving-yards V1 improvements.
2. Preserve suppression audit outputs for future validation.
3. Keep legacy scripts as references.
4. Ignore/delete invalid receptions backtest artifacts.
5. Update README/project docs for generalized workflow..

### Near-term

1. Build backtest-safe receptions projection output.
2. Validate receptions ROI properly.
3. Add suppression audit outputs for receiving-yards experiments.
4. Add robust current-market ingestion for all supported markets.
5. Explore alt-line pricing support, starting with passing yards.
6. Pause receiving-yards tuning until a valid historical projection source exists.

### Medium-term

1. Add alt-line pricing support.
2. Add line-shopping support across books.
3. Add contextual calibration features:

   * spread
   * total
   * team implied total
   * favorite/underdog
   * position
   * line bucket
   * juice bucket
   * player role / usage proxies
4. Improve projections using multiple sources rather than FantasyPros alone.
5. Consider learning market-specific thresholds from historical backtests instead of manually tuning.

## Copy/paste commands

### Receiving yards

```cmd
python scripts\03_modeling\build_market_projection_engine.py --market player_reception_yds
python scripts\03_modeling\backtest_market_model.py --market player_reception_yds
```

### Rushing yards

```cmd
python scripts\03_modeling\build_market_projection_engine.py --market player_rush_yds
python scripts\03_modeling\backtest_market_model.py --market player_rush_yds
```

### Receptions

```cmd
python scripts\03_modeling\build_market_projection_engine.py --market player_receptions
```

Backtest is intentionally blocked until stable keys exist:

```cmd
python scripts\03_modeling\backtest_market_model.py --market player_receptions
```

### Passing yards

```cmd
python scripts\03_modeling\build_market_projection_engine.py --market player_pass_yds
python scripts\03_modeling\backtest_market_model.py --market player_pass_yds
```
