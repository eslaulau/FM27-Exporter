import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "FM27_FormalPlayerReport_Enrichment_v1.1.py"
SPEC = importlib.util.spec_from_file_location("fm27_position_enrichment", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class NativePositionMaskValidationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = {
            "schema_version": 1,
            "source_bundle_sha256": "a" * 64,
            "resolver_rva": "0x64fe90",
            "resolver_page_sha256": "b" * 64,
            "positions": [
                {"id": "GK", "mask": 1},
                {"id": "DR", "mask": 4},
                {"id": "DL", "mask": 8},
                {"id": "DC", "mask": 16},
                {"id": "DMC", "mask": 128},
                {"id": "MC", "mask": 1024},
                {"id": "AMR", "mask": 2048},
                {"id": "AML", "mask": 4096},
                {"id": "AMC", "mask": 8192},
                {"id": "ST", "mask": 16384},
                # Compound tactical slots are intentionally not equivalent to raw 16-bit match codes.
                {"id": "DCR", "mask": 2097168},
                {"id": "DCL", "mask": 1048592},
            ],
        }
        self.position_map = MODULE.load_position_catalog(self.catalog)
        self.source = {
            "game": "FM27",
            "game_build": "27.1.1+2511875",
            "fmsave_version": "0.14.3",
            "section": "match_stats_cfg",
            "section_schema": 6,
            "record_variant_counts": {"0100013d1f": 56},
        }

    def make_rows(self, code=4, count=3):
        return [
            {
                "date": f"2027-04-{20 + index:02d}",
                "competition_id": "7",
                "opponent_team_id": str(500 + index),
                "player_uid": str(1000 + index),
                "player_name": f"Player {index + 1}",
                "position_code": str(code),
                "minutes": "90",
            }
            for index in range(count)
        ]

    def test_catalog_uses_exact_16_bit_single_bit_masks_only(self):
        self.assertEqual(
            self.position_map,
            {
                1: {"id": "GK", "name_zh": "门将"},
                4: {"id": "DR", "name_zh": "右后卫"},
                8: {"id": "DL", "name_zh": "左后卫"},
                16: {"id": "DC", "name_zh": "中后卫"},
                128: {"id": "DMC", "name_zh": "后腰"},
                1024: {"id": "MC", "name_zh": "中前卫"},
                2048: {"id": "AMR", "name_zh": "右边锋"},
                4096: {"id": "AML", "name_zh": "左边锋"},
                8192: {"id": "AMC", "name_zh": "前腰"},
                16384: {"id": "ST", "name_zh": "中锋"},
            },
        )

    def test_exact_catalog_mask_and_passed_raw_crosscheck_verify_mapping(self):
        rows = self.make_rows(code=4, count=3)
        coverage = MODULE.build_position_code_coverage(rows, [])
        audit = MODULE.build_position_semantic_validation(
            coverage,
            self.position_map,
            self.source,
            {"matched": 210, "tested": 210, "mismatches": 0},
            self.catalog,
        )
        right_back = next(item for item in audit["codes"] if item["position_code_raw"] == "4")
        self.assertEqual(audit["overall_status"], "verified_by_native_position_catalog")
        self.assertEqual(audit["verified_code_count"], 1)
        self.assertEqual(right_back["position_mask_hex"], "0x0004")
        self.assertEqual(right_back["semantic_status"], "verified_by_native_position_mask_catalog")
        self.assertEqual(right_back["verified_position_id"], "DR")
        self.assertEqual(right_back["verified_position_name_zh"], "右后卫")
        self.assertFalse(audit["validation_method"]["screenshots_required"])

    def test_raw_mask_validation_does_not_require_three_fixtures_or_screenshots(self):
        coverage = MODULE.build_position_code_coverage(self.make_rows(count=1), [])
        audit = MODULE.build_position_semantic_validation(
            coverage,
            self.position_map,
            self.source,
            {"matched": 25, "tested": 25, "mismatches": 0},
            self.catalog,
        )
        self.assertEqual(audit["verified_code_count"], 1)
        self.assertEqual(audit["codes"][0]["semantic_status"], "verified_by_native_position_mask_catalog")

    def test_raw_field_crosscheck_below_threshold_keeps_candidate_unverified(self):
        coverage = MODULE.build_position_code_coverage(self.make_rows(count=3), [])
        audit = MODULE.build_position_semantic_validation(
            coverage,
            self.position_map,
            self.source,
            {"matched": 24, "tested": 24, "mismatches": 0},
            self.catalog,
        )
        self.assertEqual(audit["overall_status"], "pending_raw_position_crosscheck")
        self.assertEqual(audit["verified_code_count"], 0)
        self.assertEqual(audit["codes"][0]["semantic_status"], "pending_raw_position_crosscheck")

    def test_any_raw_history_mismatch_blocks_semantic_verification(self):
        coverage = MODULE.build_position_code_coverage(self.make_rows(count=3), [])
        audit = MODULE.build_position_semantic_validation(
            coverage,
            self.position_map,
            self.source,
            {"matched": 209, "tested": 210, "mismatches": 1},
            self.catalog,
        )
        self.assertFalse(audit["numeric_history_crosscheck"]["passed"])
        self.assertEqual(audit["verified_code_count"], 0)

    def test_unknown_or_compound_raw_code_is_not_guessed(self):
        rows = self.make_rows(code=32, count=2)
        rows += self.make_rows(code=2097168, count=1)
        coverage = MODULE.build_position_code_coverage(rows, [])
        audit = MODULE.build_position_semantic_validation(
            coverage,
            self.position_map,
            self.source,
            {"matched": 25, "tested": 25, "mismatches": 0},
            self.catalog,
        )
        statuses = {item["position_code_raw"]: item["semantic_status"] for item in audit["codes"]}
        self.assertEqual(statuses["32"], "no_exact_native_catalog_mask_match")
        self.assertEqual(statuses["2097168"], "no_exact_native_catalog_mask_match")
        self.assertEqual(audit["unverified_code_count"], 2)

    def test_base_centre_back_mask_does_not_claim_left_or_right_centre_back(self):
        coverage = MODULE.build_position_code_coverage(self.make_rows(code=16), [])
        audit = MODULE.build_position_semantic_validation(
            coverage,
            self.position_map,
            self.source,
            {"matched": 25, "tested": 25, "mismatches": 0},
            self.catalog,
        )
        dc = audit["codes"][0]
        self.assertEqual(dc["verified_position_id"], "DC")
        self.assertIn(
            "A base code such as 16 maps to DC (centre-back); it does not identify DCL or DCR.",
            audit["validation_method"]["limitations"],
        )

    def test_verified_fields_are_applied_only_after_crosscheck_validation(self):
        rows = [
            {"position_code": "4"},
            {"position_code": "128"},
            {"position_code": ""},
        ]
        codes = [
            {
                "position_code_raw": "4",
                "semantic_status": "verified_by_native_position_mask_catalog",
                "verified_position_id": "DR",
                "verified_position_name_zh": "右后卫",
            },
            {
                "position_code_raw": "128",
                "semantic_status": "pending_raw_position_crosscheck",
                "verified_position_id": None,
                "verified_position_name_zh": None,
            },
        ]
        result = MODULE.apply_position_semantic_results(rows, codes)
        self.assertEqual(result[0]["match_position_id_verified"], "DR")
        self.assertEqual(result[0]["match_position_name_verified"], "右后卫")
        self.assertEqual(result[1]["match_position_id_verified"], "")
        self.assertEqual(result[1]["match_position_semantic_status"], "pending_raw_position_crosscheck")
        self.assertEqual(result[2]["match_position_semantic_status"], "no_raw_position_code_or_unmapped")

    def test_coverage_keeps_unresolved_rows_separate(self):
        identified = self.make_rows(code=4, count=3)
        unresolved = [{
            "date": "2027-04-25",
            "competition_id": "7",
            "opponent_team_id": "599",
            "position_code": "4",
        }]
        coverage = MODULE.build_position_code_coverage(identified, unresolved)
        self.assertEqual(coverage["4"]["total_rows"], 4)
        self.assertEqual(coverage["4"]["identified_rows"], 3)
        self.assertEqual(coverage["4"]["unresolved_rows"], 1)
        self.assertEqual(coverage["4"]["distinct_matches_available"], 3)

    def test_enriched_record_preserves_raw_code_and_marks_native_candidate_before_audit(self):
        row = self.make_rows(count=1)[0]
        enriched = MODULE.enrich_record(row, {}, self.position_map)
        self.assertEqual(enriched["position_code"], "4")
        self.assertEqual(enriched["match_position_id_candidate"], "DR")
        self.assertEqual(enriched["match_position_mapping_evidence"], "exact_native_position_catalog_mask_match")
        self.assertEqual(enriched["match_position_semantic_status"], "pending_raw_position_crosscheck")
        self.assertEqual(enriched["match_position_id_verified"], "")


if __name__ == "__main__":
    unittest.main()
