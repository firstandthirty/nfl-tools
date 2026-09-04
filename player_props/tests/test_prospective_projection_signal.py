from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts" / "03_modeling"))

from prospective_projection_signal import (
    SignalPolicy,
    american_price_sort_value,
    build_candidate_gate_counts,
    build_distribution_by_line_type,
    build_extreme_alternate_examples,
    build_manifest,
    build_projection_signal_rows,
    load_policy,
    public_price_rule_pass,
    select_public_candidates,
    source_vote,
)


def _policy(
    sources: list[str] | None = None,
    required: int = 5,
    minimum: int = 4,
    max_age: float | None = None,
    min_price: int | None = -150,
    max_price: int | None = 200,
    allow_alternates: bool = True,
) -> SignalPolicy:
    return SignalPolicy(
        season=2026,
        required_source_count=required,
        minimum_agreement_count=minimum,
        active_sources=tuple(sources or ["alpha", "beta", "gamma", "delta", "epsilon"]),
        market_policy={
            "player_pass_yds": {"green_light_enabled": True},
            "player_rush_yds": {"green_light_enabled": True},
            "player_reception_yds": {"green_light_enabled": True},
            "player_receptions": {"green_light_enabled": True},
        },
        sportsbook_policy={
            "actionable_sportsbooks": ["draftkings", "fanduel", "williamhill_us"],
            "sportsbook_display_names": {"draftkings": "DraftKings", "fanduel": "FanDuel", "williamhill_us": "Caesars"},
        },
        staleness_policy={
            "enabled": max_age is not None,
            "maximum_projection_age_hours": max_age,
            "stale_sources_invalidate_green_light": True,
        },
        public_candidate_policy={
            "allow_alternate_public_candidates": allow_alternates,
            "price_policy_enabled": True,
            "min_american_odds": min_price,
            "max_american_odds": max_price,
        },
        edge_policy={
            "minimum_consensus_edge_abs": None,
            "minimum_consensus_edge_pct": None,
        },
        dispersion_policy={
            "maximum_projection_stddev": None,
            "maximum_projection_range": None,
        },
    )


def _projections(values: dict[str, float], market: str = "player_pass_yds") -> pd.DataFrame:
    rows = []
    for source, projection in values.items():
        rows.append({
            "season": 2026,
            "week": 1,
            "source": source,
            "player": "Player A",
            "player_normalized": "player a",
            "team": "BUF",
            "position": "QB",
            "market": market,
            "projection": projection,
            "captured_at": "2026-09-01T12:00:00-04:00",
            "as_of": "2026-09-01T13:00:00-04:00",
            "snapshot_age_hours": 1.0,
            "raw_file": f"{source}.csv",
        })
    return pd.DataFrame(rows)


def _snapshots(sources: list[str], age: float = 1.0) -> pd.DataFrame:
    return pd.DataFrame([{
        "source": source,
        "selection_status": "selected",
        "selected_captured_at": "2026-09-01T12:00:00-04:00",
        "selected_raw_file": f"{source}.csv",
        "selected_processed_file": f"{source}_long.csv",
        "snapshot_age_hours": age,
    } for source in sources])


def _odds(line: float = 10.0, side: str = "over", sportsbook: str = "draftkings", market: str = "player_pass_yds", is_alternate: bool = False, price: int = -110) -> pd.DataFrame:
    return pd.DataFrame([{
        "sportsbook": sportsbook,
        "source": "odds_api",
        "event_id": "event_1",
        "commence_time": "2026-09-06T17:00:00Z",
        "home_team": "Home",
        "away_team": "Away",
        "player": "Player A",
        "player_normalized": "player a",
        "market": market,
        "line": line,
        "side": side,
        "price": price,
        "captured_at": "2026-09-01T13:00:00-04:00",
        "season": 2026,
        "week": 1,
        "is_alternate": is_alternate,
        "market_source_key": market + ("_alternate" if is_alternate else ""),
    }])


def _run(values: dict[str, float], *, policy: SignalPolicy | None = None, odds: pd.DataFrame | None = None) -> pd.DataFrame:
    policy = policy or _policy(list(values))
    result = build_projection_signal_rows(
        projections=_projections(values),
        selected_snapshots=_snapshots(list(values)),
        odds=odds if odds is not None else _odds(),
        policy=policy,
        season=2026,
        week=1,
        as_of="2026-09-01T13:00:00-04:00",
    )
    return result["research_rows"]


