#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build a safe per-club identity-cache seed for FM27 cloud exports.

Only mappings from a previously published report for the exact managed club and
first-team ID are considered. The prior report must use the same FM27 build and
the same verified four-byte signature layout. A mapping is carried forward only
when its player UID and name still occur together in the current first-team roster.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any


CACHE_NAME = "FM27_PlayerIdentityCache_Formal_v1.1_learned.json"
AUDIT_NAME = "player-report-identity-audit.json"
MANIFEST_NAME = "cloud-export-manifest.json"
SIGNATURE_BYTES = 4
SIGNATURE_OFFSET = -100
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
SIGNATURE = re.compile(r"^[0-9a-f]{8}$")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n",
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent),
        delete=False,
    )
    temp_path = Path(handle.name)
    try:
        with handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
            handle.write("\n")
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def load_current_roster(export_dir: Path, team_id: int) -> dict[int, str]:
    import csv

    path = export_dir / "player-season-stats.csv"
    if not path.is_file():
        raise RuntimeError("Current player-season-stats.csv is missing.")
    roster: dict[int, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("team_id") != str(team_id) or row.get("kind") != "overall":
                continue
            try:
                uid = int(row.get("player_uid", ""))
            except (TypeError, ValueError):
                continue
            name = str(row.get("player_name") or "").strip()
            if uid <= 0 or not name:
                continue
            previous = roster.get(uid)
            if previous is not None and previous != name:
                raise RuntimeError(
                    f"Current roster contains conflicting names for player UID {uid}: "
                    f"{previous!r} vs {name!r}"
                )
            roster[uid] = name
    if not roster:
        raise RuntimeError("No current managed first-team overall player rows were found.")
    return roster


def candidate_metadata(cache_path: Path, team_id: int, club_uid: int, game_build: str) -> dict[str, Any] | None:
    try:
        cache = read_json(cache_path)
        audit_path = cache_path.parent / AUDIT_NAME
        manifest_path = cache_path.parent / MANIFEST_NAME
        if not audit_path.is_file() or not manifest_path.is_file():
            return None
        audit = read_json(audit_path)
        manifest = read_json(manifest_path)
    except (OSError, ValueError, TypeError):
        return None

    try:
        cache_team_id = int(cache.get("team_id", -1))
        cache_club_uid = int(cache.get("club_uid", -1))
        cache_competition_id = int(cache.get("competition_id", -1))
    except (TypeError, ValueError):
        return None
    if (
        cache.get("game") != "FM27"
        or cache_team_id != team_id
        or cache_club_uid != club_uid
        or cache_competition_id != 0
    ):
        return None

    source = audit.get("source") or {}
    layout = (audit.get("identity") or {}).get("signature_layout") or {}
    try:
        audit_team_id = int(audit.get("team_id", -1))
        audit_club_uid = int(audit.get("club_uid", -1))
        section_schema = int(source.get("section_schema", -1))
        layout_bytes = int(layout.get("bytes", -1))
        layout_offset = int(layout.get("offset_from_statistics_anchor", 999999))
        identified = int((audit.get("scope") or {}).get("identified_appearance_rows", 0))
        signature_count = int((audit.get("identity") or {}).get("signature_mapping_count", 0))
    except (TypeError, ValueError):
        return None

    digest = str(manifest.get("source_sha256_verified") or "").lower()
    if (
        audit_team_id != team_id
        or audit_club_uid != club_uid
        or source.get("game") != "FM27"
        or str(source.get("game_build") or "") != game_build
        or source.get("section") != "match_stats_cfg"
        or section_schema != 6
        or layout_bytes != SIGNATURE_BYTES
        or layout_offset != SIGNATURE_OFFSET
        or not HEX_SHA256.fullmatch(digest)
        or identified <= 0
        or signature_count <= 0
        or not manifest.get("workflow_run_id")
    ):
        return None

    mappings = cache.get("mappings")
    if not isinstance(mappings, dict) or not mappings:
        return None
    try:
        exported_at = str(manifest.get("exported_at_utc") or "")
        run_id = str(manifest.get("workflow_run_id") or "")
    except Exception:
        return None
    return {
        "cache": cache,
        "audit": audit,
        "manifest": manifest,
        "mappings": mappings,
        "exported_at": exported_at,
        "run_id": run_id,
        "source_sha256": digest,
        "cache_path": cache_path,
    }


def filter_current_roster_mappings(
    mappings: dict[str, Any], roster: dict[int, str]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    accepted: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    signature_to_uid: dict[str, int] = {}
    uid_to_signature: dict[int, str] = {}
    conflicted_signatures: set[str] = set()
    conflicted_uids: set[int] = set()

    for raw_signature, raw_entry in mappings.items():
        signature = str(raw_signature).lower()
        if signature in conflicted_signatures:
            continue
        if not SIGNATURE.fullmatch(signature) or not isinstance(raw_entry, dict):
            rejected.append({"signature": signature, "reason": "invalid_cache_entry"})
            continue
        try:
            uid = int(raw_entry.get("player_uid", -1))
        except (TypeError, ValueError):
            uid = -1
        name = str(raw_entry.get("player_name") or "").strip()
        if uid in conflicted_uids:
            continue
        if uid not in roster:
            rejected.append({
                "signature": signature,
                "player_uid": uid,
                "player_name": name,
                "reason": "player_uid_not_in_current_first_team_roster",
            })
            continue
        if roster[uid] != name:
            rejected.append({
                "signature": signature,
                "player_uid": uid,
                "cached_player_name": name,
                "current_player_name": roster[uid],
                "reason": "player_name_does_not_match_current_roster",
            })
            continue
        evidence = str(raw_entry.get("evidence") or "")
        if evidence not in {
            "unique_exact_same_match_stat_vector",
            "single_remaining_same_match_named_history",
            "prior_validated_signature_cache",
        } or str(raw_entry.get("confidence") or "") != "high":
            rejected.append({
                "signature": signature,
                "player_uid": uid,
                "reason": "unsupported_or_non_high_confidence_identity_evidence",
            })
            continue

        previous_uid = signature_to_uid.get(signature)
        previous_signature = uid_to_signature.get(uid)
        if previous_uid is not None and previous_uid != uid:
            rejected.append({
                "signature": signature,
                "player_uid": uid,
                "reason": "signature_maps_to_multiple_player_uids",
            })
            accepted.pop(signature, None)
            uid_to_signature.pop(previous_uid, None)
            signature_to_uid.pop(signature, None)
            conflicted_signatures.add(signature)
            conflicted_uids.add(previous_uid)
            conflicted_uids.add(uid)
            continue
        if previous_signature is not None and previous_signature != signature:
            rejected.append({
                "signature": signature,
                "player_uid": uid,
                "reason": "player_uid_maps_to_multiple_signatures",
            })
            accepted.pop(previous_signature, None)
            signature_to_uid.pop(previous_signature, None)
            uid_to_signature.pop(uid, None)
            conflicted_signatures.add(previous_signature)
            conflicted_signatures.add(signature)
            conflicted_uids.add(uid)
            continue

        signature_to_uid[signature] = uid
        uid_to_signature[uid] = signature
        accepted[signature] = raw_entry

    return accepted, rejected


def build_seed(
    report_root: Path, export_dir: Path, team_id: int, club_uid: int, output: Path
) -> dict[str, Any]:
    save_info = read_json(export_dir / "save-info.json")
    if save_info.get("game") != "FM27":
        raise RuntimeError("Current save-info.json is not an FM27 save.")
    game_build = str(save_info.get("build") or "").strip()
    if not game_build:
        raise RuntimeError("Current FM27 game build is missing from save-info.json.")
    schema = (save_info.get("section_schemas") or {}).get("match_stats_cfg")
    if int(schema or -1) != 6:
        raise RuntimeError(f"Current match_stats_cfg schema is not 6: {schema!r}")

    current_scope = read_json(export_dir / "first-team-scope.json")
    if int(current_scope.get("team_id", -1)) != team_id or int(current_scope.get("club_uid", -1)) != club_uid:
        raise RuntimeError("Current first-team scope does not match the requested club/team.")

    roster = load_current_roster(export_dir, team_id)
    candidates = []
    if report_root.is_dir():
        for path in report_root.rglob(CACHE_NAME):
            item = candidate_metadata(path, team_id, club_uid, game_build)
            if item is not None:
                candidates.append(item)

    candidates.sort(
        key=lambda item: (item["exported_at"], item["run_id"], str(item["cache_path"])),
        reverse=True,
    )

    selected_mappings: dict[str, dict[str, Any]] = {}
    rejected: list[dict[str, Any]] = []
    signature_to_uid: dict[str, int] = {}
    uid_to_signature: dict[int, str] = {}
    conflicted_signatures: set[str] = set()
    conflicted_uids: set[int] = set()
    contributing_candidates: list[dict[str, Any]] = []

    # Merge compatible history for this club across reports. Newer reports are
    # considered first; conflicting signature/UID claims are quarantined.
    for candidate in candidates:
        filtered, rejected_items = filter_current_roster_mappings(candidate["mappings"], roster)
        rejected.extend(rejected_items)
        contributed = False
        for signature, entry in filtered.items():
            if signature in conflicted_signatures:
                continue
            uid = int(entry["player_uid"])
            if uid in conflicted_uids:
                continue
            previous_uid = signature_to_uid.get(signature)
            previous_signature = uid_to_signature.get(uid)
            if previous_uid is not None and previous_uid != uid:
                selected_mappings.pop(signature, None)
                previous_signature_for_uid = uid_to_signature.pop(previous_uid, None)
                if previous_signature_for_uid:
                    selected_mappings.pop(previous_signature_for_uid, None)
                    conflicted_signatures.add(previous_signature_for_uid)
                signature_to_uid.pop(signature, None)
                conflicted_signatures.add(signature)
                conflicted_uids.update({previous_uid, uid})
                rejected.append({
                    "signature": signature,
                    "player_uid": uid,
                    "previous_player_uid": previous_uid,
                    "reason": "cross_report_signature_identity_conflict",
                })
                continue
            if previous_signature is not None and previous_signature != signature:
                selected_mappings.pop(previous_signature, None)
                signature_to_uid.pop(previous_signature, None)
                uid_to_signature.pop(uid, None)
                conflicted_signatures.update({previous_signature, signature})
                conflicted_uids.add(uid)
                rejected.append({
                    "signature": signature,
                    "player_uid": uid,
                    "previous_signature": previous_signature,
                    "reason": "cross_report_player_signature_conflict",
                })
                continue
            if previous_uid is None and previous_signature is None:
                selected_mappings[signature] = entry
                signature_to_uid[signature] = uid
                uid_to_signature[uid] = signature
                contributed = True
        if contributed:
            contributing_candidates.append(candidate)

    selected = contributing_candidates[0] if contributing_candidates else None
    contributing_candidates.reverse()
    contributing_reports = []
    for candidate in contributing_candidates:
        try:
            report_path = candidate["cache_path"].parent.relative_to(report_root).as_posix()
        except ValueError:
            report_path = candidate["cache_path"].parent.as_posix()
        contributing_reports.append({
            "report_path": report_path,
            "workflow_run_id": candidate["run_id"],
            "source_sha256_verified": candidate["source_sha256"],
        })

    seed_source = None
    if selected_mappings:
        seed_source = {
            "source": "previous_published_same_club_cloud_reports",
            "source_reports": contributing_reports,
            "source_game_build": game_build,
            "reused_current_roster_mappings": len(selected_mappings),
            "filtered_or_rejected_mappings": len(rejected),
            "cross_report_conflicts": len(conflicted_signatures) + len(conflicted_uids),
            "filter_policy": "exact club/team, exact game build/signature layout, current first-team UID and exact name, one-to-one signature mapping",
        }

    seed = {
        "cache_version": "1.3-cloud-club-roster-seed",
        "game": "FM27",
        "team_id": team_id,
        "club_uid": club_uid,
        "competition_id": 0,
        "scope": "exact managed club UID and owned first-team ID; cross-run mappings revalidated against current first-team UID/name",
        "seed_source": seed_source,
        "mappings": selected_mappings,
        "rejected_mappings": rejected,
    }
    atomic_json(output, seed)
    return {
        "status": "seeded" if selected_mappings else "empty_seed_no_compatible_prior_club_cache",
        "club_uid": club_uid,
        "team_id": team_id,
        "current_first_team_players": len(roster),
        "reused_mappings": len(selected_mappings),
        "rejected_mappings": len(rejected),
        "source_run_ids": [item["workflow_run_id"] for item in contributing_reports],
        "source_reports": [item["report_path"] for item in contributing_reports],
        "output": str(output),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-root", required=True, type=Path)
    parser.add_argument("--current-export-dir", required=True, type=Path)
    parser.add_argument("--team-id", required=True, type=int)
    parser.add_argument("--club-uid", required=True, type=int)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = build_seed(
            args.report_root.resolve(),
            args.current_export_dir.resolve(),
            args.team_id,
            args.club_uid,
            args.output.resolve(),
        )
    except Exception as exc:
        print(f"IDENTITY_CACHE_SEED_ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
