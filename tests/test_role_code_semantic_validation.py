import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "FM27_FormalPlayerReport_Enrichment_v1.1.py"
SPEC = importlib.util.spec_from_file_location("fm27_role_enrichment", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class RoleCodeSemanticValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = MODULE.read_json(ROOT / "catalog.json")
        cls.flags = MODULE.load_role_flag_catalog(cls.catalog)
        cls.eligibility = cls.catalog["role_eligibility"]

    def test_role_code_is_bit_index_not_role_array_index(self):
        # FullBack is flags=4 (bit 2); OPLineKeeper reuses that same bit in phase 1.
        result = MODULE.resolve_match_role_code(2, "DR", self.flags, self.eligibility)
        self.assertEqual(result["role_bit_mask"], "0x4")
        self.assertEqual(result["candidate_role_id"], "FullBack")
        self.assertEqual(result["verified_role_id"], "FullBack")
        self.assertEqual(result["verified_role_name_zh"], "边后卫")
        self.assertEqual(result["verified_role_phase"], 0)
        self.assertEqual(result["phase1_alternative_role_ids"], ["OPLineKeeper"])
        self.assertEqual(result["status"], "decoded_native_in_possession_role")

    def test_role_code_mapping_is_not_derived_from_catalog_array_order(self):
        # The bit mask still resolves after the role table is deliberately reversed.
        reversed_catalog = dict(self.catalog)
        reversed_catalog["roles"] = list(reversed(self.catalog["roles"]))
        flags = MODULE.load_role_flag_catalog(reversed_catalog)
        result = MODULE.resolve_match_role_code(24, "DC", flags, self.eligibility)
        self.assertEqual(result["verified_role_id"], "BallPlayingCentreBack")
        self.assertEqual(result["verified_role_name_zh"], "出球中卫")

    def test_same_channel_midfielder_role_decodes_at_mc_and_amc(self):
        for position in ("MC", "AMC"):
            with self.subTest(position=position):
                result = MODULE.resolve_match_role_code(56, position, self.flags, self.eligibility)
                self.assertEqual(result["verified_role_id"], "ChannelMidfielder")
                self.assertEqual(result["verified_role_name_zh"], "肋部中场")

    def test_screenshot_corroborated_codes_map_to_expected_native_roles(self):
        # These codes were cross-checked against the in-possession role badges in 3/3.png and 3/4.png.
        samples = {
            (1, "DC"): "CentreBack",
            (2, "DL"): "FullBack",
            (3, "DR"): "WingBack",
            (12, "GK"): "BallPlayingGoalkeeper",
            (24, "DC"): "BallPlayingCentreBack",
            (31, "ST"): "ChannelForward",
            (43, "AMR"): "PlaymakingWinger",
            (56, "MC"): "ChannelMidfielder",
        }
        for (code, position), role_id in samples.items():
            with self.subTest(code=code, position=position):
                result = MODULE.resolve_match_role_code(code, position, self.flags, self.eligibility)
                self.assertEqual(result["verified_role_id"], role_id)
                self.assertEqual(result["status"], "decoded_native_in_possession_role")

    def test_role_code_and_position_eligibility_conflict_keeps_raw_value(self):
        # Observed in one retained row: 27 maps to InsideForward, but ST does not allow that role.
        result = MODULE.resolve_match_role_code(27, "ST", self.flags, self.eligibility)
        self.assertEqual(result["candidate_role_id"], "InsideForward")
        self.assertEqual(result["verified_role_id"], "")
        self.assertEqual(result["status"], "position_eligibility_conflict")

    def test_unmapped_role_code_keeps_raw_value(self):
        result = MODULE.resolve_match_role_code(250, "DC", self.flags, self.eligibility)
        self.assertEqual(result["verified_role_id"], "")
        self.assertEqual(result["status"], "no_matching_native_role_flag")

    def test_missing_role_code_is_not_confused_with_zero(self):
        missing = MODULE.resolve_match_role_code(None, "GK", self.flags, self.eligibility)
        goalkeeper = MODULE.resolve_match_role_code(0, "GK", self.flags, self.eligibility)
        self.assertEqual(missing["status"], "no_same_match_role_history")
        self.assertEqual(goalkeeper["verified_role_id"], "Goalkeeper")

    def test_semantic_audit_records_phase_alternatives_and_position_conflicts(self):
        rows = [
            {
                "role_code_raw": "2", "position_code": "4",
                "player_uid": "1", "player_name": "Player A",
                "match_position_id_candidate": "DR",
                **{
                    "role_code_bit_mask": "0x4",
                    "match_role_id_verified": "FullBack",
                    "match_role_name_verified": "边后卫",
                    "role_code_meaning_status": "decoded_native_in_possession_role",
                },
            },
            {
                "role_code_raw": "27", "position_code": "16384",
                "player_uid": "2", "player_name": "Player B",
                "match_position_id_candidate": "ST",
                "role_code_bit_mask": "0x8000000",
                "match_role_id_verified": "",
                "match_role_name_verified": "",
                "role_code_meaning_status": "position_eligibility_conflict",
            },
        ]
        audit = MODULE.build_role_code_semantic_validation(rows, self.catalog)
        code2 = next(x for x in audit["codes"] if x["role_code_raw"] == "2")
        code27 = next(x for x in audit["codes"] if x["role_code_raw"] == "27")
        self.assertEqual(code2["decoded_role_ids"], ["FullBack"])
        self.assertEqual(code2["phase1_same_flag_alternatives"], [{"id": "OPLineKeeper", "name_zh": "门线门将"}])
        self.assertEqual(code27["position_eligibility_conflict_rows"], 1)
        self.assertEqual(audit["visual_crosscheck"]["visually_crosschecked_role_codes"], [1, 2, 3, 12, 24, 31, 43, 56])

    def test_role_audit_groups_include_decoded_role_names(self):
        rows = [{
            "position_code": "4",
            "match_position_id_candidate": "DR",
            "match_position_name_candidate": "右后卫",
            "role_code_raw": 2,
            "role_code_bit_mask": "0x4",
            "match_role_id_verified": "FullBack",
            "match_role_name_verified": "边后卫",
            "player_name": "Player A",
            "role_code_meaning_status": "decoded_native_in_possession_role",
        }]
        result = MODULE.build_role_audit(rows)
        self.assertEqual(result[0]["match_role_id_verified"], "FullBack")
        self.assertEqual(result[0]["match_role_name_verified"], "边后卫")


if __name__ == "__main__":
    unittest.main()
