#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Enrich FM27 match reports with native position-mask, role-code and rating provenance.

This post-processing step does not read or modify the .fm save and does not change the
original identified/unresolved CSVs. Match-position labels come from exact raw-mask
matches to the native catalog and are verified only after the raw field passes its
same-match named-history cross-check gate.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

POSITION_NAMES_ZH = {
    "GK": "门将",
    "DR": "右后卫",
    "DL": "左后卫",
    "DC": "中后卫",
    "WBR": "右翼卫",
    "WBL": "左翼卫",
    "DMC": "后腰",
    "DMR": "右中场",
    "DML": "左中场",
    "MR": "右前卫",
    "ML": "左前卫",
    "MC": "中前卫",
    "MCR": "右中前卫",
    "MCL": "左中前卫",
    "AMR": "右边锋",
    "AML": "左边锋",
    "AMC": "前腰",
    "AMCR": "右内侧前腰",
    "AMCL": "左内侧前腰",
    "ST": "中锋",
    "STR": "右中锋",
    "STL": "左中锋",
}

POSITION_RAW_CROSSCHECK_MINIMUM = 25
POSITION_VERIFIED_STATUS = "verified_by_native_position_mask_catalog"


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def as_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def load_position_catalog(catalog: dict[str, Any]) -> dict[int, dict[str, str]]:
    """Use exact native catalog masks; only 16-bit one-hot masks can match match-history codes."""
    result: dict[int, dict[str, str]] = {}
    for item in catalog.get("positions", []):
        mask = as_int(item.get("mask"))
        position_id = str(item.get("id") or "")
        if mask is None or mask <= 0 or mask > 0x8000:
            continue
        if mask & (mask - 1):
            continue
        if not position_id:
            continue
        result[mask] = {
            "id": position_id,
            "name_zh": POSITION_NAMES_ZH.get(position_id, position_id),
        }
    return result


def history_key(row: dict[str, Any]) -> tuple[int, str, int, int] | None:
    uid = as_int(row.get("player_uid"))
    comp = as_int(row.get("competition_id"))
    opponent = as_int(row.get("opponent_team_id"))
    date = str(row.get("date") or "")
    if uid is None or comp is None or opponent is None or not date:
        return None
    return uid, date, comp, opponent


def build_history_index(rows: list[dict[str, Any]]) -> dict[tuple[int, str, int, int], dict[str, Any]]:
    index: dict[tuple[int, str, int, int], dict[str, Any]] = {}
    for row in rows:
        key = history_key(row)
        if key is None:
            continue
        previous = index.get(key)
        score = (
            bool(row.get("has_stats")),
            row.get("rating") not in (None, ""),
            row.get("position_code") not in (None, ""),
        )
        previous_score = (
            bool(previous and previous.get("has_stats")),
            bool(previous and previous.get("rating") not in (None, "")),
            bool(previous and previous.get("position_code") not in (None, "")),
        )
        if previous is None or score > previous_score:
            index[key] = row
    return index


def rating_source_status(row: dict[str, Any], history: dict[str, Any] | None) -> str:
    recorded_source = str(row.get("rating_source") or "")
    if recorded_source in {
        "raw_match_report_rating_crosschecked",
        "raw_match_report_rating_recovered",
        "retained_named_player_history",
    }:
        return recorded_source
    if row.get("rating") not in (None, ""):
        return "retained_player_history_rating"
    unknown = (history or {}).get("unknown") or {}
    if as_int(unknown.get("rating_raw")) == 0:
        return "history_stores_zero_no_rating_awarded"
    if history and history.get("has_stats") is True:
        return "history_has_stats_but_no_rating_value"
    if history:
        return "history_row_has_no_stats"
    return "no_same_match_player_history_row"


