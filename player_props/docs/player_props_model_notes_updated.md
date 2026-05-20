# Player Props Model Notes

## Current scope
- NFL player props
- FanDuel primary book
- Passing yards v1 complete
- Receptions historical market analysis in progress / mostly complete
- Monte Carlo projection engines separated from historical market analysis

## Architecture / workflow
- Use `analyze_market.py` for historical market behavior across markets.
- Use market-specific projection engines for forward-looking betting outputs.
- Keep historical diagnostics separate from projection-driven recommendations.
- FanDuel remains the primary book for backfill and current-market evaluation.
- Game context enrichment now exists for historical receptions:
  - `home_spread`
  - `away_spread`
  - `game_total`
  - `home_moneyline`
  - `away_moneyline`
  - `game_context_book`
- Team-specific context is derived after PFF join inside `analyze_market.py`, because PFF provides the player team/position mapping.

## Current scripts

### Backfills
- `scripts/01_build/backfill_fanduel_pass_yds_history.py`
- `scripts/01_build/backfill_fanduel_receptions_history.py`

### Market analysis
- `scripts/04_analysis/analyze_market.py`
  - Supports `--market player_pass_yds`
  - Supports `--market player_receptions`
  - Produces market summary, residuals, line buckets, juice buckets, ROI splits, and plots.
  - Receptions-specific outputs include position, line bucket, favorite/dog, spread bucket, and total bucket splits when data exists.

### Projection / modeling
- `scripts/04_analysis/build_projection_ensemble_engine.py`
  - Passing yards projection ensemble engine.
- `scripts/04_analysis/build_receptions_projection_engine.py`
  - New V1 receptions Monte Carlo engine.
  - Uses fantasy/ensemble receptions projections + current FanDuel reception lines.
  - Uses historical variance by position + line bucket.
  - Simulates discrete receptions with a Negative Binomial distribution.
  - Outputs `data/analysis/receptions_model_bets.csv`.

## Key findings: passing yards
- Market line behaves like median.
- Over hit rate ≈ 50.4%.
- Avg actual - line ≈ +0.6 yards.
- Clean residual sigma ≈ 68.5 yards.
- Normal-ish residual shape.
- Around +10 yards vs line starts becoming interesting.
- +15 yards is stronger.
- Need projection consensus, not one-source hero ball.

## Key findings: receptions

### Overall receptions market
- Historical FanDuel receptions backfill completed:
  - 2023: 2,005 rows
  - 2024: 2,175 rows
  - 2025: 2,721 rows
  - Total: 6,901 raw rows
  - 6,250 matched rows after PFF actuals join
- Overall market behavior:
  - Avg line ≈ 3.42 receptions
  - Avg actual ≈ 3.59 receptions
  - Avg actual - line ≈ +0.18
  - Median actual - line ≈ -0.5
  - Over hit rate ≈ 48.4%
  - Under hit rate ≈ 51.6%
- Interpretation:
  - Typical player goes under.
  - Distribution is right-skewed.
  - Mean can sit above line even when median and hit rate favor unders.
  - This reinforces the “mean projection vs median betting line” issue.

### Position-level receptions findings
- WR reception overs are consistently poor historically.
- WR over ROI by line bucket is roughly -11% to -14% across most lines.
- WR unders are closer to breakeven, meaning much of the edge is eaten by vig.
- HB/RB low reception lines show some over potential:
  - HB `<=2.5` receptions over performed well historically.
- TEs behave differently from WRs/RBs and may need separate treatment.

### Receptions + total bucket findings
- WR high-total games are the strongest structural signal so far:
  - WR in games with total 47+:
    - Over ROI ≈ -18.4%
    - Under ROI ≈ +5.0%
    - Sample ≈ 874
- TE low-total games showed positive over ROI:
  - TE total <42:
    - Over ROI ≈ +6.7%
    - Sample ≈ 450
- Interpretation:
  - Public likely overbets WR reception overs in projected shootouts.
  - TE behavior may be different in low-total games, possibly due to safety-valve / compressed passing-game dynamics, but this needs further validation.

### WR underdog + high-total finding
- Strongest discovered receptions angle:
  - WR
  - Underdog
  - Game total 47+
  - Reception unders
