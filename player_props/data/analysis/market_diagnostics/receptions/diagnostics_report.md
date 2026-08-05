# Market Diagnostics: player_receptions

Input: `data\analysis\backtests\receptions_backtest_rows.csv`

## Validated baseline

- Bets: **608**
- Record: **278-330-0**
- Win rate: **45.72%**
- Profit: **-94.12 units**
- ROI: **-15.48%**
- Bootstrap 95% ROI interval: **-22.76% to -8.17%**

## Edge and bucket definitions

| field | source_column | output_column | interpreted_unit | bucket_boundaries | bucket_labels | verified |
| --- | --- | --- | --- | --- | --- | --- |
| line | line | line_bucket | receptions line | -inf, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, inf | <1.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5+ |  |
| projection_edge | projection_minus_line | projection_minus_line_bucket | receptions, signed projection-minus-line | -inf, -1, -0.5, -0.25, 0, 0.25, 0.5, 1, inf | <-1, -1--0.5, -0.5--0.25, -0.25-0, 0-0.25, 0.25-0.5, 0.5-1, 1+ |  |
| recommended_probability | recommended_prob | probability_bucket | decimal probability | -inf, 0.45, 0.5, 0.525, 0.55, 0.575, 0.6, 0.625, 0.65, 0.7, inf | <45%, 45-50%, 50-52.5%, 52.5-55%, 55-57.5%, 57.5-60%, 60-62.5%, 62.5-65%, 65-70%, 70%+ |  |
| recommended_ev_percent | recommended_ev_percent | ev_bucket | percentage points | -inf, 0, 2, 5, 10, 15, 20, inf | <0, 0-2, 2-5, 5-10, 10-15, 15-20, 20+ |  |
| absolute_projection_edge | edge_receptions | verified_edge_bucket | receptions, absolute projection-minus-line | 0, 0.5, 1, 1.5, 2, 3, 4, inf | 0-0.5, 0.5-1, 1-1.5, 1.5-2, 2-3, 3-4, 4+ |  |
| raw_edge_signed | edge |  | receptions, signed; equals projection_minus_line when present |  |  | True |
| projection_edge | projection_minus_line |  | receptions, signed projection-minus-line |  |  | True |
| absolute_projection_edge | edge_receptions |  | receptions, absolute projection-minus-line |  |  | True |

## Data quality

| check | value |
| --- | --- |
| input_rows | 608 |
| input_columns | 28 |
| graded_rows | 608 |
| ungraded_rows | 0 |
| duplicate_full_rows | 0 |
| column_actual | actual |
| column_ev_percent | recommended_ev_percent |
| column_line | line |
| column_market | market_key |
| column_odds | bet_odds |
| column_opponent | opponent |
| column_player | player |
| column_predicted_probability | recommended_prob |
| column_profit | profit_1u |
| column_projection | projection |
| column_season | season |
| column_side | recommended_side |
| column_team | team |
| column_week | week |
| missing_side | 0 |
| missing_line_value | 0 |
| missing_projection_value | 0 |
| missing_predicted_probability | 0 |
| missing_recommended_ev_percent_value | 0 |
| missing_profit_units | 0 |
| missing_won | 0 |
| missing_pushed | 0 |
| bucket_line | receptions line \| -inf, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, inf |
| bucket_projection_edge | receptions, signed projection-minus-line \| -inf, -1, -0.5, -0.25, 0, 0.25, 0.5, 1, inf |
| bucket_recommended_probability | decimal probability \| -inf, 0.45, 0.5, 0.525, 0.55, 0.575, 0.6, 0.625, 0.65, 0.7, inf |
| bucket_recommended_ev_percent | percentage points \| -inf, 0, 2, 5, 10, 15, 20, inf |
| bucket_absolute_projection_edge | receptions, absolute projection-minus-line \| 0, 0.5, 1, 1.5, 2, 3, 4, inf |

## Calibration: probability

