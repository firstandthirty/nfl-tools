# Receptions Holdout Autopsy

Input: `data\analysis\backtests\receptions_backtest_rows.csv`

## Split

Only one season is present, so a true prior-season to latest-season holdout is unavailable. Using chronological fallback: discovery `2024 weeks <= 13`, validation `2024 weeks 14-17`.

| sample | method | label | seasons | weeks | bets | wins | losses | pushes | win_rate | profit_units | roi | avg_line | avg_projection | avg_projection_minus_line | avg_recommended_probability | avg_recommended_ev_percent | avg_bet_odds | avg_raw_edge | avg_projection_edge | avg_absolute_projection_edge |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| discovery | single_season_late_week_holdout | 2024 weeks <= 13 | 2024 | 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13 | 480 | 220 | 260 | 0 | 45.83% | -71.88 | -14.97% | 3.33 | 3.47 | 0.15 | 0.57 | 5.56 | 1.89 | 0.15 | 0.15 | 0.38 |
| validation | single_season_late_week_holdout | 2024 weeks 14-17 | 2024 | 14, 15, 16, 17 | 128 | 58 | 70 | 0 | 45.31% | -22.24 | -17.38% | 3.59 | 3.72 | 0.13 | 0.57 | 5.79 | 1.87 | 0.13 | 0.13 | 0.43 |

## Season Distribution

| season | bets | wins | losses | pushes | win_rate | profit_units | roi | avg_line | avg_projection | avg_projection_minus_line | avg_recommended_probability | avg_recommended_ev_percent | avg_bet_odds | avg_raw_edge | avg_projection_edge | avg_absolute_projection_edge | side_under_bets | side_over_bets | line_0.5_bets | line_1.5_bets | line_2.5_bets | line_3.5_bets | line_4.5_bets | line_5.5_bets | line_6.5_bets | line_7.5_bets | recommended_probability_mean | recommended_probability_std | recommended_probability_min | recommended_probability_10% | recommended_probability_25% | recommended_probability_50% | recommended_probability_75% | recommended_probability_90% | recommended_probability_max | absolute_projection_edge_mean | absolute_projection_edge_std | absolute_projection_edge_min | absolute_projection_edge_10% | absolute_projection_edge_25% | absolute_projection_edge_50% | absolute_projection_edge_75% | absolute_projection_edge_90% | absolute_projection_edge_max |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024 | 608 | 278 | 330 | 0 | 45.72% | -94.12 | -15.48% | 3.38 | 3.52 | 0.14 | 0.57 | 5.61 | 1.89 | 0.14 | 0.14 | 0.39 | 358 | 250 | 1 | 79 | 218 | 122 | 101 | 57 | 28 | 2 | 0.57 | 0.07 | 0.37 | 0.47 | 0.51 | 0.57 | 0.63 | 0.67 | 0.77 | 0.39 | 0.26 | 0.00 | 0.07 | 0.18 | 0.35 | 0.59 | 0.77 | 1.22 |

## Probability Source Trace

`recommended_prob` is produced in `scripts/03_modeling/build_receptions_projection_engine.py` as the simulated hit probability for the EV-favored side (`p_over` or `p_under`) from negative-binomial simulations. `recommended_ev_percent` is calculated as decimal EV multiplied by 100. This autopsy documents the formula but does not edit it.

## Probability Audit

| sample | bets | mean_recommended_probability | actual_win_rate | calibration_error | brier_score | expected_calibration_error | pearson_corr_probability_outcome | spearman_corr_probability_outcome | auc_probability | mean_raw_implied_probability | mean_no_vig_implied_probability | mean_probability_edge_vs_raw_market | mean_probability_edge_vs_no_vig_market | probability_bottom_roi | probability_top_roi | probability_roi_lift | probability_bottom_hit_rate | probability_top_hit_rate | absolute_edge_bottom_roi | absolute_edge_top_roi | absolute_edge_roi_lift | absolute_edge_bottom_hit_rate | absolute_edge_top_hit_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| discovery | 480 | 0.57 | 45.83% | 10.92% | 0.26 | 0.11 | 0.14 | 0.14 | 0.58 | 0.54 | 0.50 | 0.03 | 0.06 | -0.22 | -0.06 | 0.16 | 0.35 | 0.58 | -0.25 | -0.14 | 0.11 | 0.38 | 0.51 |
| validation | 128 | 0.57 | 45.31% | 12.10% | 0.26 | 0.13 | 0.17 | 0.16 | 0.59 | 0.54 | 0.51 | 0.03 | 0.06 | -0.07 | -0.10 | -0.03 | 0.44 | 0.56 | -0.30 | -0.26 | 0.05 | 0.36 | 0.44 |