- Split:
  - WR underdog, total 47+:
    - Over ROI ≈ -23.6%
    - Under ROI ≈ +8.4%
    - Sample ≈ 431
  - WR favorite, total 47+:
    - Over ROI ≈ -13.3%
    - Under ROI ≈ +1.6%
    - Sample ≈ 443
- Interpretation:
  - The signal appears mostly concentrated in underdog WRs in high-total games.
  - Public narrative is likely: trailing script + shootout = more WR catches.
  - Books appear to tax that assumption heavily.

### WR underdog + high-total + line bucket
- The signal is not uniform by line:
  - WR underdog, total 47+, line 3.5:
    - Under ROI ≈ +27.7%
    - Sample ≈ 81
  - WR underdog, total 47+, line 4.5:
    - Under ROI ≈ +6.5%
    - Sample ≈ 78
  - WR underdog, total 47+, line 5.5:
    - Under ROI ≈ -3.5%
    - Sample ≈ 81
  - WR underdog, total 47+, line 6.5:
    - Under ROI ≈ +5.8%
    - Sample ≈ 55
  - WR underdog, total 47+, line 7+:
    - Under ROI ≈ +9.7%
    - Sample ≈ 79
- Interpretation:
  - Possible WR2/WR3 narrative trap at 3.5–4.5.
  - Books may be sharper on true WR1 reception lines around 5.5.
  - Higher star-WR lines can still show under value, but samples get thin.

### Juice-specific note
- Receptions must always be evaluated with side-specific juice.
- Lines are rarely priced symmetrically.
- A 3.5 reception line at Over +125 / Under -160 is a different bet from -110/-110.
- Any edge must survive the actual over/under prices, not just hit-rate assumptions.
- The WR underdog + high-total signal partially survived juice splits, but sample sizes become thin after slicing.

## Current modeling direction: receptions Monte Carlo

### V1 approach
- Use fantasy/ensemble projected receptions as the mean input.
- Use a Negative Binomial simulation rather than normal distribution or plain Poisson.
- Receptions are discrete and overdispersed:
  - Poisson assumes variance = mean.
  - NFL receptions have variance > mean due to game script, role volatility, injuries, target distribution, and play volume.
- Simulate integer reception outcomes.
- Compare:
  - `P(over)`
  - `P(under)`
  - fair odds
  - market odds
  - EV over
  - EV under

### V1 inputs
- Projection file with:
  - player
  - projected receptions
  - position if available
- Current market file with:
  - player
  - line
  - over_price
  - under_price
  - position if available
- Historical analysis file:
  - `data/analysis/receptions_market_analysis_rows.csv`

### V1 output
- `data/analysis/receptions_model_bets.csv`
- Important output columns:
  - player
  - position
  - line
  - projection
  - projection_minus_line
  - over_price
  - under_price
  - p_over
  - p_under
  - fair_over_price
  - fair_under_price
  - ev_over
  - ev_under
  - recommended_side
  - recommended_prob
  - recommended_ev_percent
  - recommendation

## Important implementation notes
- `analyze_market.py` should remain the market-analysis script.
- Monte Carlo scripts should not become historical-market-analysis scripts.
- Historical backfill should capture game context once and reuse it downstream.
- Player team context is best derived after joining PFF actuals because PFF supplies team/position.
- PFF team abbreviations are nonstandard:
  - ARZ, BLT, CLV, HST, LA, etc.
- Use abbreviation mapping before comparing PFF team to full `home_team` / `away_team`.

## Open questions / next work
- Identify actual current projections CSV path for receptions.
- Identify or create current FanDuel receptions market CSV.
- Run `build_receptions_projection_engine.py` with real files.
- Backtest the receptions Monte Carlo engine against 2023–2025.
- Add contextual calibration only after V1 works:
  - WR + underdog + total 47+
  - line bucket interactions
  - juice bucket interactions
- Extend generalized market workflow to:
  - receiving yards
  - rushing yards
  - alt-line pricing
  - line shopping
- Eventually standardize market config so passing yards, receptions, receiving yards, and rushing yards share as much infrastructure as possible.