| calibration_field | bucket | bets | actual_win_rate | roi | profit_units | avg_odds | avg_recommended_probability | avg_predicted_probability | calibration_error | absolute_calibration_error | overall_brier_score | overall_expected_calibration_error | overall_mean_predicted_probability | overall_actual_win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| recommended_probability | <45% | 24 | 37.50% | -9.83% | -2.36 | 2.47 | 0.42 | 42.36% | -4.86% | 4.86% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 45-50% | 103 | 33.01% | -28.01% | -28.85 | 2.19 | 0.48 | 47.82% | -14.81% | 14.81% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 50-52.5% | 70 | 47.14% | -1.94% | -1.36 | 2.07 | 0.51 | 51.16% | -4.01% | 4.01% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 52.5-55% | 70 | 48.57% | -4.84% | -3.39 | 1.96 | 0.54 | 53.92% | -5.35% | 5.35% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 55-57.5% | 53 | 39.62% | -25.85% | -13.70 | 1.88 | 0.56 | 56.31% | -16.69% | 16.69% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 57.5-60% | 61 | 34.43% | -38.74% | -23.63 | 1.79 | 0.59 | 58.63% | -24.20% | 24.20% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 60-62.5% | 60 | 51.67% | -11.23% | -6.74 | 1.72 | 0.61 | 61.26% | -9.60% | 9.60% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 62.5-65% | 74 | 55.41% | -8.16% | -6.04 | 1.66 | 0.64 | 63.76% | -8.36% | 8.36% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 65-70% | 75 | 56.00% | -10.61% | -7.96 | 1.59 | 0.67 | 67.30% | -11.30% | 11.30% | 0.26 | 0.11 | 0.57 | 0.46 |
| recommended_probability | 70%+ | 18 | 66.67% | -0.50% | -0.09 | 1.50 | 0.72 | 71.52% | -4.85% | 4.85% | 0.26 | 0.11 | 0.57 | 0.46 |

## Calibration: ev

| calibration_field | bucket | bets | actual_win_rate | roi | profit_units | avg_odds | avg_recommended_ev_percent |
| --- | --- | --- | --- | --- | --- | --- | --- |
| recommended_ev_percent | 2-5 | 271 | 43.17% | -19.05% | -51.62 | 1.91 | 3.43 |
| recommended_ev_percent | 5-10 | 337 | 47.77% | -12.61% | -42.50 | 1.87 | 7.35 |

## Calibration: projection_minus_line

| calibration_field | bucket | bets | actual_win_rate | roi | profit_units | avg_odds | avg_projection_minus_line |
| --- | --- | --- | --- | --- | --- | --- | --- |
| projection_minus_line | -1--0.5 | 58 | 60.34% | -2.97% | -1.72 | 1.60 | -0.63 |
| projection_minus_line | -0.5--0.25 | 73 | 61.64% | 2.67% | 1.95 | 1.67 | -0.37 |
| projection_minus_line | -0.25-0 | 96 | 36.46% | -31.24% | -29.99 | 1.90 | -0.12 |
| projection_minus_line | 0-0.25 | 122 | 33.61% | -31.41% | -38.32 | 2.06 | 0.13 |
| projection_minus_line | 0.25-0.5 | 122 | 49.18% | 1.97% | 2.40 | 2.07 | 0.35 |
| projection_minus_line | 0.5-1 | 125 | 42.40% | -24.60% | -30.75 | 1.82 | 0.72 |

## Calibration: verified_edge

| calibration_field | bucket | bets | actual_win_rate | roi | profit_units | avg_odds | avg_absolute_projection_edge |
| --- | --- | --- | --- | --- | --- | --- | --- |
| absolute_projection_edge | 0-0.5 | 412 | 43.93% | -15.28% | -62.96 | 1.96 | 0.24 |
| absolute_projection_edge | 0.5-1 | 184 | 47.83% | -18.19% | -33.47 | 1.75 | 0.69 |

## Strongest negative exploratory segments

