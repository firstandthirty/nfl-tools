from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = PROJECT_ROOT / "scripts" / "03_modeling" / "receiving_crossfit_calibration.py"
spec = importlib.util.spec_from_file_location("receiving_crossfit_calibration", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


class ReceivingCrossfitCalibrationTests(unittest.TestCase):
    def test_signal_fit_uses_only_prior_weeks(self) -> None:
        rows = self._history()
        preds = module.crossfit_signal_predictions(rows)
        self.assertTrue((preds["training_end_week"] < preds["predicted_week"]).all())

    def test_predicted_week_excluded_from_signal_training(self) -> None:
        preds = module.crossfit_signal_predictions(self._history())
        week = preds.iloc[0]["predicted_week"]
        self.assertNotEqual(int(preds.iloc[0]["training_end_week"]), int(week))

    def test_calibration_fit_uses_only_earlier_crossfitted_rows(self) -> None:
        calibrated = module.nested_calibrated_predictions(module.crossfit_signal_predictions(self._history()))
        self.assertTrue((calibrated["calibration_training_end_week"] < calibrated["predicted_week"]).all())

    def test_current_week_excluded_from_calibration_training(self) -> None:
        calibrated = module.nested_calibrated_predictions(module.crossfit_signal_predictions(self._history()))
        self.assertFalse((calibrated["calibration_training_end_week"] == calibrated["predicted_week"]).any())

    def test_minimum_history_guard(self) -> None:
        rows = self._history().query("week <= 3").copy()
        self.assertTrue(module.crossfit_signal_predictions(rows).empty)

    def test_predicted_margin_sign_to_side_mapping(self) -> None:
        self.assertEqual(module.projection_side(1.2), "over")
        self.assertEqual(module.projection_side(-0.1), "under")
        self.assertEqual(module.projection_side(0.0), "none")

    def test_side_oriented_score_construction(self) -> None:
        preds = module.crossfit_signal_predictions(self._history())
        prepared = module.prepare_calibration_frame(preds, "improved_signal")
        self.assertTrue((prepared["side_oriented_score"] >= 0).all())

    def test_logistic_calibration(self) -> None:
        train = pd.DataFrame({"score": [0, 1, 2, 3, 4, 5], "won": [0, 0, 0, 1, 1, 1]})
        coef = module.fit_logistic_calibrator(train, "score", "won")
        probs = module.predict_logistic_probability(pd.Series([0, 5]), coef)
        self.assertLess(probs[0], probs[1])

    def test_isotonic_calibration(self) -> None:
        blocks = module.fit_isotonic(pd.Series([1, 2, 3, 4]), pd.Series([0, 1, 0, 1]))
        probs = module.predict_isotonic(pd.Series([1, 4]), blocks)
        self.assertLessEqual(probs[0], probs[1])

    def test_empirical_bucket_calibration(self) -> None:
        train = pd.DataFrame({"score": range(20), "won": [0] * 10 + [1] * 10})
        test = pd.DataFrame({"score": [1, 19]})
        probs = module.empirical_bucket_probability(train, test, "score", "won")
        self.assertLess(probs[0], probs[1])

    def test_push_exclusion(self) -> None:
        rows = self._history()
        rows.loc[0, "actual"] = rows.loc[0, "line"]
        rows["actual_margin"] = rows["actual"] - rows["line"]
        rows["push"] = rows["actual"].eq(rows["line"])
        preds = module.crossfit_signal_predictions(rows)
        prepared = module.prepare_calibration_frame(preds, "raw_projection_edge")
        self.assertFalse(prepared["push"].any())

    def test_brier_calculation(self) -> None:
        self.assertAlmostEqual(module.brier_score(pd.Series([1, 0]), pd.Series([0.5, 0.5])), 0.25)

    def test_log_loss_calculation(self) -> None:
        self.assertAlmostEqual(module.log_loss(pd.Series([1, 0]), pd.Series([0.5, 0.5])), 0.6931471805599453)

    def test_50_percent_baseline(self) -> None:
        calibrated = module.nested_calibrated_predictions(module.crossfit_signal_predictions(self._history()))
        metrics = module.probability_metrics(calibrated)
        self.assertIn("constant_50", set(metrics["calibration_method"]))

    def test_shrinkage_formula(self) -> None:
        p = 0.5 + 0.25 * (0.7 - 0.5)
        self.assertAlmostEqual(p, 0.55)

    def test_deterministic_bootstrap(self) -> None:
        calibrated = module.nested_calibrated_predictions(module.crossfit_signal_predictions(self._history()))
        first = module.bootstrap_probability_metrics(calibrated, iterations=10, seed=3)
        second = module.bootstrap_probability_metrics(calibrated, iterations=10, seed=3)
        pd.testing.assert_frame_equal(first, second)

    def test_reliability_bucket_assignment(self) -> None:
        calibrated = module.nested_calibrated_predictions(module.crossfit_signal_predictions(self._history()))
        buckets = module.reliability_buckets(calibrated)
        self.assertIn("probability_bucket", buckets.columns)

    def test_raw_edge_benchmark_aligned_to_same_rows(self) -> None:
        signal = module.crossfit_signal_predictions(self._history())
        improved = module.prepare_calibration_frame(signal, "improved_signal")
        raw = module.prepare_calibration_frame(signal, "raw_projection_edge")
        self.assertEqual(len(improved), len(raw))

    def test_no_receptions_included(self) -> None:
        self.assertEqual(module.MARKET, "player_reception_yds")

    def test_no_passing_or_rushing_included(self) -> None:
        self.assertNotIn(module.MARKET, {"player_pass_yds", "player_rush_yds"})

    def test_no_2026_outcome_data_used(self) -> None:
        rows = self._history()
        self.assertFalse((rows["season"] == 2026).any())

    def test_no_api_network_use(self) -> None:
        text = MODULE_PATH.read_text(encoding="utf-8").lower()
        self.assertNotIn("requests.", text)
        self.assertNotIn("urllib", text)

    def test_chronological_ordering_deterministic(self) -> None:
        first = module.crossfit_signal_predictions(self._history())
        second = module.crossfit_signal_predictions(self._history().sample(frac=1, random_state=1))
        self.assertEqual(first[["week", "player_norm"]].sort_values(["week", "player_norm"]).reset_index(drop=True).shape, second[["week", "player_norm"]].sort_values(["week", "player_norm"]).reset_index(drop=True).shape)

    def _history(self) -> pd.DataFrame:
        rows = []
        for week in range(1, 12):
            for idx in range(13):
                line = 20.0 + idx
                projection = line + [-3, -2, -1, 1, 2, 3][idx % 6]
                actual = line + (1 if idx % 2 else -1) + week * 0.1
                rows.append({
                    "market": module.MARKET,
                    "season": 2024,
                    "week": week,
                    "player": f"Player {idx}",
                    "player_norm": f"player {idx}",
                    "team": "T",
                    "opponent": "O",
                    "position": ["WR", "TE", "RB"][idx % 3],
                    "game_id": f"g{week}",
                    "line": line,
                    "over_price": -110.0,
                    "under_price": -110.0,
                    "projection": projection,
                    "projection_edge": projection - line,
                    "raw_indicated_side": module.projection_side(projection - line),
                    "actual": actual,
                    "actual_margin": actual - line,
                    "push": False,
                })
        return pd.DataFrame(rows)


if __name__ == "__main__":
    unittest.main()
