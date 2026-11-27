from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVER = ROOT / "FM27_PlayerMatchHistory_Archive_v1.0.py"


class PlayerHistoryArchiveScopeTests(unittest.TestCase):
    def test_archiver_discovers_save_local_formal_competitions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fm27-history-scope-") as temp:
            root = Path(temp)
            export_dir = root / "export"
            archive_dir = root / "archive"
            export_dir.mkdir()

            (export_dir / "first-team-scope.json").write_text(
                json.dumps({"team_id": 472, "club_uid": 618}), encoding="utf-8"
            )
            (export_dir / "save-info.json").write_text(
                json.dumps({"game": "FM27"}), encoding="utf-8"
            )
            fixtures = [
                {
                    "competition_id": 2945, "date": "2027-03-11",
                    "home_team_id": 472, "away_team_id": 1238,
                    "home_goals": 2, "away_goals": 1, "played": True,
                    "match_rules_template": [6, 61, 0],
                },
                {
                    "competition_id": 7, "date": "2027-03-14",
                    "home_team_id": 472, "away_team_id": 524,
                    "home_goals": 1, "away_goals": 0, "played": True,
                    "match_rules_template": [2, 58, 0],
                },
                {
                    "competition_id": 131, "date": "2027-03-15",
                    "home_team_id": 472, "away_team_id": 700,
                    "home_goals": 3, "away_goals": 0, "played": True,
                    "match_rules_template": [1, 18, 0],
                },
            ]
            (export_dir / "fixtures.json").write_text(
                json.dumps(fixtures), encoding="utf-8"
            )
            stats = [
                {"player_uid": 10, "player_name": "Player A", "date": "2027-03-11",
                 "competition_id": 2945, "opponent_team_id": 1238, "has_stats": True,
                 "minutes": 90, "goals": 1},
                {"player_uid": 10, "player_name": "Player A", "date": "2027-03-14",
                 "competition_id": 7, "opponent_team_id": 524, "has_stats": True,
                 "minutes": 90, "goals": 0},
                {"player_uid": 10, "player_name": "Player A", "date": "2027-03-15",
                 "competition_id": 131, "opponent_team_id": 700, "has_stats": True,
                 "minutes": 90, "goals": 0},
            ]
            (export_dir / "player-match-stats.json").write_text(
                json.dumps(stats), encoding="utf-8"
            )

            completed = subprocess.run(
                [
                    sys.executable, str(ARCHIVER),
                    "--export-dir", str(export_dir),
                    "--archive-dir", str(archive_dir),
                    "--team-id", "472",
                    "--club-uid", "618",
                ],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

            archived = json.loads(
                (export_dir / "player-match-stats-history-archive.json").read_text(encoding="utf-8")
            )
            self.assertEqual({row["competition_id"] for row in archived}, {7, 2945})
            summary = json.loads(
                (export_dir / "player-match-history-archive-summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["formal_competition_ids"], [7, 2945])
            self.assertEqual(summary["excluded_competition_ids"], [131])

    def test_unknown_rule_family_is_retained_and_disclosed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fm27-history-unknown-") as temp:
            root = Path(temp)
            export_dir = root / "export"
            export_dir.mkdir()
            (export_dir / "first-team-scope.json").write_text(
                json.dumps({"team_id": 472, "club_uid": 618}), encoding="utf-8"
            )
            (export_dir / "save-info.json").write_text(
                json.dumps({"game": "FM27"}), encoding="utf-8"
            )
            (export_dir / "fixtures.json").write_text(json.dumps([{
                "competition_id": 2945, "date": "2027-03-11",
                "home_team_id": 472, "away_team_id": 1238,
                "home_goals": 1, "away_goals": 0, "played": True,
            }]), encoding="utf-8")
            (export_dir / "player-match-stats.json").write_text("[]", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable, str(ARCHIVER),
                    "--export-dir", str(export_dir),
                    "--archive-dir", str(root / "archive"),
                    "--team-id", "472",
                    "--club-uid", "618",
                ],
                text=True, capture_output=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            summary = json.loads(
                (export_dir / "player-match-history-archive-summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["formal_competition_ids"], [2945])
            self.assertEqual(summary["unclassified_competition_ids"], [2945])


if __name__ == "__main__":
    unittest.main()