def enrich_record(
    row: dict[str, Any],
    history_index: dict[tuple[int, str, int, int], dict[str, Any]],
    position_map: dict[int, dict[str, str]],
) -> dict[str, Any]:
    result = dict(row)
    key = history_key(row)
    history = history_index.get(key) if key else None
    code = as_int(row.get("position_code"))
    mapped = position_map.get(code) if code is not None else None

    result["match_position_id_candidate"] = mapped["id"] if mapped else ""
    result["match_position_name_candidate"] = mapped["name_zh"] if mapped else ""
    if mapped:
        result["match_position_mapping_evidence"] = "exact_native_position_catalog_mask_match"
        result["match_position_semantic_status"] = "pending_raw_position_crosscheck"
    elif code is None:
        result["match_position_mapping_evidence"] = "no_same_match_position_history"
        result["match_position_semantic_status"] = "no_raw_position_code"
    else:
        result["match_position_mapping_evidence"] = "raw_mask_not_in_native_single_bit_catalog"
        result["match_position_semantic_status"] = "no_exact_native_catalog_mask_match"
    result["match_position_id_verified"] = ""
    result["match_position_name_verified"] = ""

    unknown = (history or {}).get("unknown") or {}
    role_code = unknown.get("role_code")
    result["role_code_raw"] = role_code if role_code is not None else ""
    result["role_code_meaning_status"] = (
        "meaning_unconfirmed_keep_raw" if role_code is not None else "no_same_match_role_history"
    )
    result["rating_source_status"] = rating_source_status(row, history)
    return result


def review_fixture_key(row: dict[str, Any]) -> tuple[str, str, str] | None:
    date = str(row.get("date") or "")
    competition_id = str(row.get("competition_id") or "")
    opponent_team_id = str(row.get("opponent_team_id") or "")
    if not date or not competition_id or not opponent_team_id:
        return None
    return date, competition_id, opponent_team_id