| dimension_1 | value_1 | dimension_2 | value_2 | bets | wins | losses | pushes | win_rate | profit_units | roi | avg_line | avg_projection | avg_projection_minus_line | avg_recommended_probability | avg_recommended_ev_percent | avg_bet_odds | avg_raw_edge | avg_projection_edge | avg_absolute_projection_edge | roi_standard_error | roi_ci_95_low | roi_ci_95_high | roi_x_sqrt_n | conservative_score | ranking_note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| projection_minus_line_bucket | 0-0.25 | probability_bucket | 45-50% | 46 | 10 | 36 | 0 | 21.74% | -24.32 | -52.87% | 3.52 | 3.66 | 0.14 | 0.48 | 4.92 | 2.19 | 0.14 | 0.14 | 0.14 | 0.13 | -79.02% | -26.72% | -3.59 | -79.02% | exploratory |
| side | over | probability_bucket | 45-50% | 53 | 12 | 41 | 0 | 22.64% | -26.86 | -50.68% | 3.50 | 3.64 | 0.14 | 0.48 | 4.84 | 2.19 | 0.14 | 0.14 | 0.15 | 0.13 | -75.48% | -25.88% | -3.69 | -75.48% | exploratory |
| line_bucket | 5.5 | verified_edge_bucket | 0-0.5 | 41 | 12 | 29 | 0 | 29.27% | -17.62 | -42.98% | 5.50 | 5.50 | 0.00 | 0.53 | 4.92 | 1.98 | 0.00 | 0.00 | 0.22 | 0.14 | -70.53% | -15.42% | -2.75 | -70.53% | exploratory |
| side | over | projection_minus_line_bucket | 0-0.25 | 55 | 14 | 41 | 0 | 25.45% | -24.42 | -44.40% | 3.55 | 3.70 | 0.14 | 0.48 | 4.90 | 2.19 | 0.14 | 0.14 | 0.14 | 0.13 | -69.81% | -18.99% | -3.29 | -69.81% | exploratory |
| side | over | line_bucket | 4.5 | 44 | 13 | 31 | 0 | 29.55% | -18.36 | -41.73% | 4.50 | 4.96 | 0.46 | 0.54 | 5.52 | 1.97 | 0.46 | 0.46 | 0.47 | 0.14 | -68.82% | -14.64% | -2.77 | -68.82% | exploratory |
| line_bucket | 2.5 | projection_minus_line_bucket | -0.25-0 | 31 | 11 | 20 | 0 | 35.48% | -10.71 | -34.55% | 2.50 | 2.38 | -0.12 | 0.57 | 5.21 | 1.88 | -0.12 | -0.12 | 0.12 | 0.16 | -66.64% | -2.45% | -1.92 | -66.64% | exploratory |
| projection_minus_line_bucket | 0-0.25 | ev_bucket | 2-5 | 68 | 19 | 49 | 0 | 27.94% | -29.66 | -43.62% | 3.43 | 3.56 | 0.13 | 0.51 | 3.51 | 2.04 | 0.13 | 0.13 | 0.13 | 0.11 | -65.41% | -21.82% | -3.60 | -65.41% | exploratory |
| probability_bucket | 45-50% | ev_bucket | 5-10 | 38 | 12 | 26 | 0 | 31.58% | -11.38 | -29.95% | 3.16 | 3.42 | 0.26 | 0.48 | 6.95 | 2.24 | 0.26 | 0.26 | 0.26 | 0.17 | -63.19% | 3.29% | -1.85 | -63.19% | exploratory |
| projection_minus_line_bucket | 0-0.25 | probability_bucket | 50-52.5% | 31 | 11 | 20 | 0 | 35.48% | -8.06 | -26.00% | 3.82 | 4.01 | 0.19 | 0.51 | 5.49 | 2.06 | 0.19 | 0.19 | 0.19 | 0.18 | -61.72% | 9.72% | -1.45 | -61.72% | exploratory |
| side | under | probability_bucket | 57.5-60% | 39 | 15 | 24 | 0 | 38.46% | -12.21 | -31.31% | 4.01 | 3.85 | -0.16 | 0.59 | 4.99 | 1.79 | -0.16 | -0.16 | 0.19 | 0.14 | -58.94% | -3.67% | -1.96 | -58.94% | exploratory |
| probability_bucket | 57.5-60% | verified_edge_bucket | 0-0.5 | 39 | 15 | 24 | 0 | 38.46% | -12.21 | -31.31% | 4.01 | 3.85 | -0.16 | 0.59 | 4.99 | 1.79 | -0.16 | -0.16 | 0.19 | 0.14 | -58.94% | -3.67% | -1.96 | -58.94% | exploratory |
| projection_minus_line_bucket | -0.25-0 | ev_bucket | 2-5 | 47 | 17 | 30 | 0 | 36.17% | -15.09 | -32.11% | 3.65 | 3.53 | -0.12 | 0.55 | 3.42 | 1.92 | -0.12 | -0.12 | 0.12 | 0.13 | -58.44% | -5.77% | -2.20 | -58.44% | exploratory |

