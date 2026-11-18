#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Add conservative position, role-code and rating-source annotations to FM27 reports.

This is a post-processing step. It does not read or modify the .fm save and does not
change the original identified/unresolved CSVs. Non-GK position labels are explicitly
candidates derived from exact single-bit matches to the native tactic-position catalog.
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
    if mapped and mapped["id"] == "GK":
        result["match_position_mapping_evidence"] = "native_catalog_exact_mask; GK also named by upstream reference"
    elif mapped:
        result["match_position_mapping_evidence"] = "native_catalog_exact_single_bit_mask_candidate; not UI-verified for match history"
    elif code is None:
        result["match_position_mapping_evidence"] = "no_same_match_position_history"
    else:
        result["match_position_mapping_evidence"] = "raw_mask_not_in_native_single_bit_catalog"

    unknown = (history or {}).get("unknown") or {}
    role_code = unknown.get("role_code")
    result["role_code_raw"] = role_code if role_code is not None else ""
    result["role_code_meaning_status"] = (
        "meaning_unconfirmed_keep_raw" if role_code is not None else "no_same_match_role_history"
    )
    result["rating_source_status"] = rating_source_status(row, history)
    return result


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
    extra_fields = [
        "match_position_id_candidate",
        "match_position_name_candidate",
        "match_position_mapping_evidence",
        "role_code_raw",
        "role_code_meaning_status",
        "rating_source_status",
    ]
    output_fields = list(fields) + [x for x in extra_fields if x not in fields]
    write_csv(export_dir / "player-match-report-identified-enriched.csv", output_fields, enriched)

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
        "enrichment_version": "1.1",
        "input_identified_rows": len(identified_rows),
        "output_rows": len(enriched),
        "unresolved_rows_left_unchanged": len(unresolved_rows),
        "native_catalog_position_map": [
            {"mask": mask, **value}
            for mask, value in sorted(position_map.items())
        ],
        "position_mapping_note": (
            "Only exact single-bit numeric matches to the bundle's native tactic-position catalog are labelled. "
            "GK is the only match-history position named by the upstream fmsave reference; other labels are candidates, "
            "not UI-verified match-position semantics. Raw position_code is preserved."
        ),
        "position_candidate_row_counts": dict(position_counts),
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
    print(f"Position candidates: {audit['position_candidate_row_counts']}")
    print(f"Role codes preserved raw: {audit['role_code_raw_counts']}")
    print(f"Outputs written to: {args.export_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
