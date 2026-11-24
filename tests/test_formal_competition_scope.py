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
        self.assertEqual(len(played_formal), 55)
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
