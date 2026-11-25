from __future__ import annotations

import csv
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
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
    with tempfile.TemporaryDirectory(prefix="fm27-identity-regression-") as temp:
        export_dir = Path(temp) / "report"
        export_dir.mkdir(parents=True)
        fixture_files = (
            "fixtures.json",
            "player-match-stats-history-archive.json",
            "player-match-stats.json",
            "player-season-stats.csv",
            "team-match-stats.json",
            "player-report-probe.json",
            "save-info.json",
            "validation.json",
        )
        base_url = (
            "https://raw.githubusercontent.com/eslaulau/FM27-Exporter/main/"
            "season-reports/FM27_EngineDividend_4Back_V0.4_20261124_run139/45402984200/"
        )
        for filename in fixture_files:
            with urllib.request.urlopen(base_url + filename, timeout=60) as response:
                (export_dir / filename).write_bytes(response.read())
        # Upgrade the archived probe's old hardcoded competition scope to the
        # save-local scope used by the current helper before replaying identities.
        helper = ROOT / "FM27_PlayerMatchReport_Recovery_v1.9_Formal.py"
        spec = importlib.util.spec_from_file_location("fm27_report_recovery", helper)
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        formal_ids, _, _ = module.discover_formal_competition_ids(
            read_json(export_dir / "fixtures.json"), TEAM_ID
        )
        probe_path = export_dir / "player-report-probe.json"
        probe = read_json(probe_path)
        probe.setdefault("source", {})["formal_competition_ids"] = sorted(formal_ids)
        probe_path.write_text(json.dumps(probe, ensure_ascii=False), encoding="utf-8")

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
            if item.get("tested", 0) != 95 or item.get("matched", 0) != 95 or item.get("mismatches", 0) != 0:
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
        valid_role_statuses = {
            "decoded_native_in_possession_role",
            "no_same_match_role_history",
            "no_matching_native_role_flag",
            "only_phase1_role_matches",
            "position_eligibility_conflict",
            "candidate_missing_position_context",
            "candidate_position_has_no_role_eligibility_table",
            "ambiguous_phase0_role_flag",
            "ambiguous_position_eligible_phase0_roles",
            "raw_role_code_out_of_byte_range",
        }
        unexpected = sorted({
            row.get("role_code_meaning_status") or ""
            for row in rows
            if row.get("role_code_meaning_status") not in valid_role_statuses
        })
        if unexpected:
            raise AssertionError(f"Unexpected role-code semantic statuses: {unexpected}")

        decoded = [
            row for row in rows
            if row.get("role_code_meaning_status") == "decoded_native_in_possession_role"
        ]
        if not decoded:
            raise AssertionError("No role_code values were decoded from the native catalog")

        # The saved history includes codes 35/40/41; ensure the role bit is filtered
        # by phase and native position, not interpreted as an index into catalog.roles.
        expected_roles = {
            ("35", "DMC", "HalfBack"),
            ("40", "ST", "FalseNine"),
            ("41", "AMC", "SecondStriker"),
        }
        observed_roles = {
            (
                row.get("role_code_raw"),
                row.get("match_position_id_candidate"),
                row.get("match_role_id_verified"),
            )
            for row in rows
        }
        missing_roles = expected_roles - observed_roles
        if missing_roles:
            raise AssertionError(f"Native role-bit mappings missing from enrichment: {sorted(missing_roles)}")

        conflicts = [
            row for row in rows
            if row.get("role_code_meaning_status") == "position_eligibility_conflict"
        ]
        if any(row.get("match_role_id_verified") for row in conflicts):
            raise AssertionError("A position-ineligible role was incorrectly verified")

        role_audit_path = export_dir / "role-code-semantic-validation.json"
        if not role_audit_path.is_file():
            raise AssertionError("Missing role-code semantic validation audit")
        role_audit = read_json(role_audit_path)
        if role_audit.get("decoded_role_code_count", 0) < 1:
            raise AssertionError("Role-code semantic audit reports no decoded role codes")

        print(
            "PASS: 94/94 appearances identified; 26 stable signatures recovered; "
            "four raw stat fields cross-checked 94/94; position enrichment completed; "
            f"{len(decoded)} player-match rows decoded to native in-possession roles."
        )


if __name__ == "__main__":
    main()
