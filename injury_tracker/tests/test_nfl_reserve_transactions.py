from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

from injury_tracker.scripts.injury_schema import normalize_player_name  # noqa: E402
from injury_tracker.scripts.nfl_reserve_transactions import (  # noqa: E402
    attach_events_to_current_reserves,
    classify_transaction,
    enrich_transaction_identities,
    fetch_month_pages,
    parse_month_bundle,
)
from injury_tracker.scripts.pff_enrichment import PFFPlayerProfile  # noqa: E402
import injury_tracker.scripts.nfl_reserve_transactions as transactions  # noqa: E402


TRANSACTION_HTML = """
<html><body>
  <h2>Reserve List — September</h2>
  <table>
    <tr><th>From</th><th>To</th><th>Date</th><th>Name</th><th>Position</th><th>Transaction</th></tr>
    <tr><td>Patriots Patriots</td><td>Patriots Patriots</td><td>09/01</td><td>Placed IR</td><td>WR</td><td>Reserve/Injured</td></tr>
    <tr><td>Patriots Patriots</td><td>Patriots Patriots</td><td>09/10</td><td>Placed IR</td><td>WR</td><td>Activated from Reserve/Injured</td></tr>
    <tr><td>Giants Giants</td><td>Giants Giants</td><td>09/02</td><td>Pup Player</td><td>TE</td><td>Reserve/Physically Unable to Perform</td></tr>
    <tr><td>Giants Giants</td><td>Giants Giants</td><td>09/12</td><td>Pup Player</td><td>TE</td><td>Activated from Reserve/Physically Unable to Perform</td></tr>
    <tr><td>Jets Jets</td><td>Jets Jets</td><td>09/03</td><td>NFI Player</td><td>S</td><td>Reserve/Non-Football Injury</td></tr>
    <tr><td>Jets Jets</td><td>Jets Jets</td><td>09/13</td><td>NFI Player</td><td>S</td><td>Activated from Reserve/Non-Football Injury</td></tr>
    <tr><td>Jets Jets</td><td>Jets Jets</td><td>09/15</td><td>Unknown Player</td><td>LB</td><td>Reserve/Club Controlled Weirdness</td></tr>
    <tr><td>Ravens Ravens</td><td>Ravens Ravens</td><td>09/20</td><td>DFR Player</td><td>CB</td><td>Designated for Return from Reserve/Injured</td></tr>
  </table>
</body></html>
"""


def profile(player_id: str, name: str, team: str, position: str = "WR") -> PFFPlayerProfile:
    return PFFPlayerProfile(
        player_id=player_id,
        player_name=name,
        normalized_player_name=normalize_player_name(name),
        teams={team},
        positions=Counter({position: 1}),
        identity_sources={"player_directory"},
    )


