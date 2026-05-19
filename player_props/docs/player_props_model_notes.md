# Player Props Model Notes

## Current scope
- NFL player props
- FanDuel primary book
- Passing yards v1 complete

## Key findings: passing yards
- Market line behaves like median
- Over hit rate ≈ 50.4%
- Avg actual - line ≈ +0.6 yards
- Clean residual sigma ≈ 68.5 yards
- Normal-ish residual shape
- Around +10 yards vs line starts becoming interesting
- +15 yards is stronger
- Need projection consensus, not one-source hero ball

## Current scripts
- backfill_fanduel_pass_yds_history.py
- analyze_pass_yds_market.py
- calibrate_pass_yds_distribution.py
- pass_yds_ev_thresholds.py
- pass_yds_projection_error_penalty.py
- build_projection_ensemble_engine.py

## Open questions
- receiving yards distribution
- rushing yards distribution
- receptions distribution
- alt-line pricing
- line shopping
- projection capture workflow