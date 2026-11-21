from __future__ import annotations
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "FM27_FirstTeam_Filter_v1.3.0.py"
TEAM = 539
OPPONENT = 900

def write_json(path: Path, value):
    path.write_text(json.dumps(value), encoding="utf-8")

def make_export(root: Path, *, paired: bool = True):
    write_json(root / "fixtures.json", [
        {"competition_id": 7, "date": "2026-11-01", "home_team_id": TEAM,
         "away_team_id": OPPONENT, "played": True, "home_goals": 2, "away_goals": 1},
        {"competition_id": 7, "date": "2026-11-02", "home_team_id": 901,
         "away_team_id": 902, "played": True},
    ])
    write_json(root / "selections.json", [
        {"team_id": TEAM, "player_uid": 10, "substitute": False},
        {"team_id": 540, "player_uid": 11, "substitute": True},
    ])
    write_json(root / "players.json", [
        {"team_id": TEAM, "uid": 10, "name": "First Team Player"},
        {"team_id": 540, "uid": 11, "name": "Reserve Player"},
    ])
    write_json(root / "player-match-stats.json", [
        {"player_uid": 10, "competition_id": 7, "date": "2026-11-01",
         "opponent_team_id": OPPONENT, "has_stats": True, "minutes": 90},
        {"player_uid": 10, "competition_id": 7, "date": "2026-11-02",
         "opponent_team_id": 901, "has_stats": True, "minutes": 90},
        {"player_uid": 20, "competition_id": 7, "date": "2026-11-01",
         "opponent_team_id": TEAM, "has_stats": True, "minutes": 90},
    ])
    with (root / "player-season-stats.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["team_id", "player_uid", "goals"])
        w.writeheader()
        w.writerows([
            {"team_id": TEAM, "player_uid": 10, "goals": 1},
            {"team_id": 540, "player_uid": 10, "goals": 4},
            {"team_id": 901, "player_uid": 20, "goals": 2},
        ])
    stats = [
        {"competition_id": 7, "date": "2026-11-01", "home_team_id": TEAM,
         "away_team_id": OPPONENT, "team_id": TEAM, "is_home": True, "expected_goals": 1.8},
        {"competition_id": 7, "date": "2026-11-01", "home_team_id": TEAM,
         "away_team_id": OPPONENT, "team_id": OPPONENT, "is_home": False, "expected_goals": 0.7},
        {"competition_id": 7, "date": "2026-11-02", "home_team_id": 901,
         "away_team_id": 902, "team_id": 901, "is_home": True, "expected_goals": 0.4},
        {"competition_id": 7, "date": "2026-11-02", "home_team_id": 901,
         "away_team_id": 902, "team_id": 902, "is_home": False, "expected_goals": 0.3},
    ]
    if not paired:
        stats = stats[:1]
    write_json(root / "team-match-stats.json", stats)
    write_json(root / "tactics.json", [{"team_id": TEAM, "name": "stale tactic"}])
    write_json(root / "set-pieces.json", [{"team_id": TEAM}])
    write_json(root / "league-tables.json", [])

class FirstTeamFilterTests(unittest.TestCase):
    def run_filter(self, root: Path):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(root), "--team-id", str(TEAM),
             "--club-uid", "680", "--club-name", "Test Club"],
            text=True, capture_output=True, check=False,
        )

    def test_keeps_first_team_and_both_match_sides_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_export(root)
            result = self.run_filter(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            fixtures = json.loads((root / "fixtures.json").read_text())
            self.assertEqual(len(fixtures), 1)
            players = json.loads((root / "players.json").read_text())
            self.assertEqual([x["uid"] for x in players], [10])
            selections = json.loads((root / "selections.json").read_text())
            self.assertEqual([x["player_uid"] for x in selections], [10])
            player_rows = json.loads((root / "player-match-stats.json").read_text())
            self.assertEqual(len(player_rows), 1)
            self.assertEqual(player_rows[0]["opponent_team_id"], OPPONENT)
            with (root / "player-season-stats.csv").open(encoding="utf-8-sig") as f:
                season_rows = list(csv.DictReader(f))
            self.assertEqual(len(season_rows), 1)
            self.assertEqual(season_rows[0]["team_id"], str(TEAM))
            team_rows = json.loads((root / "team-match-stats.json").read_text())
            self.assertEqual(len(team_rows), 2)
            self.assertEqual({x["team_id"] for x in team_rows}, {TEAM, OPPONENT})
            scope = json.loads((root / "first-team-scope.json").read_text())
            self.assertEqual(scope["counts"]["managed_team_rows"], 1)
            self.assertEqual(scope["counts"]["opponent_team_rows"], 1)
            self.assertEqual(scope["counts"]["home_team_rows"], 1)
            self.assertEqual(scope["counts"]["away_team_rows"], 1)
            self.assertFalse((root / "tactics.json").exists())
            self.assertFalse((root / "set-pieces.json").exists())
            self.assertFalse((root / "league-tables.json").exists())

    def test_rejects_single_sided_team_match_export(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            make_export(root, paired=False)
            result = self.run_filter(root)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exactly two team rows", result.stdout + result.stderr)
            self.assertFalse((root / "first-team-scope.json").exists())

if __name__ == "__main__":
    unittest.main()