class NFLReserveTransactionTests(unittest.TestCase):
    def test_reserve_transaction_parser_preserves_dates_and_raw_wording(self) -> None:
        events = parse_month_bundle(
            {
                "pages": [
                    {
                        "url": "https://www.nfl.com/transactions/league/reserve-list/2026/9",
                        "fetched_at": "2026-09-28T12:00:00+00:00",
                        "status": "OK",
                        "body": TRANSACTION_HTML,
                    }
                ]
            },
            season=2026,
            month=9,
            raw_file="raw.json",
        )
        by_name = {(row["player_name"], row["raw_transaction"]): row for row in events}
        self.assertEqual(len(events), 8)
        self.assertEqual(by_name[("Placed IR", "Reserve/Injured")]["transaction_date"], "2026-09-01")
        self.assertEqual(by_name[("Placed IR", "Reserve/Injured")]["event_type"], "PLACED_ON_IR")
        self.assertEqual(by_name[("Placed IR", "Activated from Reserve/Injured")]["event_type"], "ACTIVATED_FROM_IR")
        self.assertEqual(by_name[("Pup Player", "Reserve/Physically Unable to Perform")]["event_type"], "PLACED_ON_PUP")
        self.assertEqual(by_name[("Pup Player", "Activated from Reserve/Physically Unable to Perform")]["event_type"], "ACTIVATED_FROM_PUP")
        self.assertEqual(by_name[("NFI Player", "Reserve/Non-Football Injury")]["event_type"], "PLACED_ON_NFI")
        self.assertEqual(by_name[("NFI Player", "Activated from Reserve/Non-Football Injury")]["event_type"], "ACTIVATED_FROM_NFI")
        self.assertEqual(by_name[("Unknown Player", "Reserve/Club Controlled Weirdness")]["event_type"], "OTHER_RESERVE_EVENT")
        self.assertEqual(by_name[("Unknown Player", "Reserve/Club Controlled Weirdness")]["raw_transaction"], "Reserve/Club Controlled Weirdness")

    def test_classification_examples(self) -> None:
        self.assertEqual(classify_transaction("Reserve/Injured"), ("PLACED_ON_IR", "IR"))
        self.assertEqual(classify_transaction("Activated from Reserve/Injured"), ("ACTIVATED_FROM_IR", "IR"))
        self.assertEqual(classify_transaction("Reserve/Physically Unable to Perform"), ("PLACED_ON_PUP", "PUP"))
        self.assertEqual(classify_transaction("Activated from Reserve/Physically Unable to Perform"), ("ACTIVATED_FROM_PUP", "PUP"))
        self.assertEqual(classify_transaction("Reserve/Non-Football Injury"), ("PLACED_ON_NFI", "NFI"))
        self.assertEqual(classify_transaction("Activated from Reserve/Non-Football Injury"), ("ACTIVATED_FROM_NFI", "NFI"))

    def test_identity_join_and_unresolved_identity_preserved(self) -> None:
        events = parse_month_bundle({"pages": [{"url": "u", "fetched_at": "f", "status": "OK", "body": TRANSACTION_HTML}]}, season=2026, month=9)
        profiles = {
            "1": profile("1", "Placed IR", "NE"),
            "2": profile("2", "Pup Player", "NYG", "TE"),
        }
        original_build = transactions.build_pff_player_index
        try:
            transactions.build_pff_player_index = lambda *args, **kwargs: profiles
            enriched, summary = enrich_transaction_identities(events, season=2026, week=3)
        finally:
            transactions.build_pff_player_index = original_build
        by_name = {row["player_name"]: row for row in enriched}
        self.assertEqual(by_name["Placed IR"]["pff_player_id"], "1")
        self.assertEqual(by_name["Pup Player"]["pff_player_id"], "2")
        self.assertEqual(by_name["Unknown Player"]["pff_identity_status"], "UNMATCHED")
        self.assertIn("MATCHED", summary["relevant_transaction_identity_counts"])

    def test_current_state_remains_authoritative_and_placement_date_attaches(self) -> None:
        current = [
            {
                "team": "NE",
                "player_name": "Placed IR",
                "normalized_player_name": normalize_player_name("Placed IR"),
                "canonical_roster_status": "IR",
                "raw_roster_status": "Reserve/Injured",
                "designated_for_return": False,
                "pff_player_id": "1",
                "pff_identity_status": "MATCHED",
                "key_candidate": False,
            }
        ]
        events = [
            {
                "team": "NE",
                "player_name": "Placed IR",
                "normalized_player_name": normalize_player_name("Placed IR"),
                "pff_player_id": "1",
                "pff_identity_status": "MATCHED",
                "transaction_date": "2026-09-01",
                "event_type": "PLACED_ON_IR",
                "reserve_status": "IR",
                "raw_transaction": "Reserve/Injured",
            }
        ]
        enriched, rec = attach_events_to_current_reserves(current, events)
        self.assertEqual(enriched[0]["reserve_transaction_date"], "2026-09-01")
        self.assertEqual(enriched[0]["reserve_transaction_type"], "PLACED_ON_IR")
        self.assertEqual(enriched[0]["canonical_roster_status"], "IR")
        self.assertEqual(rec[0]["reconciliation_status"], "HISTORY_CONFIRMS_CURRENT_STATE")

    def test_later_activation_is_flagged_but_does_not_override_current_club_state(self) -> None:
        current = [
            {
                "team": "NE",
                "player_name": "Placed IR",
                "normalized_player_name": normalize_player_name("Placed IR"),
                "canonical_roster_status": "IR",
                "raw_roster_status": "Reserve/Injured",
                "designated_for_return": False,
                "pff_player_id": "1",
                "pff_identity_status": "MATCHED",
                "key_candidate": False,
            }
        ]
        events = [
            {"team": "NE", "normalized_player_name": normalize_player_name("Placed IR"), "pff_player_id": "1", "pff_identity_status": "MATCHED", "transaction_date": "2026-09-01", "event_type": "PLACED_ON_IR", "reserve_status": "IR", "raw_transaction": "Reserve/Injured"},
            {"team": "NE", "normalized_player_name": normalize_player_name("Placed IR"), "pff_player_id": "1", "pff_identity_status": "MATCHED", "transaction_date": "2026-09-10", "event_type": "ACTIVATED_FROM_IR", "reserve_status": "IR", "raw_transaction": "Activated from Reserve/Injured"},
        ]
        enriched, rec = attach_events_to_current_reserves(current, events)
        self.assertEqual(enriched[0]["canonical_roster_status"], "IR")
        self.assertEqual(rec[0]["reconciliation_status"], "HISTORY_HAS_LATER_ACTIVATION")

    def test_designated_for_return_current_state_missing_history_date_stays_null(self) -> None:
        current = [
            {
                "team": "BAL",
                "player_name": "DFR Player",
                "normalized_player_name": normalize_player_name("DFR Player"),
                "canonical_roster_status": "IR",
                "raw_roster_status": "Reserve/Injured; Designated for Return",
                "designated_for_return": True,
                "pff_player_id": "8",
                "pff_identity_status": "MATCHED",
                "key_candidate": False,
            }
        ]
        events = [
            {"team": "BAL", "normalized_player_name": normalize_player_name("DFR Player"), "pff_player_id": "8", "pff_identity_status": "MATCHED", "transaction_date": "2026-09-01", "event_type": "PLACED_ON_IR", "reserve_status": "IR", "raw_transaction": "Reserve/Injured"},
        ]
        enriched, _rec = attach_events_to_current_reserves(current, events)
        self.assertTrue(enriched[0]["designated_for_return"])
        self.assertIsNone(enriched[0]["designated_for_return_date"])

    def test_repeated_pagination_body_is_marked_duplicate_and_not_reparsed(self) -> None:
        calls = []

        def fake_fetch(url, *, timeout, retries):
            calls.append(url)
            body = TRANSACTION_HTML.replace("</body>", '<a href="?after=duplicate">Next Page</a></body>')
            return transactions.TransactionPage(url=url, fetched_at="f", status="OK", http_status=200, body=body)

        original_fetch = transactions.fetch_page
        try:
            transactions.fetch_page = fake_fetch
            bundle = fetch_month_pages(2026, 9, delay_seconds=0)
        finally:
            transactions.fetch_page = original_fetch
        self.assertEqual(len(bundle["pages"]), 2)
        self.assertTrue(bundle["pages"][1]["duplicate_body"])
        events = parse_month_bundle(bundle, season=2026, month=9)
        self.assertEqual(len(events), 8)


if __name__ == "__main__":
    unittest.main()
