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
import hashlib
import json
import re
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

POSITION_REVIEW_FIELDS = [
    "sample_id", "game_build", "section_schema", "record_variant_scope",
    "date", "competition_id", "competition_name", "round", "kick_off_time",
    "home_away", "opponent_team_id", "opponent_name", "player_uid", "player_name",
    "position_code_raw", "candidate_position_id", "candidate_position_name_zh",
    "game_ui_position_text", "screenshot_file", "screenshot_sha256",
    "visual_review_position_id", "visual_review_position_name_zh",
    "visual_review_status", "reviewed_by", "reviewed_at", "notes",
]
POSITION_REVIEW_RESPONSE_FIELDS = (
    "game_ui_position_text", "screenshot_file", "screenshot_sha256",
    "visual_review_position_id", "visual_review_position_name_zh",
    "visual_review_status", "reviewed_by", "reviewed_at", "notes",
)
POSITION_UI_MIN_DISTINCT_MATCHES = 3
POSITION_UI_MIN_DISTINCT_PLAYERS = 2


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
        result["match_position_mapping_evidence"] = (
            "native_catalog_exact_single_bit_mask_candidate; "
            "game UI semantics have not been visually verified"
        )
    elif code is None:
        result["match_position_mapping_evidence"] = "no_same_match_position_history"
    else:
        result["match_position_mapping_evidence"] = "raw_mask_not_in_native_single_bit_catalog"

    # A numeric match against fmsave's same-match history confirms the decoded number only.
    # It does not establish what the number means on the in-game match screen.
    result["match_position_semantic_status"] = "unverified_pending_game_ui_evidence"
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


