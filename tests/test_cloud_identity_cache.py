from __future__ import annotations

import csv
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "FM27_CloudExport_IdentityCache.py"
SPEC = importlib.util.spec_from_file_location("fm27_cloud_identity_cache", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


class CloudIdentityCacheTests(unittest.TestCase):
    def make_current_export(self, root: Path, team_id: int = 472, club_uid: int = 618) -> Path:
        export_dir = root / "current"
        export_dir.mkdir()
        write_json(export_dir / "save-info.json", {
            "game": "FM27",
            "build": "27.1.1+2511875",
            "section_schemas": {"match_stats_cfg": 6},
        })
        write_json(export_dir / "first-team-scope.json", {
            "team_id": team_id, "club_uid": club_uid,
        })
        with (export_dir / "player-season-stats.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=["player_uid", "player_name", "kind", "team_id"])
            writer.writeheader()
            writer.writerow({"player_uid": 10, "player_name": "Player A", "kind": "overall", "team_id": team_id})
            writer.writerow({"player_uid": 20, "player_name": "Player B", "kind": "overall", "team_id": team_id})
        return export_dir

    def make_prior_report(self, root: Path, team_id: int = 472, club_uid: int = 618, game_build: str = "27.1.1+2511875") -> Path:
        report_dir = root / "reports" / "1" / "123456789" / "FM27_Analysis_20261127_000000"
        cache = {
            "cache_version": "1.2-managed-club-scoped",
            "game": "FM27",
            "team_id": team_id,
            "club_uid": club_uid,
            "competition_id": 0,
            "mappings": {
                "02001600": {
                    "player_uid": 10,
                    "player_name": "Player A",
                    "evidence": "unique_exact_same_match_stat_vector",
                    "confidence": "high",
                    "derived_from_matches": [{
                        "player_uid": 10, "player_name": "Player A",
                        "same_match_history_has_stats": True,
                        "exact_stat_vector_match": True,
                        "matched_fields": ["goals", "assists", "passes_attempted", "passes_completed"],
                        "reason": "unique_exact_four_field_same_match_stat_vector",
                    }],
                },
                "020e1700": {
                    "player_uid": 20,
                    "player_name": "Wrong historical name",
                    "evidence": "unique_exact_same_match_stat_vector",
                    "confidence": "high",
                    "derived_from_matches": [],
                },
                "028a1000": {
                    "player_uid": 99,
                    "player_name": "Player who left",
                    "evidence": "unique_exact_same_match_stat_vector",
                    "confidence": "high",
                    "derived_from_matches": [],
                },
            },
        }
        write_json(report_dir / MODULE.CACHE_NAME, cache)
        write_json(report_dir / MODULE.AUDIT_NAME, {
            "team_id": team_id,
            "club_uid": club_uid,
            "source": {
                "game": "FM27",
                "game_build": game_build,
                "section": "match_stats_cfg",
                "section_schema": 6,
            },
            "scope": {"identified_appearance_rows": 20},
            "identity": {
                "signature_mapping_count": 3,
                "signature_layout": {
                    "bytes": 4,
                    "offset_from_statistics_anchor": -100,
                },
            },
        })
        write_json(report_dir / MODULE.MANIFEST_NAME, {
            "exporter_version": "1.5.0",
            "workflow_run_id": "123456789",
            "exported_at_utc": "2026-11-27T00:00:00Z",
            "source_sha256_verified": "a" * 64,
        })
        return report_dir

    def test_reuses_only_exact_club_team_and_current_roster_identities(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fm27-cloud-cache-") as temp:
            root = Path(temp)
            export_dir = self.make_current_export(root)
            report_dir = self.make_prior_report(root)
            output = root / "seed.json"

            result = MODULE.build_seed(root / "reports", export_dir, 472, 618, output)
            seed = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(result["status"], "seeded")
            self.assertEqual(list(seed["mappings"]), ["02001600"])
            self.assertEqual(seed["mappings"]["02001600"]["player_uid"], 10)
            self.assertEqual(seed["seed_source"]["workflow_run_id"], "123456789")
            self.assertGreaterEqual(result["rejected_mappings"], 2)

    def test_new_club_does_not_inherit_another_clubs_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fm27-cloud-cache-club-") as temp:
            root = Path(temp)
            export_dir = self.make_current_export(root, team_id=900, club_uid=901)
            self.make_prior_report(root, team_id=472, club_uid=618)
            output = root / "seed.json"

            result = MODULE.build_seed(root / "reports", export_dir, 900, 901, output)
            seed = json.loads(output.read_text(encoding="utf-8"))

            self.assertEqual(result["status"], "empty_seed_no_compatible_prior_club_cache")
            self.assertEqual(seed["mappings"], {})
            self.assertIsNone(seed["seed_source"])

    def test_different_game_build_is_not_reused(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fm27-cloud-cache-build-") as temp:
            root = Path(temp)
            export_dir = self.make_current_export(root)
            self.make_prior_report(root, game_build="27.1.0+2505117")
            output = root / "seed.json"

            result = MODULE.build_seed(root / "reports", export_dir, 472, 618, output)
            self.assertEqual(result["reused_mappings"], 0)

    def test_conflicting_signatures_for_one_uid_are_quarantined(self) -> None:
        mappings = {
            "02001600": {
                "player_uid": 10, "player_name": "Player A",
                "evidence": "unique_exact_same_match_stat_vector", "confidence": "high",
            },
            "020e1700": {
                "player_uid": 10, "player_name": "Player A",
                "evidence": "unique_exact_same_match_stat_vector", "confidence": "high",
            },
        }
        accepted, rejected = MODULE.filter_current_roster_mappings(mappings, {10: "Player A"})
        self.assertEqual(accepted, {})
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["reason"], "player_uid_maps_to_multiple_signatures")


if __name__ == "__main__":
    unittest.main()
