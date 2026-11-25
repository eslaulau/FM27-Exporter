import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "FM27_PlayerMatchReport_Recovery_v1.9_Formal.py"
SPEC = importlib.util.spec_from_file_location("fm27_report_recovery", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class FormalCompetitionScopeTests(unittest.TestCase):
    def test_discovers_save_local_continental_id_and_cups(self):
        fixtures = [
            {"competition_id": 7, "home_team_id": 472, "away_team_id": 501, "match_rules_template": [2, 58, 0]},
            {"competition_id": 2945, "home_team_id": 800, "away_team_id": 472, "match_rules_template": [6, 61, 2]},
            {"competition_id": 2945, "home_team_id": 472, "away_team_id": 801, "match_rules_template": [7, 67, 1]},
            {"competition_id": 661, "home_team_id": 472, "away_team_id": 502, "match_rules_template": [5, 63, 0]},
            {"competition_id": 662, "home_team_id": 503, "away_team_id": 472, "match_rules_template": [5, 58, 1]},
        ]
        formal, excluded, unclassified = MODULE.discover_formal_competition_ids(fixtures, 472)
        self.assertEqual(formal, {7, 2945, 661, 662})
        self.assertEqual(excluded, set())
        self.assertEqual(unclassified, set())

    def test_excludes_all_friendly_and_preseason_competition_ids(self):
        fixtures = [
            {"competition_id": 131, "home_team_id": 472, "away_team_id": 501, "match_rules_template": [1, 18, 0]},
            {"competition_id": 395, "home_team_id": 502, "away_team_id": 472, "match_rules_template": [1, 18, 1]},
            {"competition_id": 7, "home_team_id": 472, "away_team_id": 503, "match_rules_template": [2, 58, 0]},
        ]
        formal, excluded, unclassified = MODULE.discover_formal_competition_ids(fixtures, 472)
        self.assertEqual(formal, {7})
        self.assertEqual(excluded, {131, 395})
        self.assertEqual(unclassified, set())

    def test_includes_unknown_rule_family_conservatively_and_reports_it(self):
        fixtures = [
            {"competition_id": 999, "home_team_id": 472, "away_team_id": 504},
        ]
        formal, excluded, unclassified = MODULE.discover_formal_competition_ids(fixtures, 472)
        self.assertEqual(formal, {999})
        self.assertEqual(excluded, set())
        self.assertEqual(unclassified, {999})

    def test_brighton_run100_real_export_includes_continental_competition(self):
        fixture_path = (
            ROOT / "season-reports" / "Brighton_V3_1_Compact_HighPress_20261124_run100"
            / "45318755045" / "fixtures.json"
        )
        with fixture_path.open("r", encoding="utf-8") as stream:
            fixtures = json.load(stream)
        formal, excluded, unclassified = MODULE.discover_formal_competition_ids(fixtures, 472)
        self.assertEqual(formal, {7, 661, 662, 2945})
        self.assertIn(131, excluded)
        self.assertIn(395, excluded)
        played_formal = [
            row for row in fixtures
            if row.get("played") is True
            and row.get("competition_id") in formal
            and 472 in (row.get("home_team_id"), row.get("away_team_id"))
        ]
        self.assertEqual(len(played_formal), 57)
        self.assertEqual(unclassified, set())

    def test_rule_family_groups_are_save_local(self):
        fixtures = [
            {"competition_id": 7, "home_team_id": 472, "away_team_id": 501, "match_rules_template": [2, 58, 0]},
            {"competition_id": 2945, "home_team_id": 472, "away_team_id": 502, "match_rules_template": [7, 61, 2]},
            {"competition_id": 661, "home_team_id": 472, "away_team_id": 503, "match_rules_template": [5, 63, 0]},
            {"competition_id": 131, "home_team_id": 472, "away_team_id": 504, "match_rules_template": [1, 18, 0]},
        ]
        families = MODULE.discover_competition_rule_families(fixtures, 472)
        self.assertEqual(families[7], {2})
        self.assertEqual(families[2945], {7})
        self.assertEqual(families[661], {5})
        self.assertEqual(families[131], {1})

    def test_parser_completeness_uses_reports_retained_by_native_reader(self):
        native = {
            (7, 503, 472, "2027-04-24", "20:00:00", 472): {},
            (2945, 1166, 472, "2027-04-29", "20:00:00", 472): {},
        }
        reports = [
            {"competition_id": 7, "date": "2027-04-24", "home_team_id": 503, "away_team_id": 472},
            {"competition_id": 2945, "date": "2027-04-29", "home_team_id": 1166, "away_team_id": 472},
        ]
        audit = MODULE.audit_retained_report_coverage(native, reports, {7, 2945})
        self.assertTrue(audit["passed"])
        self.assertEqual(audit["native_team_match_stats_matches_retained"], 2)
        self.assertEqual(audit["decoded_reports_matching_native_retained_matches"], 2)

        incomplete = MODULE.audit_retained_report_coverage(native, reports[:1], {7, 2945})
        self.assertFalse(incomplete["passed"])
        self.assertEqual(incomplete["native_retained_matches_missing_player_detail"], [
            [2945, "2027-04-29", 1166, 472]
        ])


    def test_native_friendlies_and_unknown_competition_ids_do_not_fail_formal_coverage(self):
        native = {
            (7, 503, 472, "2027-04-24", "20:00:00", 472): {},
            (131, 472, 736, "2026-07-25", "15:00:00", 472): {},
            (395, 472, 691, "2026-08-12", "15:00:00", 472): {},
            # Native reader's competition ID differs from the friendly fixture ID.
            (8208, 472, 6059, "2026-08-15", "19:30:00", 472): {},
        }
        reports = [
            {"competition_id": 7, "date": "2027-04-24", "home_team_id": 503, "away_team_id": 472},
        ]
        audit = MODULE.audit_retained_report_coverage(native, reports, {7})
        self.assertTrue(audit["passed"])
        self.assertEqual(audit["native_team_match_stats_matches_retained_all_competitions"], 4)
        self.assertEqual(audit["native_team_match_stats_matches_retained"], 1)
        self.assertEqual(audit["native_team_match_stats_matches_excluded_outside_formal_scope"], 3)
        self.assertEqual(audit["native_match_stats_competition_ids_excluded"], [131, 395, 8208])
        self.assertEqual(audit["native_retained_matches_missing_player_detail"], [])

    def test_player_goal_audit_uses_raw_rows_and_does_not_invent_scorers(self):
        fixtures = {
            (7, "2027-04-24", 503, 472): {
                "home_goals": 1,
                "away_goals": 2,
            },
        }
        reports = [
            {
                "competition_id": 7,
                "date": "2027-04-24",
                "home_team_id": 503,
                "away_team_id": 472,
                "is_home": False,
                "anonymous_player_rows": [
                    {"metrics": {"goals": 1}},
                    {"metrics": {"goals": 1}},
                    # Raw row still counts even if a later appearance filter excludes it.
                    {"metrics": {"goals": 0}},
                ],
            }
        ]
        audit = MODULE.audit_player_goal_reconciliation(reports, fixtures)
        self.assertFalse(audit["passed"])
        self.assertEqual(audit["matches_checked"], 1)
        self.assertEqual(audit["team_score_goals_total"], 2)
        self.assertEqual(audit["raw_player_record_goals_total"], 2)
        self.assertEqual(audit["unattributed_team_goals_total"], 0)
        self.assertEqual(audit["matches_with_equal_team_and_player_goals"], 1)

        reports[0]["anonymous_player_rows"][0]["metrics"]["goals"] = 0
        audit = MODULE.audit_player_goal_reconciliation(reports, fixtures)
        self.assertFalse(audit["passed"])
        self.assertEqual(audit["unattributed_team_goals_total"], 1)
        self.assertEqual(audit["unresolved_matches"][0]["status"], "team_score_exceeds_player_goals")
        self.assertNotIn("player_name", audit["unresolved_matches"][0])

    def test_ignores_other_teams_competitions(self):
        fixtures = [
            {"competition_id": 777, "home_team_id": 100, "away_team_id": 101, "match_rules_template": [7, 61, 2]},
            {"competition_id": 7, "home_team_id": 472, "away_team_id": 501, "match_rules_template": [2, 58, 0]},
        ]
        formal, excluded, unclassified = MODULE.discover_formal_competition_ids(fixtures, 472)
        self.assertEqual(formal, {7})
        self.assertEqual(excluded, set())
        self.assertEqual(unclassified, set())


if __name__ == "__main__":
    unittest.main()