## Strongest positive exploratory segments

| dimension_1 | value_1 | dimension_2 | value_2 | bets | wins | losses | pushes | win_rate | profit_units | roi | avg_line | avg_projection | avg_projection_minus_line | avg_recommended_probability | avg_recommended_ev_percent | avg_bet_odds | avg_raw_edge | avg_projection_edge | avg_absolute_projection_edge | roi_standard_error | roi_ci_95_low | roi_ci_95_high | roi_x_sqrt_n | conservative_score | ranking_note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| projection_minus_line_bucket | 0.25-0.5 | probability_bucket | 50-52.5% | 37 | 22 | 15 | 0 | 59.46% | 8.70 | 23.51% | 2.96 | 3.28 | 0.32 | 0.51 | 6.31 | 2.08 | 0.32 | 0.32 | 0.32 | 0.17 | -9.83% | 56.85% | 1.43 | -9.83% | exploratory |
| probability_bucket | 50-52.5% | ev_bucket | 5-10 | 42 | 24 | 18 | 0 | 57.14% | 8.42 | 20.05% | 3.24 | 3.51 | 0.27 | 0.51 | 7.49 | 2.10 | 0.27 | 0.27 | 0.27 | 0.16 | -11.79% | 51.88% | 1.30 | -11.79% | exploratory |
| projection_minus_line_bucket | -0.5--0.25 | verified_edge_bucket | 0-0.5 | 72 | 45 | 27 | 0 | 62.50% | 2.95 | 4.10% | 3.65 | 3.28 | -0.37 | 0.64 | 6.21 | 1.67 | -0.37 | -0.37 | 0.37 | 0.10 | -14.73% | 22.92% | 0.35 | -14.73% | exploratory |
| side | under | projection_minus_line_bucket | -0.5--0.25 | 73 | 45 | 28 | 0 | 61.64% | 1.95 | 2.67% | 3.68 | 3.31 | -0.37 | 0.64 | 6.19 | 1.67 | -0.37 | -0.37 | 0.37 | 0.10 | -16.10% | 21.44% | 0.23 | -16.10% | exploratory |
| projection_minus_line_bucket | 0.25-0.5 | verified_edge_bucket | 0-0.5 | 122 | 60 | 62 | 0 | 49.18% | 2.40 | 1.97% | 3.19 | 3.54 | 0.35 | 0.51 | 5.46 | 2.07 | 0.35 | 0.35 | 0.35 | 0.09 | -16.57% | 20.50% | 0.22 | -16.57% | exploratory |
| projection_minus_line_bucket | 0.25-0.5 | ev_bucket | 5-10 | 62 | 32 | 30 | 0 | 51.61% | 5.62 | 9.06% | 2.98 | 3.33 | 0.35 | 0.51 | 7.54 | 2.11 | 0.35 | 0.35 | 0.35 | 0.14 | -17.51% | 35.64% | 0.71 | -17.51% | exploratory |
| line_bucket | 2.5 | projection_minus_line_bucket | 0.25-0.5 | 53 | 28 | 25 | 0 | 52.83% | 4.73 | 8.92% | 2.50 | 2.86 | 0.36 | 0.52 | 5.79 | 2.06 | 0.36 | 0.36 | 0.36 | 0.14 | -19.15% | 37.00% | 0.65 | -19.15% | exploratory |
| side | over | probability_bucket | 50-52.5% | 30 | 17 | 13 | 0 | 56.67% | 5.38 | 17.93% | 3.50 | 3.79 | 0.29 | 0.51 | 6.02 | 2.07 | 0.29 | 0.29 | 0.29 | 0.19 | -19.63% | 55.50% | 0.98 | -19.63% | exploratory |
| side | under | line_bucket | 3.5 | 53 | 30 | 23 | 0 | 56.60% | 2.09 | 3.94% | 3.50 | 3.33 | -0.17 | 0.59 | 5.51 | 1.83 | -0.17 | -0.17 | 0.33 | 0.13 | -21.19% | 29.08% | 0.29 | -21.19% | exploratory |
| ev_bucket | 5-10 | verified_edge_bucket | 0-0.5 | 216 | 102 | 114 | 0 | 47.22% | -19.33 | -8.95% | 3.22 | 3.24 | 0.02 | 0.56 | 7.33 | 1.95 | 0.02 | 0.02 | 0.25 | 0.07 | -21.99% | 4.10% | -1.32 | -21.99% | exploratory |
| side | over | projection_minus_line_bucket | 0.25-0.5 | 61 | 31 | 30 | 0 | 50.82% | 1.97 | 3.23% | 3.14 | 3.50 | 0.36 | 0.53 | 5.96 | 2.01 | 0.36 | 0.36 | 0.36 | 0.13 | -22.51% | 28.97% | 0.25 | -22.51% | exploratory |
| probability_bucket | 62.5-65% | verified_edge_bucket | 0.5-1 | 48 | 29 | 19 | 0 | 60.42% | 0.18 | 0.37% | 4.06 | 4.24 | 0.17 | 0.64 | 5.89 | 1.66 | 0.17 | 0.17 | 0.74 | 0.12 | -22.87% | 23.62% | 0.03 | -22.87% | exploratory |