## Current 0.35 Hypothesis

| sample | table | rule | bets | wins | losses | pushes | win_rate | profit_units | roi | avg_line | avg_projection | avg_projection_minus_line | avg_recommended_probability | avg_recommended_ev_percent | avg_bet_odds | avg_raw_edge | avg_projection_edge | avg_absolute_projection_edge | side | line_bucket | season |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| discovery | overall | absolute_projection_edge >= 0.35 | 235 | 122 | 113 | 0 | 51.91% | -20.13 | -8.57% | 3.33 | 3.58 | 0.26 | 0.60 | 5.81 | 1.80 | 0.26 | 0.26 | 0.60 |  |  |  |
| validation | overall | absolute_projection_edge >= 0.35 | 67 | 33 | 34 | 0 | 49.25% | -9.18 | -13.70% | 3.44 | 3.66 | 0.22 | 0.61 | 6.04 | 1.78 | 0.22 | 0.22 | 0.63 |  |  |  |

The `absolute_projection_edge >= 0.35` subset had discovery ROI -8.57% and validation ROI -13.70%.

### Rule by Side/Line/Season

| sample | table | rule | bets | wins | losses | pushes | win_rate | profit_units | roi | avg_line | avg_projection | avg_projection_minus_line | avg_recommended_probability | avg_recommended_ev_percent | avg_bet_odds | avg_raw_edge | avg_projection_edge | avg_absolute_projection_edge | side | line_bucket | season |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| discovery | side |  | 120 | 56 | 64 | 0 | 46.67% | -21.68 | -18.07% |  |  |  | 0.60 |  | 1.77 |  |  | 0.68 | over |  |  |
| discovery | side |  | 115 | 66 | 49 | 0 | 57.39% | 1.55 | 1.35% |  |  |  | 0.60 |  | 1.82 |  |  | 0.52 | under |  |  |
| discovery | line_bucket |  | 29 | 19 | 10 | 0 | 65.52% | 4.12 | 14.21% |  |  |  | 0.61 |  | 1.79 |  |  | 0.67 |  | 1.5 |  |
| discovery | line_bucket |  | 87 | 42 | 45 | 0 | 48.28% | -10.83 | -12.45% |  |  |  | 0.59 |  | 1.83 |  |  | 0.57 |  | 2.5 |  |
| discovery | line_bucket |  | 54 | 27 | 27 | 0 | 50.00% | -7.23 | -13.39% |  |  |  | 0.60 |  | 1.76 |  |  | 0.61 |  | 3.5 |  |
| discovery | line_bucket |  | 36 | 15 | 21 | 0 | 41.67% | -10.10 | -28.06% |  |  |  | 0.59 |  | 1.81 |  |  | 0.62 |  | 4.5 |  |
| discovery | line_bucket |  | 13 | 9 | 4 | 0 | 69.23% | 2.38 | 18.31% |  |  |  | 0.60 |  | 1.78 |  |  | 0.61 |  | 5.5 |  |
| discovery | line_bucket |  | 15 | 10 | 5 | 0 | 66.67% | 2.53 | 16.87% |  |  |  | 0.61 |  | 1.74 |  |  | 0.60 |  | 6.5+ |  |
| discovery | line_bucket |  | 1 | 0 | 1 | 0 | 0.00% | -1.00 | -100.00% |  |  |  | 0.43 |  | 2.50 |  |  | 0.71 |  | <1.5 |  |
| discovery | season |  | 235 | 122 | 113 | 0 | 51.91% | -20.13 | -8.57% |  |  |  | 0.60 |  | 1.80 |  |  | 0.60 |  |  | 2024.00 |
| validation | side |  | 33 | 15 | 18 | 0 | 45.45% | -7.01 | -21.24% |  |  |  | 0.61 |  | 1.77 |  |  | 0.71 | over |  |  |
| validation | side |  | 34 | 18 | 16 | 0 | 52.94% | -2.17 | -6.38% |  |  |  | 0.61 |  | 1.79 |  |  | 0.56 | under |  |  |
| validation | line_bucket |  | 9 | 2 | 7 | 0 | 22.22% | -5.87 | -65.22% |  |  |  | 0.60 |  | 1.81 |  |  | 0.80 |  | 1.5 |  |
| validation | line_bucket |  | 24 | 12 | 12 | 0 | 50.00% | -3.69 | -15.38% |  |  |  | 0.62 |  | 1.75 |  |  | 0.60 |  | 2.5 |  |
| validation | line_bucket |  | 13 | 8 | 5 | 0 | 61.54% | 1.72 | 13.23% |  |  |  | 0.59 |  | 1.79 |  |  | 0.59 |  | 3.5 |  |
| validation | line_bucket |  | 8 | 5 | 3 | 0 | 62.50% | 0.79 | 9.87% |  |  |  | 0.59 |  | 1.80 |  |  | 0.59 |  | 4.5 |  |
| validation | line_bucket |  | 10 | 4 | 6 | 0 | 40.00% | -2.50 | -25.00% |  |  |  | 0.59 |  | 1.82 |  |  | 0.62 |  | 5.5 |  |
| validation | line_bucket |  | 3 | 2 | 1 | 0 | 66.67% | 0.37 | 12.33% |  |  |  | 0.63 |  | 1.68 |  |  | 0.74 |  | 6.5+ |  |
| validation | season |  | 67 | 33 | 34 | 0 | 49.25% | -9.18 | -13.70% |  |  |  | 0.61 |  | 1.78 |  |  | 0.63 |  |  | 2024.00 |

