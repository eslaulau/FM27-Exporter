import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "FM27_FormalPlayerReport_Enrichment_v1.1.py"
SPEC = importlib.util.spec_from_file_location("fm27_position_enrichment", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PositionSemanticValidationTests(unittest.TestCase):
    def setUp(self):
        self.position_map = {
            4: {"id": "DR", "name_zh": "右后卫"},
            1: {"id": "GK", "name_zh": "门将"},
        }
        self.source = {
            "game": "FM27",
            "game_build": "27.1.1+2511875",
            "fmsave_version": "0.14.3",
            "section": "match_stats_cfg",
            "section_schema": 6,
            "record_variant_counts": {"0100013d1f": 3},
        }

    def make_rows(self, code=4, count=3):
        return [
            {
                "date": f"2027-04-{20 + index:02d}",
                "competition_id": "7",
                "competition_name": "Premier Division",
                "round": f"Round {index + 1}",
                "kick_off_time": "15:00:00",
                "home_away": "主场",
                "opponent_team_id": str(500 + index),
                "opponent_name": f"Opponent {index + 1}",
                "player_uid": str(1000 + index),
                "player_name": f"Player {index + 1}",
                "position_code": str(code),
                "minutes": "90",
            }
            for index in range(count)
        ]

    def test_catalog_match_never_auto_confirms_game_ui_semantics(self):
        row = self.make_rows(count=1)[0]
        enriched = MODULE.enrich_record(row, {}, self.position_map)
        self.assertEqual(enriched["match_position_id_candidate"], "DR")
        self.assertEqual(enriched["match_position_name_candidate"], "右后卫")
        self.assertEqual(
            enriched["match_position_semantic_status"],
            "unverified_pending_game_ui_evidence",
        )
        self.assertEqual(enriched["match_position_id_verified"], "")
        self.assertEqual(enriched["match_position_name_verified"], "")

    def test_review_queue_covers_identified_and_unresolved_counts(self):
        identified = self.make_rows(count=3)
        unresolved = [{
            "date": "2027-04-25",
            "competition_id": "7",
            "opponent_team_id": "599",
            "position_code": "4",
        }]
        queue, coverage = MODULE.build_position_review_queue(
            identified, unresolved, self.position_map,
            game_build="27.1.1+2511875", section_schema=6,
            record_variant_scope="0100013d1f",
        )
        self.assertEqual(coverage["4"]["total_rows"], 4)
        self.assertEqual(coverage["4"]["identified_rows"], 3)
        self.assertEqual(coverage["4"]["unresolved_rows"], 1)
        self.assertEqual(len(queue), 3)
        self.assertEqual(len({row["sample_id"] for row in queue}), 3)
        self.assertTrue(all(row["visual_review_status"] == "pending_visual_review" for row in queue))

    def test_raw_numeric_history_match_does_not_verify_position_meaning(self):
        queue, coverage = MODULE.build_position_review_queue(
            self.make_rows(count=3), [], self.position_map,
            game_build="27.1.1+2511875", section_schema=6,
        )
        audit = MODULE.build_position_semantic_validation(
            queue, coverage, self.position_map, self.source,
            {"matched": 174, "tested": 174, "mismatches": 0},
        )
        self.assertEqual(audit["overall_status"], "pending_game_ui_validation")
        self.assertEqual(audit["codes"][0]["semantic_status"], "pending_game_ui_validation")
        self.assertEqual(audit["numeric_history_crosscheck"]["matched"], 174)
        self.assertIn("does not prove", audit["numeric_history_crosscheck"]["what_it_does_not_prove"])
        self.assertEqual(audit["verified_code_count"], 0)

    def test_three_distinct_screenshot_reviewed_matches_can_confirm_candidate(self):
        queue, coverage = MODULE.build_position_review_queue(
            self.make_rows(count=3), [], self.position_map,
            game_build="27.1.1+2511875", section_schema=6,
        )
        for row in queue:
            row.update({
                "game_ui_position_text": "右后卫",
                "screenshot_file": f"{row['sample_id']}.png",
                "screenshot_sha256": "a" * 64,
                "visual_review_position_id": "DR",
                "visual_review_position_name_zh": "右后卫",
                "visual_review_status": "confirmed",
                "reviewed_by": "visual-review",
                "reviewed_at": "2026-11-25",
            })
        audit = MODULE.build_position_semantic_validation(
            queue, coverage, self.position_map, self.source,
            {"matched": 174, "tested": 174, "mismatches": 0},
        )
        self.assertEqual(audit["overall_status"], "partially_verified")
        self.assertEqual(audit["codes"][0]["semantic_status"], "verified_by_visual_game_ui_evidence")
        self.assertEqual(audit["codes"][0]["distinct_matches_visually_checked"], 3)
        self.assertEqual(audit["codes"][0]["verified_position_id"], "DR")

    def test_rare_code_queue_keeps_distinct_players_from_one_fixture(self):
        rows = self.make_rows(code=128, count=3)
        for row in rows:
            row["date"] = "2026-08-20"
            row["opponent_team_id"] = "1275"
            row["opponent_name"] = "Trnava"
        queue, coverage = MODULE.build_position_review_queue(
            rows, [], self.position_map | {128: {"id": "DMC", "name_zh": "后腰"}},
            game_build="27.1.1+2511875", section_schema=6,
        )
        self.assertEqual(len(queue), 3)
        self.assertEqual(coverage["128"]["distinct_matches_available"], 1)
        self.assertEqual(coverage["128"]["distinct_players_available"], 3)

        for row in queue:
            row.update({
                "game_ui_position_text": "后腰",
                "screenshot_file": f"{row['sample_id']}.png",
                "screenshot_sha256": "d" * 64,
                "visual_review_position_id": "DMC",
                "visual_review_position_name_zh": "后腰",
                "visual_review_status": "confirmed",
                "reviewed_by": "visual-review",
                "reviewed_at": "2026-11-25",
            })
        audit = MODULE.build_position_semantic_validation(
            queue, coverage,
            self.position_map | {128: {"id": "DMC", "name_zh": "后腰"}},
            self.source, {},
        )
        dmc = next(item for item in audit["codes"] if item["position_code_raw"] == "128")
        self.assertEqual(dmc["semantic_status"], "visually_observed_but_insufficient_match_diversity")
        self.assertEqual(dmc["distinct_matches_visually_checked"], 1)
        self.assertEqual(dmc["distinct_players_visually_checked"], 3)
        self.assertEqual(audit["verified_code_count"], 0)

    def test_one_available_player_can_be_checked_across_three_matches(self):
        rows = self.make_rows(code=1, count=3)
        for row in rows:
            row["player_uid"] = "1000"
            row["player_name"] = "Goalkeeper"
        queue, coverage = MODULE.build_position_review_queue(
            rows, [], self.position_map,
            game_build="27.1.1+2511875", section_schema=6,
        )
        self.assertEqual(len(queue), 3)
        self.assertEqual(coverage["1"]["distinct_players_available"], 1)
        for row in queue:
            row.update({
                "game_ui_position_text": "门将",
                "screenshot_file": f"{row['sample_id']}.png",
                "screenshot_sha256": "e" * 64,
                "visual_review_position_id": "GK",
                "visual_review_position_name_zh": "门将",
                "visual_review_status": "confirmed",
                "reviewed_by": "visual-review",
                "reviewed_at": "2026-11-25",
            })
        audit = MODULE.build_position_semantic_validation(
            queue, coverage, self.position_map, self.source, {},
        )
        goalkeeper = next(item for item in audit["codes"] if item["position_code_raw"] == "1")
        self.assertEqual(goalkeeper["semantic_status"], "verified_by_visual_game_ui_evidence")
        self.assertEqual(goalkeeper["distinct_matches_visually_checked"], 3)

    def test_visual_evidence_that_disagrees_with_candidate_blocks_promotion(self):
        queue, coverage = MODULE.build_position_review_queue(
            self.make_rows(count=3), [], self.position_map,
            game_build="27.1.1+2511875", section_schema=6,
        )
        for row in queue:
            row.update({
                "game_ui_position_text": "左后卫",
                "screenshot_file": f"{row['sample_id']}.png",
                "screenshot_sha256": "b" * 64,
                "visual_review_position_id": "DL",
                "visual_review_position_name_zh": "左后卫",
                "visual_review_status": "confirmed",
                "reviewed_by": "visual-review",
                "reviewed_at": "2026-11-25",
            })
        audit = MODULE.build_position_semantic_validation(
            queue, coverage, self.position_map, self.source, {},
        )
        self.assertEqual(
            audit["codes"][0]["semantic_status"],
            "candidate_mapping_conflicts_with_visual_evidence",
        )
        self.assertEqual(audit["verified_code_count"], 0)

    def test_screenshot_metadata_without_visual_review_is_not_confirmation(self):
        queue, coverage = MODULE.build_position_review_queue(
            self.make_rows(count=3), [], self.position_map,
            game_build="27.1.1+2511875", section_schema=6,
        )
        for row in queue:
            row.update({
                "game_ui_position_text": "右后卫",
                "screenshot_file": f"{row['sample_id']}.png",
                "screenshot_sha256": "c" * 64,
                "visual_review_position_id": "DR",
                "visual_review_position_name_zh": "右后卫",
                "visual_review_status": "pending_visual_review",
                "reviewed_by": "user",
                "reviewed_at": "2026-11-25",
            })
        audit = MODULE.build_position_semantic_validation(
            queue, coverage, self.position_map, self.source, {},
        )
        self.assertEqual(audit["codes"][0]["semantic_status"], "pending_game_ui_validation")
        self.assertEqual(audit["verified_code_count"], 0)


if __name__ == "__main__":
    unittest.main()