## Candidate exclusions

| rule_removed | rule_dimensions | removed_bets | removed_roi | removed_profit_units | remaining_bets | remaining_roi | remaining_profit_units | roi_lift | profit_change_units | pct_bets_retained | baseline_roi | baseline_bets | multiple_testing_note | evidence_class |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| absolute_projection_edge < 0.35 | 1 | 303 | -20.96% | -63.52 | 305 | -10.03% | -30.60 | 5.45% | 63.52 | 50.16% | -0.15 | 608 | exploratory; rule family comparison index 49 | hypothesis worth holdout testing |
| absolute_projection_edge < 0.18 | 1 | 149 | -28.70% | -42.76 | 459 | -11.19% | -51.36 | 4.29% | 42.76 | 75.49% | -0.15 | 608 | exploratory; rule family comparison index 47 | hypothesis worth holdout testing |
| projection_minus_line_bucket = 0-0.25 | 1 | 122 | -31.41% | -38.32 | 486 | -11.48% | -55.80 | 4.00% | 38.32 | 79.93% | -0.15 | 608 | exploratory; rule family comparison index 16 | hypothesis worth holdout testing |
| projection_minus_line_bucket = 0-0.25 AND verified_edge_bucket = 0-0.5 | 2 | 122 | -31.41% | -38.32 | 486 | -11.48% | -55.80 | 4.00% | 38.32 | 79.93% | -0.15 | 608 | exploratory; rule family comparison index 277 | hypothesis worth holdout testing |
| side = over | 1 | 250 | -20.84% | -52.11 | 358 | -11.73% | -42.01 | 3.75% | 52.11 | 58.88% | -0.15 | 608 | exploratory; rule family comparison index 2 | hypothesis worth holdout testing |
| projection_minus_line_bucket = 0-0.25 AND ev_bucket = 2-5 | 2 | 68 | -43.62% | -29.66 | 540 | -11.94% | -64.46 | 3.54% | 29.66 | 88.82% | -0.15 | 608 | exploratory; rule family comparison index 267 | hypothesis worth holdout testing |
| side = over AND ev_bucket = 2-5 | 2 | 120 | -29.26% | -35.11 | 488 | -12.09% | -59.01 | 3.39% | 35.11 | 80.26% | -0.15 | 608 | exploratory; rule family comparison index 78 | hypothesis worth holdout testing |
| side = over AND probability_bucket = 45-50% | 2 | 53 | -50.68% | -26.86 | 555 | -12.12% | -67.26 | 3.36% | 26.86 | 91.28% | -0.15 | 608 | exploratory; rule family comparison index 67 | hypothesis worth holdout testing |
| ev_bucket = 2-5 AND verified_edge_bucket = 0-0.5 | 2 | 196 | -22.26% | -43.63 | 412 | -12.25% | -50.49 | 3.23% | 43.63 | 67.76% | -0.15 | 608 | exploratory; rule family comparison index 326 | hypothesis worth holdout testing |
| projection_minus_line_bucket = -0.25-0 | 1 | 96 | -31.24% | -29.99 | 512 | -12.53% | -64.13 | 2.95% | 29.99 | 84.21% | -0.15 | 608 | exploratory; rule family comparison index 14 | hypothesis worth holdout testing |
| projection_minus_line_bucket = -0.25-0 AND verified_edge_bucket = 0-0.5 | 2 | 96 | -31.24% | -29.99 | 512 | -12.53% | -64.13 | 2.95% | 29.99 | 84.21% | -0.15 | 608 | exploratory; rule family comparison index 275 | hypothesis worth holdout testing |
| side = over AND projection_minus_line_bucket = 0-0.25 | 2 | 55 | -44.40% | -24.42 | 553 | -12.60% | -69.70 | 2.88% | 24.42 | 90.95% | -0.15 | 608 | exploratory; rule family comparison index 52 | hypothesis worth holdout testing |
| ev_bucket = 2-5 | 1 | 271 | -19.05% | -51.62 | 337 | -12.61% | -42.50 | 2.87% | 51.62 | 55.43% | -0.15 | 608 | exploratory; rule family comparison index 28 | hypothesis worth holdout testing |
| projection_edge < 0.17 | 1 | 303 | -18.27% | -55.35 | 305 | -12.71% | -38.77 | 2.77% | 55.35 | 50.16% | -0.15 | 608 | exploratory; rule family comparison index 35 | hypothesis worth holdout testing |
| probability_bucket = 45-50% AND verified_edge_bucket = 0-0.5 | 2 | 91 | -30.67% | -27.91 | 517 | -12.81% | -66.21 | 2.67% | 27.91 | 85.03% | -0.15 | 608 | exploratory; rule family comparison index 307 | hypothesis worth holdout testing |
| probability_bucket = 57.5-60% | 1 | 61 | -38.74% | -23.63 | 547 | -12.89% | -70.49 | 2.59% | 23.63 | 89.97% | -0.15 | 608 | exploratory; rule family comparison index 18 | hypothesis worth holdout testing |
| probability_bucket = 45-50% | 1 | 103 | -28.01% | -28.85 | 505 | -12.92% | -65.27 | 2.56% | 28.85 | 83.06% | -0.15 | 608 | exploratory; rule family comparison index 23 | hypothesis worth holdout testing |
| projection_minus_line_bucket = 0.5-1 AND ev_bucket = 5-10 | 2 | 67 | -35.97% | -24.10 | 541 | -12.94% | -70.02 | 2.54% | 24.10 | 88.98% | -0.15 | 608 | exploratory; rule family comparison index 258 | hypothesis worth holdout testing |
| side = under AND projection_minus_line_bucket = -0.25-0 | 2 | 79 | -31.33% | -24.75 | 529 | -13.11% | -69.37 | 2.37% | 24.75 | 87.01% | -0.15 | 608 | exploratory; rule family comparison index 49 | hypothesis worth holdout testing |
| projection_minus_line_bucket = 0.5-1 | 1 | 125 | -24.60% | -30.75 | 483 | -13.12% | -63.37 | 2.36% | 30.75 | 79.44% | -0.15 | 608 | exploratory; rule family comparison index 11 | hypothesis worth holdout testing |

## Warnings and holdout tests

- Candidate exclusions are exploratory and discovered from many comparisons; none are production-ready.
- Validate any hypothesis on a holdout season, rolling chronological split, or future settled sample before changing policy.