## Threshold Stability

| signal | rule | threshold | discovery_bets | discovery_roi | discovery_profit_units | validation_bets | validation_roi | validation_profit_units | discovery_retention_pct | validation_retention_pct | roi_direction_agrees | hit_rate_direction_agrees | evidence_class |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| absolute_projection_edge | absolute_projection_edge >= 0.25 | 0.25 | 304 | -0.05 | -16.67 | 89 | -0.14 | -12.14 | 0.63 | 0.70 | True | True | weak holdout-consistent loss reduction |
| absolute_projection_edge | absolute_projection_edge >= 0.35 | 0.35 | 235 | -0.09 | -20.13 | 67 | -0.14 | -9.18 | 0.49 | 0.52 | True | True | weak holdout-consistent loss reduction |
| absolute_projection_edge | absolute_projection_edge >= 0.5 | 0.50 | 147 | -0.12 | -17.43 | 49 | -0.28 | -13.73 | 0.31 | 0.38 | False | False | does not generalize |
| absolute_projection_edge | absolute_projection_edge >= 0.75 | 0.75 | 53 | -0.08 | -4.44 | 16 | -0.00 | -0.04 | 0.11 | 0.12 | True | True | insufficient sample |
| absolute_projection_edge | absolute_projection_edge >= 1 | 1.00 | 7 | 0.11 | 0.80 | 5 | 0.30 | 1.51 | 0.01 | 0.04 | True | True | insufficient sample |
| recommended_ev_percent_value | recommended_ev_percent_value >= 2 | 2.00 | 480 | -0.15 | -71.88 | 128 | -0.17 | -22.24 | 1.00 | 1.00 | True | True | weak exploratory signal |
| recommended_ev_percent_value | recommended_ev_percent_value >= 3 | 3.00 | 400 | -0.13 | -52.06 | 109 | -0.24 | -26.47 | 0.83 | 0.85 | False | False | does not generalize |
| recommended_ev_percent_value | recommended_ev_percent_value >= 5 | 5.00 | 259 | -0.09 | -24.52 | 78 | -0.23 | -17.98 | 0.54 | 0.61 | False | False | does not generalize |
| recommended_ev_percent_value | recommended_ev_percent_value >= 7.5 | 7.50 | 120 | -0.11 | -13.50 | 43 | -0.12 | -5.33 | 0.25 | 0.34 | True | True | weak holdout-consistent loss reduction |
| recommended_probability | recommended_probability >= 0.5 | 0.50 | 376 | -0.12 | -46.35 | 105 | -0.16 | -16.56 | 0.78 | 0.82 | True | True | weak holdout-consistent loss reduction |
| recommended_probability | recommended_probability >= 0.525 | 0.53 | 323 | -0.14 | -45.45 | 88 | -0.18 | -16.10 | 0.67 | 0.69 | False | True | weak exploratory signal |
| recommended_probability | recommended_probability >= 0.55 | 0.55 | 268 | -0.17 | -45.39 | 73 | -0.17 | -12.77 | 0.56 | 0.57 | True | True | weak exploratory signal |
| recommended_probability | recommended_probability >= 0.575 | 0.57 | 227 | -0.16 | -36.15 | 61 | -0.14 | -8.31 | 0.47 | 0.48 | False | True | weak exploratory signal |
| recommended_probability | recommended_probability >= 0.6 | 0.60 | 176 | -0.09 | -15.42 | 51 | -0.11 | -5.41 | 0.37 | 0.40 | True | True | weak holdout-consistent loss reduction |
| recommended_probability | recommended_probability >= 0.625 | 0.62 | 128 | -0.08 | -10.47 | 39 | -0.09 | -3.62 | 0.27 | 0.30 | True | True | weak holdout-consistent loss reduction |
| recommended_probability | recommended_probability >= 0.65 | 0.65 | 71 | -0.07 | -4.90 | 22 | -0.14 | -3.15 | 0.15 | 0.17 | True | True | insufficient sample |