def build_position_review_queue(
    identified_rows: list[dict[str, Any]],
    unresolved_rows: list[dict[str, Any]],
    position_map: dict[int, dict[str, str]],
    game_build: str = "",
    section_schema: int | None = None,
    record_variant_scope: str = "",
    samples_per_code: int = 3,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, int]]]:
    """Create a compact, reproducible UI review set covering as many codes per fixture as possible."""
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

    # Organise identified samples by raw code and exact fixture. Unresolved rows contribute
    # coverage counts but are not review samples because there is no safe player identity.
    by_code_fixture: dict[str, dict[tuple[str, str, str], list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for row in identified_rows:
        value = as_int(row.get("position_code"))
        fixture_key = review_fixture_key(row)
        if value is None or fixture_key is None:
            continue
        by_code_fixture[str(value)][fixture_key].append(row)

    def row_sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
        minutes = as_int(row.get("minutes"))
        return (
            0 if minutes is not None and minutes > 0 else 1,
            0 if row.get("player_uid") not in (None, "") else 1,
            str(row.get("player_uid") or ""),
            str(row.get("player_name") or ""),
        )

    # Choose a shared set of match screens. Rare codes that occur in fewer than three
    # fixtures force all their available fixtures into the set. Then greedily add fixtures
    # that cover the greatest number of still-underrepresented codes.
    selected_fixtures: set[tuple[str, str, str]] = set()
    code_fixture_keys = {
        code: set(fixtures)
        for code, fixtures in by_code_fixture.items()
    }
    for code, fixture_keys in code_fixture_keys.items():
        if len(fixture_keys) < samples_per_code:
            selected_fixtures.update(fixture_keys)

    while True:
        unfinished = {
            code for code, fixture_keys in code_fixture_keys.items()
            if len(fixture_keys) >= samples_per_code
            and sum(1 for key in selected_fixtures if key in fixture_keys) < samples_per_code
        }
        if not unfinished:
            break
        remaining = set().union(*(code_fixture_keys[code] for code in unfinished)) - selected_fixtures
        if not remaining:
            break
        best_fixture = max(
            remaining,
            key=lambda key: (
                sum(1 for code in unfinished if key in code_fixture_keys[code]),
                sum(len(by_code_fixture[code].get(key, [])) for code in unfinished),
                tuple(reversed(key)),
            ),
        )
        selected_fixtures.add(best_fixture)

    queue: list[dict[str, Any]] = []
    for raw_code in sorted(by_code_fixture, key=lambda item: int(item)):
        fixture_map = by_code_fixture[raw_code]
        code_fixtures = sorted(
            (key for key in selected_fixtures if key in fixture_map),
            key=lambda key: (key[0], key[1], key[2]),
        )
        selected_rows: list[dict[str, Any]] = []
        used_players: set[str] = set()

        # First choose one player from each selected fixture, preferring a new player.
        for fixture_key in code_fixtures:
            candidates = sorted(fixture_map[fixture_key], key=row_sort_key)
            row = next(
                (
                    item for item in candidates
                    if item.get("player_uid") not in (None, "")
                    and str(item.get("player_uid")) not in used_players
                ),
                candidates[0] if candidates else None,
            )
            if row is None:
                continue
            selected_rows.append(row)
            if row.get("player_uid") not in (None, ""):
                used_players.add(str(row.get("player_uid")))
            if len(selected_rows) >= samples_per_code:
                break

        # For a rare code with fewer available fixtures, add other distinct players from
        # those same fixtures. This yields useful row-level evidence without pretending the
        # repeated observations are independent matches.
        if len(selected_rows) < samples_per_code:
            selected_keys = {
                (
                    review_fixture_key(row),
                    str(row.get("player_uid") or ""),
                )
                for row in selected_rows
            }
            additional_rows = sorted(
                (
                    row
                    for fixture_key in code_fixtures
                    for row in fixture_map[fixture_key]
                ),
                key=lambda row: (
                    0 if row.get("player_uid") not in (None, "") else 1,
                    str(row.get("date") or ""),
                    str(row.get("competition_id") or ""),
                    str(row.get("opponent_team_id") or ""),
                    str(row.get("player_uid") or ""),
                ),
            )
            for row in additional_rows:
                fixture_key = review_fixture_key(row)
                player_key = str(row.get("player_uid") or "")
                sample_key = (fixture_key, player_key)
                if fixture_key is None or sample_key in selected_keys:
                    continue
                if player_key and player_key in used_players:
                    continue
                selected_rows.append(row)
                selected_keys.add(sample_key)
                if player_key:
                    used_players.add(player_key)
                if len(selected_rows) >= samples_per_code:
                    break

        mapped = position_map.get(int(raw_code))
        for row in selected_rows:
            fixture_key = review_fixture_key(row) or ("", "", "")
            stable_key = "|".join((
                game_build, str(section_schema or ""), raw_code,
                *fixture_key, str(row.get("player_uid") or ""),
            ))
            sample_id = hashlib.sha256(stable_key.encode("utf-8")).hexdigest()[:16]
            queue.append({
                "sample_id": sample_id,
                "game_build": game_build,
                "section_schema": section_schema if section_schema is not None else "",
                "record_variant_scope": record_variant_scope,
                "date": row.get("date") or "",
                "competition_id": row.get("competition_id") or "",
                "competition_name": row.get("competition_name") or "",
                "round": row.get("round") or "",
                "kick_off_time": row.get("kick_off_time") or "",
                "home_away": row.get("home_away") or "",
                "opponent_team_id": row.get("opponent_team_id") or "",
                "opponent_name": row.get("opponent_name") or "",
                "player_uid": row.get("player_uid") or "",
                "player_name": row.get("player_name") or "",
                "position_code_raw": raw_code,
                "candidate_position_id": mapped["id"] if mapped else "",
                "candidate_position_name_zh": mapped["name_zh"] if mapped else "",
                "game_ui_position_text": "",
                "screenshot_file": "",
                "screenshot_sha256": "",
                "visual_review_position_id": "",
                "visual_review_position_name_zh": "",
                "visual_review_status": "pending_visual_review",
                "reviewed_by": "",
                "reviewed_at": "",
                "notes": "",
            })

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
            "review_samples": sum(1 for item in queue if item["position_code_raw"] == code),
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
            "review_samples": 0,
            "distinct_matches_available": 0,
            "distinct_players_available": 0,
        }
    return queue, coverage


def preserve_position_review_responses(
    review_path: Path, queue: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Carry forward manually entered UI evidence when re-enriching the same export folder."""
    if not review_path.is_file():
        return queue
    _, previous_rows = read_csv(review_path)
    previous_by_id = {
        str(row.get("sample_id") or ""): row
        for row in previous_rows
        if row.get("sample_id")
    }
    for row in queue:
        previous = previous_by_id.get(str(row["sample_id"]))
        if not previous:
            continue
        for field in POSITION_REVIEW_RESPONSE_FIELDS:
            value = previous.get(field)
            if value not in (None, ""):
                row[field] = value
    return queue


def build_position_semantic_validation(
    queue: list[dict[str, Any]],
    coverage: dict[str, dict[str, int]],
    position_map: dict[int, dict[str, str]],
    source: dict[str, Any],
    numeric_crosscheck: dict[str, Any],
) -> dict[str, Any]:
    """Only promote a mapping after visually reviewed screenshots from distinct matches."""
    codes: list[dict[str, Any]] = []
    for raw_code, counts in coverage.items():
        code_value = as_int(raw_code)
        mapped = position_map.get(code_value) if code_value is not None else None
        records = [row for row in queue if row.get("position_code_raw") == raw_code]
        confirmed = [
            row for row in records
            if row.get("visual_review_status") == "confirmed"
            and row.get("game_ui_position_text")
            and row.get("screenshot_file")
            and bool(re.fullmatch(r"[0-9a-fA-F]{64}", str(row.get("screenshot_sha256") or "")))
            and row.get("visual_review_position_id")
            and row.get("visual_review_position_name_zh")
            and row.get("reviewed_by")
            and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(row.get("reviewed_at") or "")))
        ]
        fixture_keys = {review_fixture_key(row) for row in confirmed}
        fixture_keys.discard(None)
        player_keys = {
            str(row.get("player_uid")) for row in confirmed
            if row.get("player_uid") not in (None, "")
        }
        observed_ids = sorted({str(row["visual_review_position_id"]) for row in confirmed})
        mismatches = [
            row for row in confirmed
            if mapped is not None and str(row["visual_review_position_id"]) != mapped["id"]
        ]
        if mapped is None:
            status = "unmapped_raw_code"
        elif mismatches:
            status = "candidate_mapping_conflicts_with_visual_evidence"
        elif len(observed_ids) > 1:
            status = "conflicting_visual_evidence"
        elif (
            len(fixture_keys) >= POSITION_UI_MIN_DISTINCT_MATCHES
            and len(player_keys) >= min(
                POSITION_UI_MIN_DISTINCT_PLAYERS,
                max(1, int(counts.get("distinct_players_available", 0))),
            )
        ):
            status = "verified_by_visual_game_ui_evidence"
        elif len(confirmed) >= 3 and len(fixture_keys) < POSITION_UI_MIN_DISTINCT_MATCHES:
            status = "visually_observed_but_insufficient_match_diversity"
        elif len(fixture_keys) >= POSITION_UI_MIN_DISTINCT_MATCHES:
            status = "visually_observed_but_insufficient_player_diversity"
        else:
            status = "pending_game_ui_validation"

        verified_id = (
            str(confirmed[0]["visual_review_position_id"])
            if status == "verified_by_visual_game_ui_evidence" and confirmed
            else ""
        )
        verified_name = (
            str(confirmed[0]["visual_review_position_name_zh"])
            if status == "verified_by_visual_game_ui_evidence" and confirmed
            else ""
        )
        codes.append({
            "position_code_raw": raw_code,
            "candidate_position_id": mapped["id"] if mapped else None,
            "candidate_position_name_zh": mapped["name_zh"] if mapped else None,
            **counts,
            "visual_evidence_rows_confirmed": len(confirmed),
            "distinct_matches_visually_checked": len(fixture_keys),
            "distinct_players_visually_checked": len(player_keys),
            "minimum_distinct_players_required": min(
                POSITION_UI_MIN_DISTINCT_PLAYERS,
                max(1, int(counts.get("distinct_players_available", 0))),
            ),
            "observed_ui_position_ids": observed_ids,
            "candidate_mismatch_rows": len(mismatches),
            "semantic_status": status,
            "verified_position_id": verified_id or None,
            "verified_position_name_zh": verified_name or None,
        })

    verified_codes = [row for row in codes if row["semantic_status"] == "verified_by_visual_game_ui_evidence"]
    return {
        "audit_version": "1.0-game-ui-position-semantic-validation",
        "overall_status": "partially_verified" if verified_codes else "pending_game_ui_validation",
        "game": source.get("game") or "FM27",
        "game_build": source.get("game_build"),
        "fmsave_version": source.get("fmsave_version"),
        "section": source.get("section") or "match_stats_cfg",
        "section_schema": source.get("section_schema"),
        "record_variant_counts": source.get("record_variant_counts") or {},
        "raw_position_source": {
            "encoding": "uint16 little-endian",
            "raw_window_offset": 110,
            "anchor_relative_offset": 10,
            "note": "This validates where the raw numeric field is read; it does not validate the field's in-game positional meaning.",
        },
        "numeric_history_crosscheck": {
            **(numeric_crosscheck or {}),
            "what_it_proves": "The raw numeric code agrees with the same-match named-history numeric field where available.",
            "what_it_does_not_prove": "It does not prove that the numeric code means the candidate position label shown by the tactic-position catalog.",
        },
        "visual_validation_policy": {
            "required_evidence": "A screenshot of the exact FM27 match screen showing this player's actual match position, linked to the exact fixture and identified player.",
            "minimum_distinct_matches_per_code": POSITION_UI_MIN_DISTINCT_MATCHES,
            "minimum_distinct_players_per_code": (
                f"At least {POSITION_UI_MIN_DISTINCT_PLAYERS}; if the save contains only one identified "
                "player for a code, that player's evidence across distinct fixtures is sufficient."
            ),
            "rare_code_policy": (
                "If fewer than three distinct fixtures exist in the save, preserve up to three distinct "
                "player/fixture samples but report insufficient_match_diversity; do not promote globally."
            ),
            "accepted_review_status": "confirmed",
            "required_review_fields": [
                "game_ui_position_text", "screenshot_file", "screenshot_sha256",
                "visual_review_position_id", "visual_review_position_name_zh",
                "reviewed_by", "reviewed_at",
            ],
            "important": "Unreviewed screenshot references and numerical cross-checks never promote a candidate to verified.",
        },
        "codes": codes,
        "verified_code_count": len(verified_codes),
        "unverified_code_count": len(codes) - len(verified_codes),
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

    review_path = export_dir / "position-semantic-review.csv"
    position_review_queue, position_code_coverage = build_position_review_queue(
        identified_rows,
        unresolved_rows,
        position_map,
        game_build=game_build,
        section_schema=section_schema,
        record_variant_scope=record_variant_scope,
    )
    position_review_queue = preserve_position_review_responses(review_path, position_review_queue)
    numeric_position_check = (
        (formal_summary.get("raw_history_crosschecks") or {}).get("position_code")
        or (identity_audit.get("validation") or {}).get("raw_player_fields", {}).get("position_code")
        or {}
    )
    position_semantic_validation = build_position_semantic_validation(
        position_review_queue,
        position_code_coverage,
        position_map,
        source,
        numeric_position_check,
    )
    for row in enriched:
        verified = next((
            item for item in position_semantic_validation["codes"]
            if item["position_code_raw"] == str(row.get("position_code") or "")
            and item["semantic_status"] == "verified_by_visual_game_ui_evidence"
        ), None)
        if verified:
            row["match_position_semantic_status"] = verified["semantic_status"]
            row["match_position_id_verified"] = verified["verified_position_id"] or ""
            row["match_position_name_verified"] = verified["verified_position_name_zh"] or ""

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
    write_csv(export_dir / "position-semantic-review.csv", POSITION_REVIEW_FIELDS, position_review_queue)
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
        "enrichment_version": "1.1",
        "input_identified_rows": len(identified_rows),
        "output_rows": len(enriched),
        "unresolved_rows_left_unchanged": len(unresolved_rows),
        "native_catalog_position_map": [
            {"mask": mask, **value}
            for mask, value in sorted(position_map.items())
        ],
        "position_mapping_note": (
            "Every catalog-derived label remains a candidate until at least three distinct fixtures for that raw code "
            "have screenshot-backed, visually reviewed FM27 match-screen evidence. Numeric same-match history matches "
            "confirm only the raw number, not its in-game meaning. Raw position_code is always preserved."
        ),
        "position_candidate_row_counts": dict(position_counts),
        "position_semantic_validation": {
            "status": position_semantic_validation["overall_status"],
            "review_queue_file": "position-semantic-review.csv",
            "audit_file": "position-semantic-validation.json",
            "raw_position_codes_with_candidate_labels": sum(
                1 for item in position_semantic_validation["codes"] if item["candidate_position_id"]
            ),
            "verified_position_codes": position_semantic_validation["verified_code_count"],
            "unverified_position_codes": position_semantic_validation["unverified_code_count"],
            "distinct_match_threshold_per_code": POSITION_UI_MIN_DISTINCT_MATCHES,
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
    print(f"Position candidates (not semantic verification): {audit['position_candidate_row_counts']}")
    semantic = audit.get("position_semantic_validation", {})
    print(
        "Position UI semantic validation: "
        f"{semantic.get('verified_position_codes', 0)} verified / "
        f"{semantic.get('unverified_position_codes', 0)} pending or unresolved; "
        f"review queue: {semantic.get('review_queue_file', 'not generated')}"
    )
    print(f"Role codes preserved raw: {audit['role_code_raw_counts']}")
    print(f"Outputs written to: {args.export_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