def build_position_code_coverage(
    identified_rows: list[dict[str, Any]],
    unresolved_rows: list[dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Summarise observed raw position masks without asking for manual screenshot review."""
    counts: Counter[str] = Counter()
    identified_counts: Counter[str] = Counter()
    unresolved_counts: Counter[str] = Counter()
    for row in identified_rows:
        value = as_int(row.get("position_code"))
        code = str(value) if value is not None else "missing"
        counts[code] += 1
        identified_counts[code] += 1
    for row in unresolved_rows:
        value = as_int(row.get("position_code"))
        code = str(value) if value is not None else "missing"
        counts[code] += 1
        unresolved_counts[code] += 1

    coverage: dict[str, dict[str, int]] = {}
    for code in sorted((key for key in counts if key != "missing"), key=lambda item: int(item)):
        code_rows = [
            row for row in identified_rows
            if str(as_int(row.get("position_code"))) == code
        ]
        coverage[code] = {
            "total_rows": counts[code],
            "identified_rows": identified_counts[code],
            "unresolved_rows": unresolved_counts[code],
            "distinct_matches_available": len({
                key for key in (review_fixture_key(row) for row in code_rows) if key is not None
            }),
            "distinct_players_available": len({
                str(row.get("player_uid")) for row in code_rows
                if row.get("player_uid") not in (None, "")
            }),
        }
    if "missing" in counts:
        coverage["missing"] = {
            "total_rows": counts["missing"],
            "identified_rows": identified_counts["missing"],
            "unresolved_rows": unresolved_counts["missing"],
            "distinct_matches_available": 0,
            "distinct_players_available": 0,
        }
    return coverage


def position_crosscheck_passes(numeric_crosscheck: dict[str, Any]) -> bool:
    """Require a meaningful raw-field sample and a perfect same-match history comparison."""
    matched = as_int(numeric_crosscheck.get("matched")) or 0
    tested = as_int(numeric_crosscheck.get("tested")) or 0
    mismatches = as_int(numeric_crosscheck.get("mismatches")) or 0
    return (
        tested >= POSITION_RAW_CROSSCHECK_MINIMUM
        and matched == tested
        and mismatches == 0
    )


def apply_position_semantic_results(
    rows: list[dict[str, Any]],
    code_audit: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply native-mask validation while retaining raw codes as the source of truth."""
    by_code = {
        str(item.get("position_code_raw") or ""): item
        for item in code_audit
    }
    for row in rows:
        value = as_int(row.get("position_code"))
        code = str(value) if value is not None else ""
        result = by_code.get(code)
        row["match_position_semantic_status"] = (
            str(result.get("semantic_status"))
            if result
            else "no_raw_position_code_or_unmapped"
        )
        row["match_position_id_verified"] = ""
        row["match_position_name_verified"] = ""
        if result and result.get("semantic_status") == POSITION_VERIFIED_STATUS:
            row["match_position_id_verified"] = result.get("verified_position_id") or ""
            row["match_position_name_verified"] = result.get("verified_position_name_zh") or ""
    return rows


def build_position_semantic_validation(
    coverage: dict[str, dict[str, int]],
    position_map: dict[int, dict[str, str]],
    source: dict[str, Any],
    numeric_crosscheck: dict[str, Any],
    catalog: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate raw match-position masks against FM27's native position-mask catalog."""
    crosscheck_passed = position_crosscheck_passes(numeric_crosscheck or {})
    codes: list[dict[str, Any]] = []
    for raw_code, counts in coverage.items():
        code_value = as_int(raw_code)
        mapped = position_map.get(code_value) if code_value is not None else None
        if mapped is None:
            status = "no_exact_native_catalog_mask_match"
        elif crosscheck_passed:
            status = POSITION_VERIFIED_STATUS
        else:
            status = "pending_raw_position_crosscheck"

        verified = status == POSITION_VERIFIED_STATUS
        codes.append({
            "position_code_raw": raw_code,
            "position_mask_hex": f"0x{code_value:04X}" if code_value is not None and 0 <= code_value <= 0xFFFF else None,
            "candidate_position_id": mapped["id"] if mapped else None,
            "candidate_position_name_zh": mapped["name_zh"] if mapped else None,
            **counts,
            "semantic_status": status,
            "verified_position_id": mapped["id"] if verified and mapped else None,
            "verified_position_name_zh": mapped["name_zh"] if verified and mapped else None,
            "verification_basis": (
                "exact_raw_uint16_mask_match_to_native_catalog_position"
                if mapped else "raw_mask_has_no_exact_single_bit_native_catalog_entry"
            ),
        })

    verified_codes = [row for row in codes if row["semantic_status"] == POSITION_VERIFIED_STATUS]
    unverified_codes = [row for row in codes if row["semantic_status"] != POSITION_VERIFIED_STATUS]
    if not codes:
        overall_status = "no_position_codes"
    elif not crosscheck_passed:
        overall_status = "pending_raw_position_crosscheck"
    elif unverified_codes:
        overall_status = "partially_verified_by_native_position_catalog"
    else:
        overall_status = "verified_by_native_position_catalog"

    catalog = catalog or {}
    native_positions = [
        {"mask": as_int(item.get("mask")), "id": str(item.get("id") or "")}
        for item in catalog.get("positions", [])
        if as_int(item.get("mask")) is not None and item.get("id")
    ]
    return {
        "audit_version": "2.0-native-position-mask-validation",
        "overall_status": overall_status,
        "game": source.get("game") or "FM27",
        "game_build": source.get("game_build") or source.get("build"),
        "fmsave_version": source.get("fmsave_version"),
        "section": source.get("section") or "match_stats_cfg",
        "section_schema": source.get("section_schema"),
        "record_variant_counts": source.get("record_variant_counts") or {},
        "raw_position_source": {
            "field": "match_stats_cfg player appearance record",
            "encoding": "uint16 little-endian native position mask",
            "raw_window_offset": 110,
            "anchor_relative_offset": 10,
            "zero_value": "no stored match position; exported as blank",
        },
        "native_position_catalog": {
            "schema_version": catalog.get("schema_version"),
            "source_bundle_sha256": catalog.get("source_bundle_sha256"),
            "resolver_rva": catalog.get("resolver_rva"),
            "resolver_page_sha256": catalog.get("resolver_page_sha256"),
            "position_entry_count": len(native_positions),
            "positions": native_positions,
        },
        "validation_method": {
            "mapping_rule": (
                "The decoded uint16 match-position mask must exactly equal one unique "
                "single-bit mask in catalog.json positions[].mask. No player preferred-position, "
                "tactic-slot, role, duty, or formation inference is used."
            ),
            "raw_field_crosscheck_minimum": POSITION_RAW_CROSSCHECK_MINIMUM,
            "raw_field_crosscheck_requirement": (
                "At least 25 direct same-match comparisons against fmsave named history, "
                "with every compared value matching and zero mismatches."
            ),
            "screenshots_required": False,
            "limitations": [
                "A base code such as 16 maps to DC (centre-back); it does not identify DCL or DCR.",
                "The mapping identifies the stored match-position mask, not a player's role, duty, tactic slot, or separate in-possession/out-of-possession shape.",
                "Only exact masks represented as 16-bit single-bit entries are mapped; compound or unknown masks remain unmapped.",
            ],
        },
        "numeric_history_crosscheck": {
            **(numeric_crosscheck or {}),
            "passed": crosscheck_passed,
            "what_it_proves": (
                "The raw match-report position field is decoded consistently with same-match "
                "named player history for the tested records."
            ),
            "what_it_does_not_prove": (
                "The cross-check alone does not define position names; semantic labels come "
                "from exact equality with the native FM27 position-mask catalog."
            ),
        },
        "codes": codes,
        "verified_code_count": len(verified_codes),
        "unverified_code_count": len(unverified_codes),
    }


def build_role_audit(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (
            str(row.get("position_code") or ""),
            str(row.get("match_position_id_candidate") or ""),
            str(row.get("match_position_name_candidate") or ""),
            str(row.get("role_code_raw") or ""),
        )
        item = grouped.setdefault(key, {"rows": 0, "players": set()})
        item["rows"] += 1
        if row.get("player_name"):
            item["players"].add(str(row["player_name"]))
    result = []
    for (position_code, position_id, position_name, role_code), values in sorted(
        grouped.items(), key=lambda x: (x[0][0], x[0][3])
    ):
        result.append({
            "position_code_raw": position_code,
            "position_id_candidate": position_id,
            "position_name_candidate": position_name,
            "role_code_raw": role_code,
            "history_rows": values["rows"],
            "distinct_players": len(values["players"]),
            "role_code_meaning_status": "UNDECODED_KEEP_RAW" if role_code else "NO_HISTORY_ROLE_CODE",
        })
    return result


def build_unresolved_sightings(
    unresolved_rows: list[dict[str, str]],
    probe: dict[str, Any] | None,
) -> dict[str, Any]:
    signatures = {
        str(row.get("report_row_signature") or "").lower()
        for row in unresolved_rows
        if row.get("report_row_signature")
    }
    results: dict[str, list[dict[str, Any]]] = {sig: [] for sig in sorted(signatures)}
    if probe:
        for report in probe.get("reports", []):
            for row in report.get("anonymous_player_rows", []):
                sig = str(row.get("row_signature") or "").lower()
                if sig not in results:
                    continue
                raw = row.get("raw_player_stats") or {}
                metrics = row.get("metrics") or {}
                activity_values = [
                    raw.get("goals"), raw.get("assists"), raw.get("left_at_minute"),
                    raw.get("entered_at_minute"), raw.get("passes_attempted"),
                    raw.get("passes_completed"),
                ]
                activity = any((as_int(value) or 0) > 0 for value in activity_values)
                activity = activity or any(
                    isinstance(value, (int, float)) and value > 0
                    for value in metrics.values()
                )
                opponent = (
                    report.get("away_team_name") if report.get("is_home")
                    else report.get("home_team_name")
                )
                candidates = []
                for candidate in report.get("candidate_player_history_rows", []):
                    candidates.append({
                        "player_uid": candidate.get("player_uid"),
                        "player_name": candidate.get("player_name"),
                        "has_stats": candidate.get("has_stats"),
                        "minutes": candidate.get("minutes"),
                        "rating": candidate.get("rating"),
                        "position_code": candidate.get("position_code"),
                    })
                results[sig].append({
                    "date": report.get("date"),
                    "competition_id": report.get("competition_id"),
                    "round": report.get("round"),
                    "opponent_team_id": report.get("opponent_team_id"),
                    "opponent_name": opponent,
                    "report_row_index": row.get("row_index"),
                    "activity_hint_from_raw_stats": activity,
                    "raw_player_stats": raw,
                    "detail_metrics": metrics,
                    "same_match_named_history_candidates_not_linked_to_this_signature": candidates,
                })
    return {
        "scope": "unresolved report-row signatures only; sightings are not identity proof",
        "unresolved_signatures": {
            sig: {
                "active_sightings": sum(1 for x in sightings if x["activity_hint_from_raw_stats"]),
                "all_roster_sightings": len(sightings),
                "sightings": sightings,
                "status": "unresolved_no_unique_uid_evidence",
            }
            for sig, sightings in results.items()
        },
    }


def enrich_report(export_dir: Path, catalog_path: Path | None = None) -> dict[str, Any]:
    identified_path = export_dir / "player-match-report-identified.csv"
    unresolved_path = export_dir / "player-match-report-unresolved.csv"
    probe_path = export_dir / "player-report-probe.json"
    history_path = export_dir / "player-match-stats-history-archive.json"
    if not history_path.is_file():
        history_path = export_dir / "player-match-stats.json"
    if catalog_path is None:
        catalog_path = Path(__file__).resolve().with_name("catalog.json")

    if not identified_path.is_file():
        raise FileNotFoundError(f"Missing identified report: {identified_path}")
    if not catalog_path.is_file():
        raise FileNotFoundError(f"Missing native catalog: {catalog_path}")

    fields, identified_rows = read_csv(identified_path)
    _, unresolved_rows = read_csv(unresolved_path) if unresolved_path.is_file() else ([], [])
    history_rows = read_json(history_path) if history_path.is_file() else []
    probe = read_json(probe_path) if probe_path.is_file() else None
    catalog = read_json(catalog_path)
    position_map = load_position_catalog(catalog)
    history_index = build_history_index(history_rows)

    enriched = [enrich_record(row, history_index, position_map) for row in identified_rows]

    identity_audit_path = export_dir / "player-report-identity-audit.json"
    formal_summary_path = export_dir / "player-match-report-formal-summary.json"
    identity_audit = read_json(identity_audit_path) if identity_audit_path.is_file() else {}
    formal_summary = read_json(formal_summary_path) if formal_summary_path.is_file() else {}
    source = identity_audit.get("source") or {}
    if not source:
        save_info_path = export_dir / "save-info.json"
        source = read_json(save_info_path) if save_info_path.is_file() else {}
    game_build = str(source.get("game_build") or source.get("build") or "")
    section_schema = as_int(source.get("section_schema"))
    variants = source.get("record_variant_counts") or {}
    record_variant_scope = ", ".join(sorted(str(key) for key in variants))

    position_code_coverage = build_position_code_coverage(
        identified_rows, unresolved_rows
    )
    numeric_position_check = (
        (formal_summary.get("raw_history_crosschecks") or {}).get("position_code")
        or (identity_audit.get("validation") or {}).get("raw_player_fields", {}).get("position_code")
        or {}
    )
    position_semantic_validation = build_position_semantic_validation(
        position_code_coverage,
        position_map,
        source,
        numeric_position_check,
        catalog,
    )
    enriched = apply_position_semantic_results(
        enriched, position_semantic_validation["codes"]
    )

    extra_fields = [
        "match_position_id_candidate",
        "match_position_name_candidate",
        "match_position_mapping_evidence",
        "match_position_semantic_status",
        "match_position_id_verified",
        "match_position_name_verified",
        "role_code_raw",
        "role_code_meaning_status",
        "rating_source_status",
    ]
    output_fields = list(fields) + [x for x in extra_fields if x not in fields]
    write_csv(export_dir / "player-match-report-identified-enriched.csv", output_fields, enriched)
    write_json(export_dir / "position-semantic-validation.json", position_semantic_validation)

    role_audit = build_role_audit(enriched)
    write_csv(
        export_dir / "player-match-report-role-code-audit-enriched.csv",
        [
            "position_code_raw", "position_id_candidate", "position_name_candidate",
            "role_code_raw", "history_rows", "distinct_players", "role_code_meaning_status",
        ],
        role_audit,
    )

    position_counts = Counter(
        str(row.get("match_position_id_candidate") or "unmapped_or_no_history")
        for row in enriched
    )
    role_counts = Counter(
        str(row.get("role_code_raw") or "missing")
        for row in enriched
    )
    rating_counts = Counter(str(row.get("rating_source_status") or "unknown") for row in enriched)
    audit = {
        "enrichment_version": "1.2",
        "input_identified_rows": len(identified_rows),
        "output_rows": len(enriched),
        "unresolved_rows_left_unchanged": len(unresolved_rows),
        "native_catalog_position_map": [
            {"mask": mask, **value}
            for mask, value in sorted(position_map.items())
        ],
        "position_mapping_note": (
            "Raw match-position masks are mapped by exact equality with the native FM27 catalog.json "
            "positions[].mask entries. Mapping is verified only when the raw uint16 field passes at least "
            "25 same-match named-history comparisons with zero mismatches. No screenshot is required. "
            "Raw position_code is always preserved; roles, duties, tactic slots and split in/out-of-possession "
            "positions are not inferred."
        ),
        "position_candidate_row_counts": dict(position_counts),
        "position_semantic_validation": {
            "status": position_semantic_validation["overall_status"],
            "audit_file": "position-semantic-validation.json",
            "raw_position_codes_with_candidate_labels": sum(
                1 for item in position_semantic_validation["codes"] if item["candidate_position_id"]
            ),
            "verified_position_codes": position_semantic_validation["verified_code_count"],
            "unverified_position_codes": position_semantic_validation["unverified_code_count"],
            "raw_field_crosscheck_minimum": POSITION_RAW_CROSSCHECK_MINIMUM,
            "screenshots_required": False,
            "code_coverage": position_code_coverage,
        },
        "role_code_note": (
            "role_code is retained as a raw byte. Upstream fmsave documents its meaning as unestablished; "
            "it is not decoded by array order or by candidate roles."
        ),
        "role_code_raw_counts": dict(role_counts),
        "role_code_position_groups": role_audit,
        "rating_note": (
            "Ratings are sourced from the detailed raw match-report record at raw-window offset +136 "
            "(uint16 little-endian hundredths, divided by 100 and rounded half-up to one decimal) only when "
            "the current save passes at least 25 exact named-history rating cross-checks with zero mismatches. "
            "Otherwise retained same-match history remains the fallback; no performance-based estimate is used."
        ),
        "rating_source_status_counts": dict(rating_counts),
        "rating_rows_present": sum(1 for row in enriched if row.get("rating") not in (None, "")),
        "rating_rows_missing": sum(1 for row in enriched if row.get("rating") in (None, "")),
        "history_archive_rows": len(history_rows),
        "same_match_history_join_rows": sum(1 for row in enriched if history_key(row) in history_index),
    }
    write_json(export_dir / "player-match-report-enrichment-audit.json", audit)
    write_json(
        export_dir / "player-report-unresolved-signature-sightings.json",
        build_unresolved_sightings(unresolved_rows, probe),
    )
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("export_dir", type=Path, help="Existing FM27_Analysis_* report directory")
    parser.add_argument("--catalog", type=Path, default=None, help="Optional catalog.json path")
    args = parser.parse_args()
    audit = enrich_report(args.export_dir, args.catalog)
    print(
        "Enrichment complete: "
        f"{audit['output_rows']} identified rows; "
        f"{audit['rating_rows_present']} retained-history ratings; "
        f"{audit['unresolved_rows_left_unchanged']} unresolved identities."
    )
    print(f"Native position masks: {audit['position_candidate_row_counts']}")
    semantic = audit.get("position_semantic_validation", {})
    print(
        "Native position-mask validation: "
        f"{semantic.get('verified_position_codes', 0)} verified / "
        f"{semantic.get('unverified_position_codes', 0)} unmapped or pending; "
        "screenshots not required"
    )
    print(f"Role codes preserved raw: {audit['role_code_raw_counts']}")
    print(f"Outputs written to: {args.export_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