## Discovery Calibration

| calibration_field | bucket | bets | actual_win_rate | roi | profit_units | avg_odds | avg_recommended_probability | avg_predicted_probability | calibration_error | absolute_calibration_error | overall_brier_score | overall_expected_calibration_error | overall_mean_predicted_probability | overall_actual_win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| recommended_probability | <45% | 19 | 42.11% | 1.16% | 0.22 | 2.46 | 0.42 | 42.47% | -0.36% | 0.36% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 45-50% | 85 | 31.76% | -30.29% | -25.75 | 2.20 | 0.48 | 47.75% | -15.98% | 15.98% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 50-52.5% | 53 | 47.17% | -1.70% | -0.90 | 2.07 | 0.51 | 51.12% | -3.95% | 3.95% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 52.5-55% | 55 | 50.91% | -0.11% | -0.06 | 1.96 | 0.54 | 53.91% | -3.00% | 3.00% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 55-57.5% | 41 | 41.46% | -22.54% | -9.24 | 1.87 | 0.56 | 56.23% | -14.76% | 14.76% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 57.5-60% | 51 | 33.33% | -40.65% | -20.73 | 1.79 | 0.59 | 58.66% | -25.33% | 25.33% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 60-62.5% | 48 | 52.08% | -10.31% | -4.95 | 1.72 | 0.61 | 61.26% | -9.18% | 9.18% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 62.5-65% | 57 | 54.39% | -9.77% | -5.57 | 1.66 | 0.64 | 63.74% | -9.35% | 9.35% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 65-70% | 58 | 58.62% | -6.66% | -3.86 | 1.59 | 0.67 | 67.29% | -8.67% | 8.67% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 70%+ | 13 | 61.54% | -8.00% | -1.04 | 1.50 | 0.71 | 71.27% | -9.73% | 9.73% | 0.26 | 0.11 | 0.57 | 0.46 |

## Validation Calibration

| calibration_field | bucket | bets | actual_win_rate | roi | profit_units | avg_odds | avg_recommended_probability | avg_predicted_probability | calibration_error | absolute_calibration_error | overall_brier_score | overall_expected_calibration_error | overall_mean_predicted_probability | overall_actual_win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| recommended_probability | <45% | 5 | 20.00% | -51.60% | -2.58 | 2.49 | 0.42 | 41.96% | -21.96% | 21.96% | 0.26 | 0.12 | 0.57 | 0.45 |
| recommended_probability | 45-50% | 18 | 38.89% | -17.22% | -3.10 | 2.17 | 0.48 | 48.19% | -9.30% | 9.30% | 0.26 | 0.12 | 0.57 | 0.45 |
| recommended_probability | 50-52.5% | 17 | 47.06% | -2.71% | -0.46 | 2.06 | 0.51 | 51.28% | -4.23% | 4.23% | 0.26 | 0.12 | 0.57 | 0.45 |
| recommended_probability | 52.5-55% | 15 | 40.00% | -22.20% | -3.33 | 1.97 | 0.54 | 53.97% | -13.97% | 13.97% | 0.26 | 0.12 | 0.57 | 0.45 |
| recommended_probability | 55-57.5% | 12 | 33.33% | -37.17% | -4.46 | 1.88 | 0.57 | 56.61% | -23.28% | 23.28% | 0.26 | 0.12 | 0.57 | 0.45 |
| recommended_probability | 57.5-60% | 10 | 40.00% | -29.00% | -2.90 | 1.81 | 0.58 | 58.46% | -18.46% | 18.46% | 0.26 | 0.12 | 0.57 | 0.45 |
| recommended_probability | 60-62.5% | 12 | 50.00% | -14.92% | -1.79 | 1.72 | 0.61 | 61.27% | -11.27% | 11.27% | 0.26 | 0.12 | 0.57 | 0.45 |
| recommended_probability | 62.5-65% | 17 | 58.82% | -2.76% | -0.47 | 1.66 | 0.64 | 63.86% | -5.04% | 5.04% | 0.26 | 0.12 | 0.57 | 0.45 |
| recommended_probability | 65-70% | 17 | 47.06% | -24.12% | -4.10 | 1.59 | 0.67 | 67.32% | -20.26% | 20.26% | 0.26 | 0.12 | 0.57 | 0.45 |
| recommended_probability | 70%+ | 5 | 80.00% | 19.00% | 0.95 | 1.50 | 0.72 | 72.16% | 7.84% | 7.84% | 0.26 | 0.12 | 0.57 | 0.45 |

