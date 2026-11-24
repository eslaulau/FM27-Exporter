from __future__ import annotations

import csv
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = (
    ROOT
    / "season-reports"
    / "FM27_EngineDividend_4Back_V0.4_20261124_run139"
    / "45402984200"
)
SAVE_NAME = "FM27_EngineDividend_4Back_V0.4_20261124_run139.fm"
TEAM_ID = 472
CLUB_UID = 618


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def main() -> None:
    if not REPORT.is_dir():
        raise AssertionError(f"Regression report fixture is missing: {REPORT}")

    with tempfile.TemporaryDirectory(prefix="fm27-identity-regression-") as temp:
        export_dir = Path(temp) / "report"
        shutil.copytree(REPORT, export_dir)
        cache_path = Path(temp) / "identity-cache.json"
        cache_path.write_text(
            json.dumps(
                {
                    "cache_version": "1.2-managed-club-scoped",
                    "game": "FM27",
                    "team_id": TEAM_ID,
                    "club_uid": CLUB_UID,
                    "competition_id": 0,
                    "mappings": {},
                    "rejected_mappings": [],
                }
            ),
            encoding="utf-8",
        )

        helper = ROOT / "FM27_PlayerMatchReport_Recovery_v1.9_Formal.py"
        command = [
            sys.executable,
            str(helper),
            str(Path(temp) / SAVE_NAME),
            str(export_dir),
            "--cache-file",
            str(cache_path),
            "--team-id",
            str(TEAM_ID),
            "--club-uid",
            str(CLUB_UID),
            "--reuse-probe",
        ]
        completed = subprocess.run(
            command, cwd=ROOT, text=True, capture_output=True, check=False
        )
        if completed.returncode:
            raise AssertionError(
                "Identity recovery failed.\nSTDOUT:\n"
                + completed.stdout
                + "\nSTDERR:\n"
                + completed.stderr
            )

        summary = read_json(export_dir / "player-match-report-formal-summary.json")
        audit = read_json(export_dir / "player-report-identity-audit.json")
        learned = read_json(export_dir / "FM27_PlayerIdentityCache_Formal_v1.1_learned.json")

        expected = {
            "active_player_appearances": 94,
            "identified_appearances": 94,
            "unresolved_appearances": 0,
            "unique_players_identified": 26,
        }
        actual = {key: summary.get(key) for key in expected}
        if actual != expected:
            raise AssertionError(f"Unexpected identity coverage: {actual}; expected {expected}")

        exact_map = audit.get("identity", {}).get("exact_stat_vector_signature_mappings", {})
        if len(exact_map) != 26:
            raise AssertionError(f"Expected 26 exact-vector signature mappings, got {len(exact_map)}")
        if len(learned.get("mappings", {})) != 26:
            raise AssertionError("Learned cache does not contain all 26 validated mappings")

        crosschecks = audit.get("validation", {}).get("raw_history_crosschecks", {})
        for field in ("goals", "assists", "passes_attempted", "passes_completed"):
            item = crosschecks.get(field, {})
            if item.get("tested", 0) != 94 or item.get("matched", 0) != 94 or item.get("mismatches", 0) != 0:
                raise AssertionError(f"{field} same-match cross-check failed: {item}")

        enrichment = ROOT / "FM27_FormalPlayerReport_Enrichment_v1.1.py"
        enriched = subprocess.run(
            [sys.executable, str(enrichment), str(export_dir), "--catalog", str(ROOT / "catalog.json")],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if enriched.returncode:
            raise AssertionError(
                "Position/role enrichment failed.\nSTDOUT:\n"
                + enriched.stdout
                + "\nSTDERR:\n"
                + enriched.stderr
            )

        enriched_path = export_dir / "player-match-report-identified-enriched.csv"
        with enriched_path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        if len(rows) != 94:
            raise AssertionError(f"Expected 94 enriched appearance rows, got {len(rows)}")
        if not all(row.get("player_name") for row in rows):
            raise AssertionError("One or more enriched appearance rows has no player identity")
        if not all(row.get("role_code_meaning_status") == "meaning_unconfirmed_keep_raw" for row in rows):
            raise AssertionError("Unknown role codes were not preserved as explicitly undecoded")

        print(
            "PASS: 94/94 appearances identified; 26 stable signatures recovered; "
            "four raw stat fields cross-checked 94/94; position enrichment completed; "
            "unconfirmed role codes retained without guessing."
        )


if __name__ == "__main__":
    main()
