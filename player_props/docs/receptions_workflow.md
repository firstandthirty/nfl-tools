1. Pull current FanDuel receptions lines

Create/current script should output something like:

data/processed/current_fanduel_receptions.csv

Needs:

player, line, over_price, under_price

Ideally also:

team, opponent, game_total, team_spread, is_favorite
2. Add fantasy projections

Projection file needs:

player, projected_receptions, position
3. Run the model
python scripts/04_analysis/build_receptions_projection_engine.py ^
  --projections data/processed/current_receptions_projections.csv ^
  --markets data/processed/current_fanduel_receptions.csv

Output:

data/analysis/receptions_model_bets.csv
4. Review candidates

Sort by:

recommended_ev_percent

But sanity check:

projection_minus_line
p_over / p_under
juice
position
line_bucket
game_total
is_favorite
5. Apply manual flags

Especially:

WR underdog + total 47+ + line 3.5/4.5

Don’t auto-bet it, but flag it.

6. Log results

Save weekly outputs:

data/analysis/archive/receptions_model_bets_week_01.csv

Then after games:

actual receptions
model probability
EV
result
ROI