## Discovery Interactions

| table | probability_bucket | bets | wins | losses | pushes | win_rate | profit_units | roi | avg_bet_odds | avg_recommended_probability | avg_absolute_projection_edge | ev_bucket | verified_edge_bucket | projection_minus_line_bucket | line_bucket | side |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| recommended_probability_bucket | 45-50% | 85 | 27 | 58 | 0 | 31.76% | -25.75 | -30.29% | 2.20 | 0.48 | 0.28 |  |  |  |  |  |
| recommended_probability_bucket | 50-52.5% | 53 | 25 | 28 | 0 | 47.17% | -0.90 | -1.70% | 2.07 | 0.51 | 0.26 |  |  |  |  |  |
| recommended_probability_bucket | 52.5-55% | 55 | 28 | 27 | 0 | 50.91% | -0.06 | -0.11% | 1.96 | 0.54 | 0.25 |  |  |  |  |  |
| recommended_probability_bucket | 55-57.5% | 41 | 17 | 24 | 0 | 41.46% | -9.24 | -22.54% | 1.87 | 0.56 | 0.27 |  |  |  |  |  |
| recommended_probability_bucket | 57.5-60% | 51 | 17 | 34 | 0 | 33.33% | -20.73 | -40.65% | 1.79 | 0.59 | 0.35 |  |  |  |  |  |
| recommended_probability_bucket | 60-62.5% | 48 | 25 | 23 | 0 | 52.08% | -4.95 | -10.31% | 1.72 | 0.61 | 0.47 |  |  |  |  |  |
| recommended_probability_bucket | 62.5-65% | 57 | 31 | 26 | 0 | 54.39% | -5.57 | -9.77% | 1.66 | 0.64 | 0.60 |  |  |  |  |  |
| recommended_probability_bucket | 65-70% | 58 | 34 | 24 | 0 | 58.62% | -3.86 | -6.66% | 1.59 | 0.67 | 0.62 |  |  |  |  |  |
| recommended_probability_bucket | 70%+ | 13 | 8 | 5 | 0 | 61.54% | -1.04 | -8.00% | 1.50 | 0.71 | 0.57 |  |  |  |  |  |
| recommended_probability_bucket | <45% | 19 | 8 | 11 | 0 | 42.11% | 0.22 | 1.16% | 2.46 | 0.42 | 0.17 |  |  |  |  |  |
| recommended_ev_percent_bucket |  | 221 | 93 | 128 | 0 | 42.08% | -47.36 | -21.43% | 1.91 | 0.55 | 0.35 | 2-5 |  |  |  |  |
| recommended_ev_percent_bucket |  | 259 | 127 | 132 | 0 | 49.03% | -24.52 | -9.47% | 1.88 | 0.58 | 0.40 | 5-10 |  |  |  |  |
| absolute_projection_edge_bucket |  | 333 | 144 | 189 | 0 | 43.24% | -54.45 | -16.35% | 1.96 | 0.55 | 0.24 |  | 0-0.5 |  |  |  |
| absolute_projection_edge_bucket |  | 140 | 71 | 69 | 0 | 50.71% | -18.23 | -13.02% | 1.74 | 0.61 | 0.69 |  | 0.5-1 |  |  |  |
| absolute_projection_edge_bucket |  | 7 | 5 | 2 | 0 | 71.43% | 0.80 | 11.43% | 1.57 | 0.68 | 1.09 |  | 1-1.5 |  |  |  |
| signed_projection_edge_bucket |  | 76 | 26 | 50 | 0 | 34.21% | -26.29 | -34.59% | 1.91 | 0.56 | 0.12 |  |  | -0.25-0 |  |  |
| signed_projection_edge_bucket |  | 56 | 35 | 21 | 0 | 62.50% | 2.08 | 3.71% | 1.66 | 0.64 | 0.38 |  |  | -0.5--0.25 |  |  |
| signed_projection_edge_bucket |  | 42 | 27 | 15 | 0 | 64.29% | 1.54 | 3.67% | 1.60 | 0.66 | 0.62 |  |  | -1--0.5 |  |  |
| signed_projection_edge_bucket |  | 103 | 35 | 68 | 0 | 33.98% | -31.92 | -30.99% | 2.06 | 0.51 | 0.13 |  |  | 0-0.25 |  |  |
| signed_projection_edge_bucket |  | 98 | 48 | 50 | 0 | 48.98% | 1.68 | 1.71% | 2.07 | 0.51 | 0.35 |  |  | 0.25-0.5 |  |  |
| signed_projection_edge_bucket |  | 98 | 44 | 54 | 0 | 44.90% | -19.77 | -20.17% | 1.80 | 0.59 | 0.72 |  |  | 0.5-1 |  |  |
| signed_projection_edge_bucket |  | 7 | 5 | 2 | 0 | 71.43% | 0.80 | 11.43% | 1.57 | 0.68 | 1.09 |  |  | 1+ |  |  |
| line_bucket |  | 67 | 33 | 34 | 0 | 49.25% | -7.41 | -11.06% | 1.86 | 0.59 | 0.39 |  |  |  | 1.5 |  |
| line_bucket |  | 172 | 76 | 96 | 0 | 44.19% | -28.24 | -16.42% | 1.89 | 0.57 | 0.37 |  |  |  | 2.5 |  |
| line_bucket |  | 98 | 46 | 52 | 0 | 46.94% | -12.67 | -12.93% | 1.90 | 0.56 | 0.40 |  |  |  | 3.5 |  |
| line_bucket |  | 82 | 36 | 46 | 0 | 43.90% | -15.40 | -18.78% | 1.90 | 0.56 | 0.37 |  |  |  | 4.5 |  |
| line_bucket |  | 38 | 15 | 23 | 0 | 39.47% | -10.62 | -27.95% | 1.93 | 0.55 | 0.34 |  |  |  | 5.5 |  |
| line_bucket |  | 22 | 14 | 8 | 0 | 63.64% | 3.46 | 15.73% | 1.83 | 0.58 | 0.45 |  |  |  | 6.5+ |  |
| line_bucket |  | 1 | 0 | 1 | 0 | 0.00% | -1.00 | -100.00% | 2.50 | 0.43 | 0.71 |  |  |  | <1.5 |  |
| side |  | 201 | 85 | 116 | 0 | 42.29% | -39.50 | -19.65% | 1.95 | 0.55 | 0.47 |  |  |  |  | over |
| side |  | 279 | 135 | 144 | 0 | 48.39% | -32.38 | -11.61% | 1.85 | 0.58 | 0.32 |  |  |  |  | under |
| side_x_line_bucket |  | 28 | 16 | 12 | 0 | 57.14% | 0.56 | 2.00% | 1.89 | 0.58 | 0.55 |  |  |  | 1.5 | over |
| side_x_line_bucket |  | 67 | 33 | 34 | 0 | 49.25% | -3.46 | -5.16% | 1.94 | 0.55 | 0.48 |  |  |  | 2.5 | over |
| side_x_line_bucket |  | 55 | 21 | 34 | 0 | 38.18% | -14.86 | -27.02% | 1.96 | 0.55 | 0.46 |  |  |  | 3.5 | over |
| side_x_line_bucket |  | 39 | 11 | 28 | 0 | 28.21% | -17.06 | -43.74% | 1.98 | 0.54 | 0.45 |  |  |  | 4.5 | over |
| side_x_line_bucket |  | 10 | 4 | 6 | 0 | 40.00% | -2.68 | -26.80% | 2.01 | 0.53 | 0.39 |  |  |  | 5.5 | over |
| side_x_line_bucket |  | 2 | 0 | 2 | 0 | 0.00% | -2.00 | -100.00% | 2.02 | 0.52 | 0.40 |  |  |  | 6.5+ | over |
| side_x_line_bucket |  | 39 | 17 | 22 | 0 | 43.59% | -7.97 | -20.44% | 1.85 | 0.59 | 0.28 |  |  |  | 1.5 | under |
| side_x_line_bucket |  | 105 | 43 | 62 | 0 | 40.95% | -24.78 | -23.60% | 1.86 | 0.58 | 0.30 |  |  |  | 2.5 | under |
| side_x_line_bucket |  | 43 | 25 | 18 | 0 | 58.14% | 2.19 | 5.09% | 1.81 | 0.59 | 0.33 |  |  |  | 3.5 | under |

