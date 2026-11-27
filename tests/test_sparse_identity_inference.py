from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "FM27_PlayerMatchReport_Recovery_v1.9_Formal.py"
SPEC = importlib.util.spec_from_file_location("fm27_report_recovery_sparse", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def history(uid: int, name: str, vector: dict) -> dict:
    return {
        "player_uid": uid,
        "player_name": name,
        "has_stats": True,
        **vector,
    }


def raw_row(signature: str, vector: dict) -> dict:
    return {
        "row_signature": signature,
        "metrics": {"shots": 1},
        "raw_player_stats": {
            "goals": vector["goals"],
            "assists": vector["assists"],
            "left_at_minute": 0,
            "entered_at_minute": 0,
            "passes_attempted": vector["passes_attempted"],
            "passes_completed": vector["passes_completed"],
        },
    }


def partial_report(date: str, opponent: int) -> dict:
    vector = {
        "goals": 0,
        "assists": 0,
        "passes_attempted": 21,
        "passes_completed": 17,
    }
    unmatched = {
        "goals": 0,
        "assists": 0,
        "passes_attempted": 8,
        "passes_completed": 5,
    }
    return {
        "competition_id": 7,
        "date": date,
        "opponent_team_id": opponent,
        # Two report appearances but only one same-match named history player.
        "anonymous_player_rows": [
            raw_row("02001600", vector),
            raw_row("02abcdef", unmatched),
        ],
        "candidate_player_history_rows": [history(10, "Player A", vector)],
    }


class SparseIdentityInferenceTests(unittest.TestCase):
    def test_repeated_unique_partial_match_vectors_can_learn_a_signature(self) -> None:
        reports = [
            partial_report("2027-03-01", 501),
            partial_report("2027-03-08", 502),
        ]
        inferred, evidence, rejected = MODULE.infer_exact_stat_signature_mappings(reports, {})
        self.assertIn("02001600", inferred)
        self.assertEqual(inferred["02001600"]["player_uid"], 10)
        self.assertEqual(len(inferred["02001600"]["derived_from_matches"]), 2)
        self.assertTrue(all(
            row["complete_match_roster_reconciliation"] is False
            for row in inferred["02001600"]["derived_from_matches"]
        ))
        self.assertFalse(any(
            item.get("signature") == "02001600"
            and item.get("reason") == "insufficient_independent_partial_match_evidence"
            for item in rejected
        ))

    def test_one_partial_match_is_not_enough_to_learn_a_signature(self) -> None:
        inferred, _evidence, rejected = MODULE.infer_exact_stat_signature_mappings(
            [partial_report("2027-03-01", 501)], {}
        )
        self.assertNotIn("02001600", inferred)
        reasoned = [
            item for item in rejected
            if item.get("signature") == "02001600"
        ]
        self.assertTrue(reasoned)
        self.assertEqual(
            reasoned[0]["reason"],
            "insufficient_independent_partial_match_evidence",
        )

    def test_complete_named_roster_still_allows_single_match_exact_mapping(self) -> None:
        first = {"goals": 0, "assists": 0, "passes_attempted": 21, "passes_completed": 17}
        second = {"goals": 1, "assists": 0, "passes_attempted": 12, "passes_completed": 9}
        report = {
            "competition_id": 7,
            "date": "2027-03-01",
            "opponent_team_id": 501,
            "anonymous_player_rows": [
                raw_row("02001600", first),
                raw_row("020e1700", second),
            ],
            "candidate_player_history_rows": [
                history(10, "Player A", first),
                history(20, "Player B", second),
            ],
        }
        inferred, _evidence, _rejected = MODULE.infer_exact_stat_signature_mappings([report], {})
        self.assertEqual(set(inferred), {"02001600", "020e1700"})


if __name__ == "__main__":
    unittest.main()