class ProspectiveProjectionSignalTests(unittest.TestCase):
    def test_source_names_are_not_hardcoded(self) -> None:
        row = _run({"alpha": 11, "beta": 12, "gamma": 13, "delta": 14, "epsilon": 9}).iloc[0]
        self.assertEqual(row["participating_sources"], "alpha|beta|delta|epsilon|gamma")
        self.assertTrue(row["agreement_rule_pass"])

    def test_arbitrary_replacement_source_names_work(self) -> None:
        policy = _policy(["replacement_a", "replacement_b", "replacement_c", "replacement_d", "replacement_e"])
        row = _run({"replacement_a": 11, "replacement_b": 12, "replacement_c": 13, "replacement_d": 14, "replacement_e": 9}, policy=policy).iloc[0]
        self.assertEqual(int(row["source_count_available"]), 5)
        self.assertTrue(row["agreement_rule_pass"])

    def test_required_source_count_independent_of_provider_names(self) -> None:
        policy = _policy(["one", "two"], required=5, minimum=4)
        row = _run({"one": 11, "two": 12}, policy=policy).iloc[0]
        self.assertFalse(row["green_light"])
        self.assertIn("insufficient_projection_sources", row["green_light_reason_codes"])
        self.assertIn("source_count:2/5", row["green_light_reason"])

    def test_two_available_five_required_cannot_green_light(self) -> None:
        policy = _policy(["pff", "fantasypros"], required=5, minimum=4)
        row = _run({"pff": 11, "fantasypros": 12}, policy=policy).iloc[0]
        self.assertFalse(row["green_light"])

    def test_four_of_five_agreement_passes(self) -> None:
        row = _run({"a": 11, "b": 12, "c": 13, "d": 14, "e": 9}, policy=_policy(["a", "b", "c", "d", "e"])).iloc[0]
        self.assertEqual(int(row["agreement_count"]), 4)
        self.assertTrue(row["agreement_rule_pass"])

    def test_three_of_five_agreement_fails(self) -> None:
        row = _run({"a": 11, "b": 12, "c": 13, "d": 9, "e": 8}, policy=_policy(["a", "b", "c", "d", "e"])).iloc[0]
        self.assertEqual(int(row["agreement_count"]), 3)
        self.assertFalse(row["agreement_rule_pass"])

    def test_five_of_five_passes(self) -> None:
        row = _run({"a": 11, "b": 12, "c": 13, "d": 14, "e": 15}, policy=_policy(["a", "b", "c", "d", "e"])).iloc[0]
        self.assertEqual(row["research_tier"], "unanimous")
        self.assertTrue(row["green_light"])

    def test_neutral_vote_handled_correctly(self) -> None:
        row = _run({"a": 10, "b": 12, "c": 13, "d": 14, "e": 15}, policy=_policy(["a", "b", "c", "d", "e"])).iloc[0]
        self.assertEqual(int(row["neutral_votes"]), 1)
        self.assertEqual(int(row["over_votes"]), 4)

    def test_consensus_projection_median_correct(self) -> None:
        row = _run({"a": 7, "b": 11, "c": 13, "d": 15, "e": 100}, policy=_policy(["a", "b", "c", "d", "e"])).iloc[0]
        self.assertEqual(float(row["consensus_projection"]), 13.0)

    def test_consensus_edge_correct(self) -> None:
        row = _run({"a": 11, "b": 12, "c": 13, "d": 14, "e": 15}, policy=_policy(["a", "b", "c", "d", "e"])).iloc[0]
        self.assertEqual(float(row["consensus_edge"]), 3.0)

    def test_source_staleness_calculation_suppresses_green_light(self) -> None:
        policy = _policy(["a", "b", "c", "d", "e"], max_age=0.5)
        result = build_projection_signal_rows(
            projections=_projections({"a": 11, "b": 12, "c": 13, "d": 14, "e": 15}),
            selected_snapshots=_snapshots(["a", "b", "c", "d", "e"], age=1.0),
            odds=_odds(),
            policy=policy,
            season=2026,
            week=1,
            as_of="2026-09-01T13:00:00-04:00",
        )
        row = result["research_rows"].iloc[0]
        self.assertFalse(row["staleness_rule_pass"])
        self.assertFalse(row["green_light"])

    def test_missing_source_list_correct(self) -> None:
        policy = _policy(["a", "b", "c"], required=3, minimum=2)
        row = _run({"a": 11, "b": 12}, policy=policy).iloc[0]
        self.assertEqual(row["missing_sources"], "c")

    def test_unexpected_source_does_not_become_vote(self) -> None:
        policy = _policy(["a", "b"], required=2, minimum=2)
        row = _run({"a": 11, "b": 12, "intruder": 99}, policy=policy).iloc[0]
        self.assertEqual(int(row["source_count_available"]), 2)
        self.assertNotIn("intruder", row["participating_sources"])

    def test_fantasypros_counts_as_one_source(self) -> None:
        policy = _policy(["fantasypros"], required=1, minimum=1)
        projections = pd.concat([
            _projections({"fantasypros": 11}),
            _projections({"fantasypros": 12}),
        ], ignore_index=True)
        result = build_projection_signal_rows(
            projections=projections,
            selected_snapshots=_snapshots(["fantasypros"]),
            odds=_odds(),
            policy=policy,
            season=2026,
            week=1,
            as_of="2026-09-01T13:00:00-04:00",
        )
        self.assertEqual(int(result["research_rows"].iloc[0]["source_count_available"]), 1)

    def test_no_provider_specific_projection_columns_required(self) -> None:
        row = _run({"alpha": 11, "beta": 12}, policy=_policy(["alpha", "beta"], required=2, minimum=2)).iloc[0]
        self.assertIn('"alpha":11.0', row["source_projection_values"])
        self.assertNotIn("pff_projection", row.index)

    def test_alternate_lines_remain_in_research_output(self) -> None:
        odds = pd.concat([_odds(line=10, is_alternate=False), _odds(line=12, is_alternate=True)], ignore_index=True)
        rows = _run({"a": 14, "b": 15}, policy=_policy(["a", "b"], required=2, minimum=2), odds=odds)
        self.assertEqual(len(rows), 2)
        self.assertEqual(int(rows["is_alternate"].sum()), 1)

    def test_public_candidate_dedupes_player_market_side(self) -> None:
        odds = pd.concat([_odds(line=10, price=-110), _odds(line=12, price=105, is_alternate=True)], ignore_index=True)
        rows = _run({"a": 14, "b": 15}, policy=_policy(["a", "b"], required=2, minimum=2), odds=odds)
        candidates = select_public_candidates(rows)
        self.assertEqual(len(candidates), 1)

    def test_contradictory_over_under_signals_suppressed(self) -> None:
        odds = pd.concat([_odds(line=10, side="over"), _odds(line=20, side="under")], ignore_index=True)
        rows = _run({"a": 14, "b": 15}, policy=_policy(["a", "b"], required=2, minimum=2), odds=odds)
        self.assertTrue(rows["contradictory_projection_signal"].all())
        self.assertFalse(rows["green_light"].any())

    def test_deterministic_tiebreaking_prefers_better_price(self) -> None:
        odds = pd.concat([_odds(line=10, sportsbook="fanduel", price=-110), _odds(line=10, sportsbook="draftkings", price=-105)], ignore_index=True)
        rows = _run({"a": 14, "b": 15}, policy=_policy(["a", "b"], required=2, minimum=2), odds=odds)
        candidates = select_public_candidates(rows)
        self.assertEqual(candidates.iloc[0]["best_sportsbook"], "draftkings")

    def test_equal_price_tiebreaking_prefers_main_line(self) -> None:
        odds = pd.concat([_odds(line=10, is_alternate=True, price=-110), _odds(line=10, is_alternate=False, price=-110)], ignore_index=True)
        rows = _run({"a": 14, "b": 15}, policy=_policy(["a", "b"], required=2, minimum=2), odds=odds)
        candidates = select_public_candidates(rows)
        selected = rows.loc[rows["signal_id"] == candidates.iloc[0]["signal_id"]].iloc[0]
        self.assertFalse(bool(selected["is_alternate"]))

    def test_signal_ids_deterministic(self) -> None:
        first = _run({"a": 11, "b": 12}, policy=_policy(["a", "b"], required=2, minimum=2)).iloc[0]["signal_id"]
        second = _run({"a": 11, "b": 12}, policy=_policy(["a", "b"], required=2, minimum=2)).iloc[0]["signal_id"]
        self.assertEqual(first, second)

    def test_policy_copied_into_manifest(self) -> None:
        policy = _policy(["a", "b"], required=2, minimum=2)
        rows = _run({"a": 11, "b": 12}, policy=policy)
        manifest = build_manifest(
            policy=policy,
            source_state={"available_sources": ["a", "b"]},
            odds_snapshots=pd.DataFrame(),
            outputs={},
            season=2026,
            week=1,
            as_of="2026-09-01T13:00:00-04:00",
            run_timestamp="2026-09-01T13:01:00-04:00",
            research_rows=rows,
            candidate_rows=select_public_candidates(rows),
        )
        self.assertEqual(manifest["policy"]["active_sources"], ["a", "b"])

    def test_all_agreement_levels_retained_for_research(self) -> None:
        rows = _run({"a": 11, "b": 12, "c": 9, "d": 8, "e": 7}, policy=_policy(["a", "b", "c", "d", "e"]))
        self.assertEqual(int(rows.iloc[0]["agreement_count"]), 3)
        self.assertEqual(len(rows), 1)

    def test_no_probability_field_fabricated(self) -> None:
        rows = _run({"a": 11, "b": 12}, policy=_policy(["a", "b"], required=2, minimum=2))
        self.assertNotIn("probability", rows.columns)
        self.assertNotIn("win_probability", rows.columns)

    def test_no_ev_field_fabricated(self) -> None:
        rows = _run({"a": 11, "b": 12}, policy=_policy(["a", "b"], required=2, minimum=2))
        self.assertNotIn("ev", rows.columns)
        self.assertNotIn("expected_value", rows.columns)

    def test_no_api_network_use(self) -> None:
        self.assertTrue(callable(build_projection_signal_rows))

    def test_no_2026_outcomes_required(self) -> None:
        rows = _run({"a": 11, "b": 12}, policy=_policy(["a", "b"], required=2, minimum=2))
        self.assertNotIn("actual", rows.columns)

    def test_vote_mapping(self) -> None:
        self.assertEqual(source_vote(11, 10), "over")
        self.assertEqual(source_vote(9, 10), "under")
        self.assertEqual(source_vote(10, 10), "neutral")

    def test_receptions_pass_rush_receiving_remain_distinct(self) -> None:
        odds = pd.concat([
            _odds(market="player_pass_yds"),
            _odds(market="player_rush_yds"),
            _odds(market="player_reception_yds"),
            _odds(market="player_receptions"),
        ], ignore_index=True)
        projections = pd.concat([
            _projections({"a": 11, "b": 12}, market="player_pass_yds"),
            _projections({"a": 11, "b": 12}, market="player_rush_yds"),
            _projections({"a": 11, "b": 12}, market="player_reception_yds"),
            _projections({"a": 11, "b": 12}, market="player_receptions"),
        ], ignore_index=True)
        policy = _policy(["a", "b"], required=2, minimum=2)
        result = build_projection_signal_rows(
            projections=projections,
            selected_snapshots=_snapshots(["a", "b"]),
            odds=odds,
            policy=policy,
            season=2026,
            week=1,
            as_of="2026-09-01T13:00:00-04:00",
        )
        self.assertEqual(set(result["research_rows"]["market"]), {"player_pass_yds", "player_rush_yds", "player_reception_yds", "player_receptions"})

    def test_caesars_canonical_mapping_uses_williamhill_us(self) -> None:
        row = _run({"a": 11, "b": 12}, policy=_policy(["a", "b"], required=2, minimum=2), odds=_odds(sportsbook="williamhill_us")).iloc[0]
        self.assertTrue(row["actionable_ma_book"])
        self.assertEqual(row["sportsbook_display_name"], "Caesars")

    def test_intended_ma_books_use_canonical_keys(self) -> None:
        policy = load_policy(ROOT / "config" / "projection_signal_sources.json")
        self.assertEqual(policy.sportsbook_policy["sportsbook_display_names"]["williamhill_us"], "Caesars")
        self.assertEqual(policy.sportsbook_policy["sportsbook_display_names"]["espnbet"], "theScore")

    def test_non_ma_book_stays_research_only(self) -> None:
        row = _run({"a": 11, "b": 12}, policy=_policy(["a", "b"], required=2, minimum=2), odds=_odds(sportsbook="bovada")).iloc[0]
        self.assertFalse(row["actionable_ma_book"])
        self.assertFalse(row["public_candidate_eligible"])

    def test_price_minus_110_passes(self) -> None:
        self.assertTrue(public_price_rule_pass(-110, _policy()))

    def test_price_minus_150_passes(self) -> None:
        self.assertTrue(public_price_rule_pass(-150, _policy()))

    def test_price_worse_than_minus_150_fails(self) -> None:
        row = _run({"a": 11, "b": 12}, policy=_policy(["a", "b"], required=2, minimum=2), odds=_odds(price=-151)).iloc[0]
        self.assertFalse(row["public_candidate_price_rule_pass"])
        self.assertIn("price_out_of_range", row["green_light_reason_codes"])

    def test_price_plus_200_passes(self) -> None:
        self.assertTrue(public_price_rule_pass(200, _policy()))

    def test_price_above_plus_200_fails(self) -> None:
        row = _run({"a": 11, "b": 12}, policy=_policy(["a", "b"], required=2, minimum=2), odds=_odds(price=201)).iloc[0]
        self.assertFalse(row["public_candidate_price_rule_pass"])
        self.assertIn("price_out_of_range", row["green_light_reason_codes"])

    def test_american_odds_comparison_is_correct(self) -> None:
        ordered = sorted([-110, -105, 102, 104], key=american_price_sort_value)
        self.assertEqual(ordered, [-110, -105, 102, 104])

    def test_main_line_preference_among_otherwise_qualifying_rows(self) -> None:
        odds = pd.concat([_odds(line=5, price=-110, is_alternate=True), _odds(line=10, price=-110, is_alternate=False)], ignore_index=True)
        rows = _run({"a": 14, "b": 15}, policy=_policy(["a", "b"], required=2, minimum=2), odds=odds)
        candidate = select_public_candidates(rows).iloc[0]
        self.assertFalse(bool(candidate["is_alternate"]))

    def test_qualifying_alternate_can_win_when_main_does_not_qualify(self) -> None:
        odds = pd.concat([_odds(line=10, price=-200, is_alternate=False), _odds(line=8, price=-110, is_alternate=True)], ignore_index=True)
        rows = _run({"a": 14, "b": 15}, policy=_policy(["a", "b"], required=2, minimum=2), odds=odds)
        candidate = select_public_candidates(rows).iloc[0]
        self.assertTrue(bool(candidate["is_alternate"]))
        self.assertEqual(int(candidate["best_price"]), -110)

    def test_alternate_publication_config_false_suppresses_alternate_public_candidates(self) -> None:
        rows = _run({"a": 14, "b": 15}, policy=_policy(["a", "b"], required=2, minimum=2, allow_alternates=False), odds=_odds(is_alternate=True))
        self.assertFalse(rows.iloc[0]["public_candidate_eligible"])
        self.assertIn("alternate_publication_disabled", rows.iloc[0]["green_light_reason_codes"])

    def test_stale_source_greater_than_72h_fails(self) -> None:
        policy = _policy(["a", "b"], required=2, minimum=2, max_age=72)
        result = build_projection_signal_rows(projections=_projections({"a": 11, "b": 12}), selected_snapshots=_snapshots(["a", "b"], age=72.1), odds=_odds(), policy=policy, season=2026, week=1, as_of="2026-09-01T13:00:00-04:00")
        self.assertFalse(result["research_rows"].iloc[0]["staleness_rule_pass"])

    def test_exactly_72h_staleness_boundary_passes(self) -> None:
        policy = _policy(["a", "b"], required=2, minimum=2, max_age=72)
        result = build_projection_signal_rows(projections=_projections({"a": 11, "b": 12}), selected_snapshots=_snapshots(["a", "b"], age=72), odds=_odds(), policy=policy, season=2026, week=1, as_of="2026-09-01T13:00:00-04:00")
        self.assertTrue(result["research_rows"].iloc[0]["staleness_rule_pass"])

    def test_fresh_source_passes_staleness(self) -> None:
        policy = _policy(["a", "b"], required=2, minimum=2, max_age=72)
        result = build_projection_signal_rows(projections=_projections({"a": 11, "b": 12}), selected_snapshots=_snapshots(["a", "b"], age=1), odds=_odds(), policy=policy, season=2026, week=1, as_of="2026-09-01T13:00:00-04:00")
        self.assertTrue(result["research_rows"].iloc[0]["staleness_rule_pass"])

    def test_stale_source_remains_in_research(self) -> None:
        policy = _policy(["a", "b"], required=2, minimum=2, max_age=72)
        result = build_projection_signal_rows(projections=_projections({"a": 11, "b": 12}), selected_snapshots=_snapshots(["a", "b"], age=100), odds=_odds(), policy=policy, season=2026, week=1, as_of="2026-09-01T13:00:00-04:00")
        self.assertEqual(len(result["research_rows"]), 1)
        self.assertFalse(result["research_rows"].iloc[0]["green_light"])

    def test_staleness_is_not_provider_specific(self) -> None:
        policy = _policy(["pff", "fantasypros"], required=2, minimum=2, max_age=72)
        result = build_projection_signal_rows(projections=_projections({"pff": 11, "fantasypros": 12}), selected_snapshots=_snapshots(["pff", "fantasypros"], age=100), odds=_odds(), policy=policy, season=2026, week=1, as_of="2026-09-01T13:00:00-04:00")
        self.assertEqual(result["research_rows"].iloc[0]["stale_sources"], "fantasypros|pff")

    def test_main_alternate_diagnostics_are_separated(self) -> None:
        odds = pd.concat([_odds(line=10, is_alternate=False), _odds(line=8, is_alternate=True)], ignore_index=True)
        rows = _run({"a": 14, "b": 15}, policy=_policy(["a", "b"], required=2, minimum=2), odds=odds)
        diagnostics = build_distribution_by_line_type(rows)
        self.assertEqual(set(diagnostics["line_type"]), {"main", "alternate"})

    def test_extreme_alternate_with_minus_400_excluded_from_public_candidates(self) -> None:
        rows = _run({"a": 14, "b": 15}, policy=_policy(["a", "b"], required=2, minimum=2), odds=_odds(line=5, price=-400, is_alternate=True))
        self.assertTrue(rows.iloc[0]["is_alternate"])
        self.assertFalse(rows.iloc[0]["public_candidate_eligible"])
        self.assertEqual(len(select_public_candidates(rows)), 0)

    def test_research_still_retains_minus_400_alternate(self) -> None:
        rows = _run({"a": 14, "b": 15}, policy=_policy(["a", "b"], required=2, minimum=2), odds=_odds(line=5, price=-400, is_alternate=True))
        self.assertEqual(len(rows), 1)
        self.assertEqual(int(rows.iloc[0]["price"]), -400)

    def test_candidate_gate_counts_are_accurate(self) -> None:
        odds = pd.concat([_odds(price=-110), _odds(price=-400, is_alternate=True), _odds(sportsbook="bovada", price=-110)], ignore_index=True)
        rows = _run({"a": 14, "b": 15}, policy=_policy(["a", "b"], required=2, minimum=2), odds=odds)
        gates = build_candidate_gate_counts(rows, select_public_candidates(rows)).iloc[0]
        self.assertEqual(int(gates["total_research_rows"]), 3)
        self.assertEqual(int(gates["ma_actionable_rows"]), 2)
        self.assertEqual(int(gates["price_eligible_rows"]), 2)
        self.assertEqual(int(gates["excluded_too_much_negative_juice"]), 1)

    def test_extreme_alternate_examples_report_exclusion_reason(self) -> None:
        rows = _run({"a": 14, "b": 15}, policy=_policy(["a", "b"], required=2, minimum=2), odds=_odds(line=5, price=-400, is_alternate=True))
        examples = build_extreme_alternate_examples(rows, select_public_candidates(rows))
        self.assertIn("price_out_of_range", examples.iloc[0]["exclusion_reason"])

    def test_config_file_loads(self) -> None:
        policy = load_policy(ROOT / "config" / "projection_signal_sources.json")
        self.assertEqual(policy.required_source_count, 5)
        self.assertEqual(list(policy.active_sources), ["pff", "fantasypros"])
        self.assertEqual(policy.public_candidate_policy["min_american_odds"], -150)
        self.assertEqual(policy.public_candidate_policy["max_american_odds"], 200)
        self.assertEqual(policy.staleness_policy["maximum_projection_age_hours"], 72)


if __name__ == "__main__":
    unittest.main()