## Validation Interactions

| table | probability_bucket | bets | wins | losses | pushes | win_rate | profit_units | roi | avg_bet_odds | avg_recommended_probability | avg_absolute_projection_edge | ev_bucket | verified_edge_bucket | projection_minus_line_bucket | line_bucket | side |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| recommended_probability_bucket | 45-50% | 18 | 7 | 11 | 0 | 38.89% | -3.10 | -17.22% | 2.17 | 0.48 | 0.25 |  |  |  |  |  |
| recommended_probability_bucket | 50-52.5% | 17 | 8 | 9 | 0 | 47.06% | -0.46 | -2.71% | 2.06 | 0.51 | 0.30 |  |  |  |  |  |
| recommended_probability_bucket | 52.5-55% | 15 | 6 | 9 | 0 | 40.00% | -3.33 | -22.20% | 1.97 | 0.54 | 0.28 |  |  |  |  |  |
| recommended_probability_bucket | 55-57.5% | 12 | 4 | 8 | 0 | 33.33% | -4.46 | -37.17% | 1.88 | 0.57 | 0.29 |  |  |  |  |  |
| recommended_probability_bucket | 57.5-60% | 10 | 4 | 6 | 0 | 40.00% | -2.90 | -29.00% | 1.81 | 0.58 | 0.39 |  |  |  |  |  |
| recommended_probability_bucket | 60-62.5% | 12 | 6 | 6 | 0 | 50.00% | -1.79 | -14.92% | 1.72 | 0.61 | 0.51 |  |  |  |  |  |
| recommended_probability_bucket | 62.5-65% | 17 | 10 | 7 | 0 | 58.82% | -0.47 | -2.76% | 1.66 | 0.64 | 0.55 |  |  |  |  |  |
| recommended_probability_bucket | 65-70% | 17 | 8 | 9 | 0 | 47.06% | -4.10 | -24.12% | 1.59 | 0.67 | 0.70 |  |  |  |  |  |
| recommended_probability_bucket | 70%+ | 5 | 4 | 1 | 0 | 80.00% | 0.95 | 19.00% | 1.50 | 0.72 | 0.72 |  |  |  |  |  |
| recommended_probability_bucket | <45% | 5 | 1 | 4 | 0 | 20.00% | -2.58 | -51.60% | 2.49 | 0.42 | 0.48 |  |  |  |  |  |
| recommended_ev_percent_bucket |  | 50 | 24 | 26 | 0 | 48.00% | -4.26 | -8.52% | 1.92 | 0.55 | 0.35 | 2-5 |  |  |  |  |
| recommended_ev_percent_bucket |  | 78 | 34 | 44 | 0 | 43.59% | -17.98 | -23.05% | 1.84 | 0.59 | 0.48 | 5-10 |  |  |  |  |
| absolute_projection_edge_bucket |  | 79 | 37 | 42 | 0 | 46.84% | -8.51 | -10.77% | 1.96 | 0.55 | 0.24 |  | 0-0.5 |  |  |  |
| absolute_projection_edge_bucket |  | 44 | 17 | 27 | 0 | 38.64% | -15.24 | -34.64% | 1.76 | 0.61 | 0.68 |  | 0.5-1 |  |  |  |
| absolute_projection_edge_bucket |  | 5 | 4 | 1 | 0 | 80.00% | 1.51 | 30.20% | 1.62 | 0.67 | 1.07 |  | 1-1.5 |  |  |  |
| signed_projection_edge_bucket |  | 20 | 9 | 11 | 0 | 45.00% | -3.70 | -18.50% | 1.89 | 0.57 | 0.14 |  |  | -0.25-0 |  |  |
| signed_projection_edge_bucket |  | 17 | 10 | 7 | 0 | 58.82% | -0.13 | -0.76% | 1.70 | 0.62 | 0.35 |  |  | -0.5--0.25 |  |  |
| signed_projection_edge_bucket |  | 16 | 8 | 8 | 0 | 50.00% | -3.26 | -20.38% | 1.60 | 0.67 | 0.64 |  |  | -1--0.5 |  |  |
| signed_projection_edge_bucket |  | 19 | 6 | 13 | 0 | 31.58% | -6.40 | -33.68% | 2.08 | 0.50 | 0.15 |  |  | 0-0.25 |  |  |
| signed_projection_edge_bucket |  | 24 | 12 | 12 | 0 | 50.00% | 0.72 | 3.00% | 2.08 | 0.51 | 0.34 |  |  | 0.25-0.5 |  |  |
| signed_projection_edge_bucket |  | 27 | 9 | 18 | 0 | 33.33% | -10.98 | -40.67% | 1.85 | 0.58 | 0.71 |  |  | 0.5-1 |  |  |
| signed_projection_edge_bucket |  | 5 | 4 | 1 | 0 | 80.00% | 1.51 | 30.20% | 1.62 | 0.67 | 1.07 |  |  | 1+ |  |  |
| line_bucket |  | 12 | 3 | 9 | 0 | 25.00% | -6.73 | -56.08% | 1.88 | 0.58 | 0.67 |  |  |  | 1.5 |  |
| line_bucket |  | 46 | 21 | 25 | 0 | 45.65% | -8.96 | -19.48% | 1.84 | 0.59 | 0.41 |  |  |  | 2.5 |  |
| line_bucket |  | 24 | 13 | 11 | 0 | 54.17% | 0.54 | 2.25% | 1.91 | 0.56 | 0.41 |  |  |  | 3.5 |  |
| line_bucket |  | 19 | 9 | 10 | 0 | 47.37% | -2.65 | -13.95% | 1.90 | 0.56 | 0.37 |  |  |  | 4.5 |  |
| line_bucket |  | 19 | 8 | 11 | 0 | 42.11% | -3.71 | -19.53% | 1.89 | 0.57 | 0.39 |  |  |  | 5.5 |  |
| line_bucket |  | 8 | 4 | 4 | 0 | 50.00% | -0.73 | -9.12% | 1.84 | 0.58 | 0.43 |  |  |  | 6.5+ |  |
| side |  | 49 | 20 | 29 | 0 | 40.82% | -12.61 | -25.73% | 1.90 | 0.57 | 0.54 |  |  |  |  | over |
| side |  | 79 | 38 | 41 | 0 | 48.10% | -9.63 | -12.19% | 1.86 | 0.58 | 0.36 |  |  |  |  | under |
| side_x_line_bucket |  | 6 | 2 | 4 | 0 | 33.33% | -2.87 | -47.83% | 1.60 | 0.67 | 0.81 |  |  |  | 1.5 | over |
| side_x_line_bucket |  | 19 | 6 | 13 | 0 | 31.58% | -7.80 | -41.05% | 1.97 | 0.55 | 0.48 |  |  |  | 2.5 | over |
| side_x_line_bucket |  | 14 | 8 | 6 | 0 | 57.14% | 0.64 | 4.57% | 1.93 | 0.55 | 0.47 |  |  |  | 3.5 | over |
| side_x_line_bucket |  | 5 | 2 | 3 | 0 | 40.00% | -1.30 | -26.00% | 1.86 | 0.58 | 0.65 |  |  |  | 4.5 | over |
| side_x_line_bucket |  | 5 | 2 | 3 | 0 | 40.00% | -1.28 | -25.60% | 1.95 | 0.55 | 0.48 |  |  |  | 5.5 | over |
| side_x_line_bucket |  | 6 | 1 | 5 | 0 | 16.67% | -3.86 | -64.33% | 2.16 | 0.49 | 0.52 |  |  |  | 1.5 | under |
| side_x_line_bucket |  | 27 | 15 | 12 | 0 | 55.56% | -1.16 | -4.30% | 1.76 | 0.62 | 0.35 |  |  |  | 2.5 | under |
| side_x_line_bucket |  | 10 | 5 | 5 | 0 | 50.00% | -0.10 | -1.00% | 1.89 | 0.57 | 0.33 |  |  |  | 3.5 | under |
| side_x_line_bucket |  | 14 | 7 | 7 | 0 | 50.00% | -1.35 | -9.64% | 1.91 | 0.55 | 0.27 |  |  |  | 4.5 | under |
| side_x_line_bucket |  | 14 | 6 | 8 | 0 | 42.86% | -2.43 | -17.36% | 1.87 | 0.57 | 0.35 |  |  |  | 5.5 | under |

## Direct Conclusion

Validation probability bucket hit-rate monotonicity is `not monotonic`, absolute-edge hit-rate monotonicity is `not monotonic`, validation AUC is 0.594, and validation Spearman correlation is 0.161.
Top-vs-bottom validation ROI lift is -3.28% for recommended probability and 4.51% for absolute projection edge.
Validation unders lost less than overs: under ROI -12.19% on 79 bets vs over ROI -25.73% on 49 bets.
Conclusion: probability has a weak ranking signal out of sample, but probabilities are badly overstated; absolute projection edge does not rank outcomes monotonically in validation. Receptions should be retained for further modeling only, not restricted to a production subset from this autopsy.
