import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "FM27_PlayerMatchReport_Recovery_v1.9_Formal.py"
SPEC = importlib.util.spec_from_file_location("fm27_report_recovery_fields", HELPER)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class PlayerMatchPositionRatingTests(unittest.TestCase):
    def test_raw_position_and_variant_rating_are_decoded_and_crosschecked(self):
        raw = bytearray(160)
        raw[20] = 1
        raw[56] = 0
        raw[67] = 0
        raw[71] = 0
        raw[86] = 10
        raw[87] = 9
        raw[110:112] = (16).to_bytes(2, "little")
        # 27.1 embedded record variant adds five bytes before the rating field.
        raw[141:143] = (735).to_bytes(2, "little")
        row = {"raw_window_hex": bytes(raw).hex(), "raw_rating_offset": 141}
        decoded = MODULE.raw_stats_from_probe_row(row)
        self.assertEqual(decoded["position_code"], 16)
        self.assertEqual(decoded["rating_hundredths"], 735)
        self.assertEqual(MODULE.rating_from_raw_stats(decoded), 7.4)

        report = {
            "competition_id": 7,
            "date": "2027-04-24",
            "opponent_team_id": 503,
            "candidate_player_history_rows": [{
                "player_uid": 42,
                "has_stats": True,
                "position_code": 16,
                "rating": 7.4,
            }],
            "anonymous_player_rows": [{
                "row_signature": "aabbccdd",
                **row,
            }],
        }
        checks = MODULE.audit_raw_history_crosschecks(
            [report], {"aabbccdd": {"player_uid": 42}}, {}
        )
        self.assertEqual(checks["position_code"], {"matched": 1, "tested": 1, "mismatches": 0})
        self.assertEqual(checks["rating"], {"matched": 1, "tested": 1, "mismatches": 0})

    def test_cached_probe_rating_offset_requires_one_known_variant(self):
        source = {
            "layout_source_build": "27.1.0+2505117",
            "layout_source_schema": 6,
            "record_variant_counts": {"0100013d1f": 56},
        }
        self.assertEqual(MODULE.cached_probe_rating_offset(source), 141)
        mixed = dict(source, record_variant_counts={"0100013d1f": 55, "default": 1})
        self.assertIsNone(MODULE.cached_probe_rating_offset(mixed))

    def test_legacy_default_variant_keeps_legacy_rating_offset(self):
        raw = bytearray(160)
        raw[110:112] = (4).to_bytes(2, "little")
        raw[136:138] = (681).to_bytes(2, "little")
        decoded = MODULE.decode_raw_player_stats(bytes(raw), rating_offset=136)
        self.assertEqual(decoded["position_code"], 4)
        self.assertEqual(decoded["rating_hundredths"], 681)
        self.assertEqual(MODULE.rating_from_raw_stats(decoded), 6.8)


if __name__ == "__main__":
    unittest.main()
