# Receiving Yards Weekly Workflow

## 1. Pull current FanDuel receiving yards lines

Create/current script should output:

data/processed/current_fanduel_reception_yds.csv

Required columns:

player, line, over_price, under_price

Ideally also:

team, opponent, game_total, team_spread, is_favorite, position

Market key:

player_reception_yds

## 2. Add FantasyPros API projections

Projection source:

data/processed/fantasypros_weekly_projections_api.csv

Required columns:

player, player_clean/player_norm, season, week, position, fp_receiving_yds

Model projection column:

fp_receiving_yds

## 3. Run the model

python scripts/03_modeling/build_receiving_yds_projection_engine.py ^
  --projections data/processed/fantasypros_weekly_projections_api.csv ^
  --markets data/processed/current_fanduel_reception_yds.csv ^
  --output data/analysis/reception_yds_model_bets.csv ^
  --n-sims 500

Current tuned setting:

STD_INFLATION_FACTOR = 1.15

Output:

data/analysis/reception_yds_model_bets.csv

## 4. Review candidates

Sort by:

recommended_ev_percent

But sanity check:

projection_minus_line
p_over / p_under
juice
position
line_bucket
game_total
team_spread
is_favorite

## 5. Apply current V1 filters

Most promising V1 rule:

recommendation == over
recommended_ev_percent >= 2
recommended_ev_percent <= 10

Reason:

Backtest showed:
108 bets
56.5% hit rate
+7.8% ROI

Avoid:

very high EV plays above 10%

Reason:

10%+ EV buckets looked overconfident / poorly calibrated.

## 6. Manual sanity flags

Do not auto-bet solely from model output.

Flag/check:

injuries
depth chart role changes
rookies / new roles
weather
QB changes
target competition
snap share uncertainty
alt-line contamination
stale projections

Be extra skeptical of:

low-line backup WR overs
players with unclear route participation
extreme projection_minus_line
extreme EV

## 7. Log weekly outputs

Save weekly output:

data/analysis/archive/reception_yds_model_bets_week_01.csv

After games, log:

actual receiving yards
model probability
recommended side
EV
closing line
result
ROI
CLV

## 8. Current status

Receiving yards is promising but not production-ready.

Best current setup:

FantasyPros API projections
Normal simulation
historical variance by position + line bucket
STD_INFLATION_FACTOR = 1.15
