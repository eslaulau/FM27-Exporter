from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "FM27_CloudExport_IdentityPolicy.py"


def audit(identified: int, actual: int, unresolved: int) -> dict:
    return {
        "scope": {
            "identified_appearance_rows": identified,
            "actual_appearance_rows": actual,
            "unresolved_appearance_rows": unresolved,
        }
    }


class CloudIdentityPolicyTests(unittest.TestCase):
    def run_policy(self, value: dict) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "identity-audit.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            return subprocess.run(
                [sys.executable, str(POLICY), str(path)],
                capture_output=True,
                text=True,
                check=False,
            )

    def test_complete_identity_coverage_is_accepted(self) -> None:
        result = self.run_policy(audit(94, 94, 0))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "complete")

    def test_partial_identity_coverage_is_publishable_and_explicit(self) -> None:
        result = self.run_policy(audit(123, 125, 2))
        self.assertEqual(result.returncode, 0, result.stderr)
        policy = json.loads(result.stdout)
        self.assertEqual(policy["status"], "partial")
        self.assertFalse(policy["complete"])
        self.assertEqual(policy["unresolved_appearances"], 2)
        self.assertEqual(policy["identified_appearances"] + policy["unresolved_appearances"], 125)

    def test_inconsistent_accounting_is_rejected(self) -> None:
        result = self.run_policy(audit(123, 125, 1))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("identity accounting mismatch", result.stderr)

    def test_zero_identified_appearances_is_rejected(self) -> None:
        result = self.run_policy(audit(0, 125, 125))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no player appearances could be identified", result.stderr)

    def test_zero_actual_appearances_is_rejected(self) -> None:
        result = self.run_policy(audit(0, 0, 0))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no active player appearances", result.stderr)


if __name__ == "__main__":
    unittest.main()
