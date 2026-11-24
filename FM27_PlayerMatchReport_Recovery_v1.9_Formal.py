#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract or repair FM27 first-team player detailed match reports for all formal competitions.

This is a read-only, targeted reread of the existing match_stats_cfg section in the
current save. It does not rerun the full exporter and never modifies the save. After writing
standard reports, it invokes the bundled field-enrichment step for conservative position
candidates, raw role-code provenance, rating-source statuses and unresolved signature sightings.

Scope for the current 2026/27 Manchester United save:
  formal competitions: 7 (league), 637 (continental), 661 and 662 (cups)
  excluded: 131 (pre-season / non-competitive)

Names are assigned through a persisted four-byte player-record signature map validated on the
same save, plus a strict same-match singleton residual only when the named active roster exactly
matches the anonymous active report rows. The signature is the first four bytes of the player
record, 100 bytes before the statistics anchor returned by fmsave._squads. All other rows stay unresolved.

A cached raw probe can be replayed with --reuse-probe. This repairs signatures and identities in
an existing player-report-probe.json without reopening the .fm save or rereading match_stats_cfg.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import subprocess
import traceback
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

try:
    import fmsave
    from fmsave._layouts import MatchReportLayout, find_layout
    from fmsave.readers.team_match_stats import (
        _decompress,
        _header,
        _read,
        _record_length,
        _squads,
        index_entries,
    )
except Exception as exc:  # pragma: no cover - depends on the user's pinned environment
    print("ERROR: cannot import the pinned fmsave package / match-report reader.", file=sys.stderr)
    print("Expected fmsave==0.12.4 in the exporter's Python environment.", file=sys.stderr)
    print(f"Import detail: {exc}", file=sys.stderr)
    raise SystemExit(2)

SUPPORTED_FMSAVE_VERSION = "0.12.4"
SECTION = "match_stats_cfg"
EXPECTED_BUILD = "27.0.1+2494687"
REFERENCE_BUILD = "27.0.0+2486695"
EXPECTED_SCHEMA = 6
TEAM_ID_DEFAULT = 539
# These are the four official competitions present in this specific season export.
FORMAL_COMPETITION_IDS = (7, 637, 661, 662)
EXCLUDED_NON_COMPETITIVE_IDS = (131,)
# fmsave._squads returns the player-statistics anchor, not the start of the player record.
# The 4-byte stable identity signature is at the beginning of that record (anchor - 100).
PLAYER_SIGNATURE_OFFSET_FROM_ANCHOR = -100
PLAYER_SIGNATURE_BYTES = 4
SIGNATURE_LAYOUT_NOTE = (
    "First four bytes of each player record; fmsave._squads statistics anchor minus 100 bytes."
)

# Independently verified fields inside the player record window (window starts at
# statistics_anchor - 100). These are not inferred from row order or season totals.
# Existing validation counts below record the tested baseline; entered_at_minute is
# additionally cross-checked dynamically against the named fmsave 0.12.4 history field.
RAW_PLAYER_FIELD_OFFSETS = {
    "goals": 20,
    "assists": 56,
    "left_at_minute": 67,
    "entered_at_minute": 71,
    "passes_attempted": 86,
    "passes_completed": 87,
}
# Match-report rating candidate: uint16 little-endian, hundredths, at anchor +36.
RAW_RATING_FIELD_OFFSET = 136  # raw window starts at statistics_anchor - 100
RAW_RATING_MIN_HUNDREDTHS = 400
RAW_RATING_MAX_HUNDREDTHS = 1000
MIN_RATING_CROSSCHECKS = 25
RAW_PLAYER_FIELD_VALIDATION = {
    "goals": {"matched": 320, "tested": 320},
    "assists": {"matched": 320, "tested": 320},
    "passes_attempted": {"matched": 320, "tested": 320},
    "passes_completed": {"matched": 320, "tested": 320},
    "left_at_minute": {"matched": 95, "tested": 95},
}
RAW_MINUTE_RULE = (
    "If left_at and entered_at are both nonzero, minutes=left_at-entered_at; "
    "if only left_at is nonzero, minutes=left_at; if only entered_at is nonzero, "
    "minutes=match_duration-entered_at; if both are zero, minutes=match_duration."
)

TEAM_SUM_FIELDS = (
    "shots", "shots_on_target", "blocked_shots", "shots_outside_box",
    "clear_cut_chances", "fouls_made", "offsides", "yellow_cards", "red_cards",
    "crosses_attempted", "crosses_completed", "tackles_attempted", "tackles_completed",
    "aerial_challenges_attempted", "headers_won", "expected_goals",
    "non_penalty_expected_goals", "distance_km", "progressive_passes",
)
PLAYER_HISTORY_FIELDS = (
    "player_uid", "player_name", "has_stats", "position_code", "minutes",
    "entered_at_minute", "left_at_minute", "goals", "assists", "rating",
    "passes_attempted", "passes_completed",
)
IDENTIFIED_FIELDS = [
    "date", "competition_id", "competition_name", "round", "kick_off_time", "home_away",
    "opponent_team_id", "opponent_name", "home_goals", "away_goals", "team_goals",
    "opponent_goals", "match_result", "player_uid", "player_name", "report_row_signature",
    "report_row_index", "identity_method", "identity_confidence", "named_history_available",
    "position_code", "minutes", "entered_at_minute", "left_at_minute", "rating",
    "rating_raw_hundredths", "rating_source", "goals", "assists",
    "passes_attempted", "passes_completed", *TEAM_SUM_FIELDS,
]
UNRESOLVED_FIELDS = [
    "date", "competition_id", "competition_name", "round", "kick_off_time", "home_away",
    "opponent_team_id", "opponent_name", "report_row_signature", "report_row_index", "reason",
    "position_code", "minutes", "entered_at_minute", "left_at_minute", "rating",
    "rating_raw_hundredths", "rating_source", "goals", "assists",
    "passes_attempted", "passes_completed",
    *TEAM_SUM_FIELDS,
]


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def write_json(path: Path, value: Any) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def write_csv(path: Path, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def as_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def player_record_signature(report: bytes, anchor: int) -> str:
    """Return the stable four-byte signature at the start of a player row.

    In the schema-6 match report, the fmsave player anchor is 100 bytes into
    the player record. Reading report[anchor:anchor+4] reads a row marker
    (often 07ffffff/06ffffff), not the player identity signature.
    """
    start = int(anchor) + PLAYER_SIGNATURE_OFFSET_FROM_ANCHOR
    end = start + PLAYER_SIGNATURE_BYTES
    if start < 0 or end > len(report):
        raise RuntimeError(
            f"Player signature falls outside the report: anchor={anchor}, start={start}, report_size={len(report)}"
        )
    signature = report[start:end]
    if len(signature) != PLAYER_SIGNATURE_BYTES:
        raise RuntimeError("Player signature is truncated")
    return signature.hex().lower()


def player_record_signature_from_probe_row(row: dict[str, Any]) -> str:
    """Recover the signature from a previously saved raw-window probe row."""
    anchor = as_int(row.get("anchor_offset"))
    raw_start = as_int(row.get("raw_window_start"))
    raw_hex = row.get("raw_window_hex")
    expected_start = anchor + PLAYER_SIGNATURE_OFFSET_FROM_ANCHOR if anchor is not None else None
    if anchor is None or raw_start != expected_start:
        raise RuntimeError(
            "Cached probe row does not contain the complete player-record prefix "
            f"(anchor={anchor}, raw_window_start={raw_start}, expected={expected_start})"
        )
    if not isinstance(raw_hex, str) or len(raw_hex) < PLAYER_SIGNATURE_BYTES * 2 or len(raw_hex) % 2:
        raise RuntimeError("Cached probe row has no complete raw player-record bytes")
    try:
        raw = bytes.fromhex(raw_hex)
    except ValueError as exc:
        raise RuntimeError(f"Cached probe row contains invalid raw hex: {exc}") from exc
    if len(raw) < PLAYER_SIGNATURE_BYTES:
        raise RuntimeError("Cached probe row is shorter than the four-byte signature")
    return raw[:PLAYER_SIGNATURE_BYTES].hex().lower()


def metric_values(report: bytes, anchor: int, detailed: bool, layout: Any) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for name, code, offset in layout.player_fields:
        value = _read(report, code, anchor + offset, layout)
        values[name] = round(float(value), 8) if code == "f" else int(value)
    code, offset = layout.distance_field
    distance = float(_read(report, code, anchor + offset, layout))
    values["distance_km"] = round(distance * (layout.detailed_distance_scale if detailed else 1.0), 8)
    code, offset = layout.progressive_passes_field
    values["progressive_passes"] = int(_read(report, code, anchor + offset, layout)) if detailed else None
    return values


def resolve_match_layout(info: Any) -> tuple[Any, dict[str, Any]]:
    schema = info.section_schemas.get(SECTION)
    if schema is None:
        raise RuntimeError(f"Save has no {SECTION!r} section")
    if (
        info.game == "FM27"
        and info.build == EXPECTED_BUILD
        and schema == EXPECTED_SCHEMA
        and not bool(getattr(info, "known_build", False))
    ):
        borrowed = find_layout(MatchReportLayout, SECTION, EXPECTED_SCHEMA, REFERENCE_BUILD)
        if not borrowed.exact:
            raise RuntimeError("Could not resolve the exact reference schema-6 layout for 27.0.0")
        return borrowed, {
            "layout_source_build": REFERENCE_BUILD,
            "layout_source_schema": EXPECTED_SCHEMA,
            "layout_exact_for_save_build": False,
            "layout_borrowed": True,
            "layout_note": "Uses the registered FM27 27.0.0 schema-6 layout for build 27.0.1+2494687; not upstream-verified for this build.",
        }
    match = find_layout(MatchReportLayout, SECTION, schema, info.build)
    if not match.exact:
        raise RuntimeError(
            f"No exact registered match-report layout for {info.game} {info.build} schema {schema}; refusing an unverified parse."
        )
    return match, {
        "layout_source_build": match.source_build,
        "layout_source_schema": match.source_schema,
        "layout_exact_for_save_build": True,
        "layout_borrowed": False,
        "layout_note": "Exact registered layout for this save build.",
    }


def load_formal_fixtures(export_dir: Path, team_id: int, comp_ids: set[int]) -> tuple[list[dict[str, Any]], dict[tuple[int, str, int, int], dict[str, Any]]]:
    fixtures = read_json(export_dir / "fixtures.json")
    selected: list[dict[str, Any]] = []
    index: dict[tuple[int, str, int, int], dict[str, Any]] = {}
    for row in fixtures:
        comp = as_int(row.get("competition_id"))
        home = as_int(row.get("home_team_id"))
        away = as_int(row.get("away_team_id"))
        if comp not in comp_ids or row.get("played") is not True or home is None or away is None:
            continue
        if team_id not in (home, away):
            continue
        key = (comp, str(row.get("date", "")), home, away)
        selected.append(row)
        index[key] = row
    selected.sort(key=lambda x: (str(x.get("date", "")), str(x.get("kick_off_time", "")), int(x.get("competition_id", 0))))
    return selected, index


def load_team_match_index(export_dir: Path, team_id: int) -> dict[tuple[int, int, int, str, str, int], dict[str, Any]]:
    rows = read_json(export_dir / "team-match-stats.json")
    result: dict[tuple[int, int, int, str, str, int], dict[str, Any]] = {}
    for row in rows:
        try:
            key = (
                int(row["competition_id"]), int(row["home_team_id"]), int(row["away_team_id"]),
                str(row["date"]), str(row["kick_off_time"]), int(row["team_id"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
        if key[-1] == team_id:
            result[key] = row
    return result


def load_roster_names(export_dir: Path, team_id: int) -> dict[int, str]:
    result: dict[int, str] = {}
    path = export_dir / "player-season-stats.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("team_id") != str(team_id) or row.get("kind") != "overall":
                continue
            uid = as_int(row.get("player_uid"))
            if uid is not None and row.get("player_name"):
                result[uid] = str(row["player_name"])
    return result


def load_candidates(export_dir: Path, comp_ids: set[int], roster_names: dict[int, str]) -> dict[tuple[int, str, int], list[dict[str, Any]]]:
    """Load same-match history, including historical guests only on actual appearances.

    Current first-team players retain the original behavior. A former/reserve/youth
    player is admitted only when this exact first-team match row contains real stats
    or positive minutes; inactive guest roster entries are excluded.
    """
    archive_path = export_dir / "player-match-stats-history-archive.json"
    path = archive_path if archive_path.is_file() else (export_dir / "player-match-stats.json")
    rows = read_json(path)
    result: dict[tuple[int, str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        try:
            uid = int(row["player_uid"])
            comp = int(row["competition_id"])
            date = str(row["date"])
            opponent = int(row["opponent_team_id"])
        except (KeyError, TypeError, ValueError):
            continue
        if comp not in comp_ids:
            continue
        is_current_first_team = uid in roster_names
        guest_has_appearance = (
            row.get("has_stats") is True
            or (as_int(row.get("minutes"), 0) or 0) > 0
        )
        if not is_current_first_team and not guest_has_appearance:
            continue
        player_name = roster_names.get(uid) or str(row.get("player_name") or "")
        if not player_name:
            continue
        candidate = {key: row.get(key) for key in PLAYER_HISTORY_FIELDS}
        candidate["player_uid"] = uid
        candidate["player_name"] = player_name
        result[(comp, date, opponent)].append(candidate)
    for values in result.values():
        values.sort(key=lambda x: (x.get("player_name") or "", int(x["player_uid"])))
    return result


def load_identity_cache(path: Path, team_id: int, roster_names: dict[int, str]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    """Load only trusted mappings; quarantine stale vector-only cache entries.

    A stale cache UID must not abort the entire report. When it is absent from the
    current first-team overall roster and has neither prior-validated nor guarded
    same-match evidence, its signature is removed from the active map. The normal
    strict same-match singleton reconciliation may still recover it; otherwise the
    affected rows remain explicitly unresolved.
    """
    cache = read_json(path)
    if cache.get("game") != "FM27":
        raise RuntimeError("Identity cache is not for FM27")

    # Seed caches are club-specific. The exporter resolves the managed first-team
    # team_id from the current save and passes it explicitly; never abort a valid
    # export or reuse another club's player signatures when the seed belongs elsewhere.
    cached_team_id = as_int(cache.get("team_id"))
    cached_competition_id = as_int(cache.get("competition_id"))
    if cached_team_id != team_id or cached_competition_id != 0:
        cache = {
            "cache_version": cache.get("cache_version", "1.1"),
            "game": "FM27",
            "team_id": team_id,
            "competition_id": 0,
            "scope": "formal cross-competition identity cache; isolated to the currently resolved managed first team",
            "seed_source": None,
            "mappings": {},
            "rejected_mappings": [],
            "cache_reset": {
                "reason": "seed_cache_scope_mismatch",
                "seed_team_id": cached_team_id,
                "requested_team_id": team_id,
                "seed_competition_id": cached_competition_id,
                "action": "discarded all seed mappings; rebuild identities only from this save's roster and guarded same-match evidence",
            },
        }
        print(
            "Identity cache scope mismatch: seed team_id=%s, current team_id=%s. "
            "Discarding foreign seed mappings and rebuilding safely."
            % (cached_team_id, team_id)
        )

    raw = cache.get("mappings")
    if not isinstance(raw, dict):
        raise RuntimeError("Identity cache mappings must be a JSON object")
    mappings: dict[str, dict[str, Any]] = {}
    uid_to_signature: dict[int, str] = {}
    rejected_mappings: list[dict[str, Any]] = []
    previous_rejections = cache.get("rejected_mappings")
    if isinstance(previous_rejections, list):
        rejected_mappings.extend(x for x in previous_rejections if isinstance(x, dict))
    for signature, entry in raw.items():
        sig = str(signature).lower()
        if not re.fullmatch(r"[0-9a-f]{8}", sig):
            raise RuntimeError(f"Invalid signature in identity cache: {signature!r}")
        if not isinstance(entry, dict):
            raise RuntimeError(f"Invalid cache record for signature {sig}")
        uid = as_int(entry.get("player_uid"))
        name = str(entry.get("player_name") or "")
        if uid is None:
            raise RuntimeError(f"Invalid cached player_uid for signature {sig}")
        if uid not in roster_names:
            # Guest identities may be absent from current first-team overall stats.
            # Permit only a prior-validated seed-cache class or a new guarded
            # singleton mapping with concrete same-match active-history evidence.
            evidence_rows = entry.get("derived_from_matches")
            guarded_singleton = (
                entry.get("evidence") == "single_remaining_same_match_named_history"
                and isinstance(evidence_rows, list)
                and bool(evidence_rows)
                and all(
                    as_int(item.get("player_uid")) == uid
                    and str(item.get("player_name") or "") == name
                    and item.get("same_match_history_has_stats") is True
                    and (as_int(item.get("same_match_minutes"), 0) or 0) > 0
                    and bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(item.get("date") or "")))
                    and as_int(item.get("competition_id")) in FORMAL_COMPETITION_IDS
                    and (as_int(item.get("opponent_team_id"), 0) or 0) > 0
                    and item.get("reason") == "unique_single_remaining_row_and_named_history_uid_after_complete_match_roster_reconciliation"
                    for item in evidence_rows
                )
            )
            if entry.get("evidence") != "prior_validated_signature_cache" and not guarded_singleton:
                rejected_mappings.append({
                    "signature": sig,
                    "player_uid": uid,
                    "player_name": name,
                    "cached_evidence": entry.get("evidence"),
                    "reason": "uid_absent_from_current_overall_stats_without_prior_or_guarded_same_match_validation",
                    "action": "quarantined; strict same-match singleton reconciliation may recover this signature",
                })
                continue
        elif roster_names[uid] != name:
            raise RuntimeError(
                f"Cached identity name mismatch for signature {sig}: cache={name!r}, current save={roster_names[uid]!r}"
            )
        previous_sig = uid_to_signature.get(uid)
        if previous_sig and previous_sig != sig:
            raise RuntimeError(f"Cache assigns two different signatures to player UID {uid}: {previous_sig} and {sig}")
        uid_to_signature[uid] = sig
        mappings[sig] = {**entry, "player_uid": uid, "player_name": name}
    # Do not retain quarantined entries under mappings: the singleton resolver must
    # see their signatures as unknown, and the learned cache must not re-poison them.
    cache = {
        **cache,
        "mappings": mappings,
        "rejected_mappings": rejected_mappings,
    }
    return mappings, cache

def is_appearance(metrics: dict[str, Any], history: dict[str, Any] | None) -> bool:
    if history and (history.get("has_stats") is True or (as_int(history.get("minutes"), 0) or 0) > 0):
        return True
    for key, value in metrics.items():
        if isinstance(value, (int, float)) and abs(float(value)) > 1e-8:
            return True
    return False


def make_match_context(report: dict[str, Any], fixture: dict[str, Any]) -> dict[str, Any]:
    is_home = report["is_home"]
    if is_home:
        opponent_id = fixture.get("away_team_id")
        opponent_name = fixture.get("away_club_short_name") or fixture.get("away_club_name")
        team_goals, opponent_goals = fixture.get("home_goals"), fixture.get("away_goals")
    else:
        opponent_id = fixture.get("home_team_id")
        opponent_name = fixture.get("home_club_short_name") or fixture.get("home_club_name")
        team_goals, opponent_goals = fixture.get("away_goals"), fixture.get("home_goals")
    if team_goals is None or opponent_goals is None:
        outcome = "unknown"
    elif int(team_goals) > int(opponent_goals):
        outcome = "W"
    elif int(team_goals) < int(opponent_goals):
        outcome = "L"
    else:
        outcome = "D"
    return {
        "competition_name": fixture.get("competition_name"),
        "round": fixture.get("round"),
        "home_away": "主场" if is_home else "客场",
        "opponent_team_id": opponent_id,
        "opponent_name": opponent_name,
        "home_goals": fixture.get("home_goals"),
        "away_goals": fixture.get("away_goals"),
        "team_goals": team_goals,
        "opponent_goals": opponent_goals,
        "match_result": outcome,
    }


def rating_from_raw_stats(raw_stats: dict[str, Any] | None) -> float | None:
    """Convert a cross-validated raw rating (hundredths) to the game's one-decimal display."""
    if not raw_stats:
        return None
    hundredths = as_int(raw_stats.get("rating_hundredths"))
    if hundredths is None or not RAW_RATING_MIN_HUNDREDTHS <= hundredths <= RAW_RATING_MAX_HUNDREDTHS:
        return None
    return ((hundredths + 5) // 10) / 10  # explicit half-up rounding


def decode_raw_player_stats(raw_window: bytes) -> dict[str, int] | None:
    """Decode verified basic fields plus a raw match-report rating candidate.

    The window starts at statistics_anchor - 100. The rating is an unsigned
    16-bit little-endian integer at window +136 (statistics_anchor +36), stored
    in hundredths. It is only used after named-history cross-validation.
    """
    required = max(RAW_PLAYER_FIELD_OFFSETS.values()) + 1
    if len(raw_window) < required:
        return None
    values = {name: int(raw_window[offset]) for name, offset in RAW_PLAYER_FIELD_OFFSETS.items()}
    rating_end = RAW_RATING_FIELD_OFFSET + 2
    if len(raw_window) >= rating_end:
        candidate = int.from_bytes(
            raw_window[RAW_RATING_FIELD_OFFSET:rating_end], byteorder="little", signed=False
        )
        if RAW_RATING_MIN_HUNDREDTHS <= candidate <= RAW_RATING_MAX_HUNDREDTHS:
            values["rating_hundredths"] = candidate
    return values


def raw_stats_from_probe_row(row: dict[str, Any]) -> dict[str, int] | None:
    """Read stored stats and backfill the new rating from retained raw-window hex."""
    stored = row.get("raw_player_stats")
    stored_values: dict[str, int] | None = None
    if isinstance(stored, dict):
        try:
            if all(as_int(stored.get(name)) is not None for name in RAW_PLAYER_FIELD_OFFSETS):
                stored_values = {name: int(stored[name]) for name in RAW_PLAYER_FIELD_OFFSETS}
                stored_rating = as_int(stored.get("rating_hundredths"))
                if stored_rating is not None:
                    stored_values["rating_hundredths"] = stored_rating
        except (TypeError, ValueError):
            stored_values = None
    raw_hex = row.get("raw_window_hex")
    if not isinstance(raw_hex, str) or len(raw_hex) % 2:
        return stored_values
    try:
        raw_window = bytes.fromhex(raw_hex)
    except ValueError:
        return stored_values
    decoded = decode_raw_player_stats(raw_window)
    if decoded is None:
        return stored_values
    if stored_values is None:
        return decoded
    if "rating_hundredths" in decoded:
        stored_values["rating_hundredths"] = decoded["rating_hundredths"]
    return stored_values

def decode_minutes_from_raw(raw_stats: dict[str, int] | None, match_duration: int | None) -> int | None:
    """Calculate minutes from the stored entry/exit clocks once match duration is known."""
    if not raw_stats or match_duration is None:
        return None
    left_at = int(raw_stats["left_at_minute"])
    entered_at = int(raw_stats["entered_at_minute"])
    if left_at > 0 and entered_at > 0:
        value = left_at - entered_at
    elif left_at > 0:
        value = left_at
    elif entered_at > 0:
        value = int(match_duration) - entered_at
    else:
        value = int(match_duration)
    return value if 0 <= value <= int(match_duration) else None


def load_season_aggregate_rows(export_dir: Path, team_id: int) -> dict[str, dict[int, dict[str, int]]]:
    """Load first-team category aggregates used only to validate/infer fixture duration.

    No individual match value is copied from these aggregates. They are used as an
    independent sum check against raw per-match records.
    """
    fields = ("minutes", "goals", "assists", "passes_attempted", "passes_completed")
    result: dict[str, dict[int, dict[str, int]]] = defaultdict(dict)
    path = export_dir / "player-season-stats.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if as_int(row.get("team_id")) != team_id:
                continue
            kind = str(row.get("kind") or "")
            uid = as_int(row.get("player_uid"))
            if kind not in ("league", "continental", "cup") or uid is None:
                continue
            values: dict[str, int] = {}
            for field in fields:
                value = as_int(row.get(field))
                if value is not None:
                    values[field] = value
            result[kind][uid] = values
    return result


def _raw_rows_by_uid(
    reports: list[dict[str, Any]], signature_map: dict[str, dict[str, Any]]
) -> dict[tuple[int, str, int], list[tuple[int, dict[str, int]]]]:
    """Collect identified actual-appearance rows for category aggregate reconciliation."""
    collected: dict[tuple[int, str, int], list[tuple[int, dict[str, int]]]] = defaultdict(list)
    for report in reports:
        key = (int(report["competition_id"]), str(report["date"]), int(report["opponent_team_id"]))
        history_by_uid: dict[int, dict[str, Any]] = {}
        for item in report.get("candidate_player_history_rows", []):
            uid = as_int(item.get("player_uid"))
            if uid is not None:
                prior = history_by_uid.get(uid)
                if prior is None or (item.get("has_stats") is True and prior.get("has_stats") is not True):
                    history_by_uid[uid] = item
        for row in report.get("anonymous_player_rows", []):
            signature = str(row.get("row_signature") or "").lower()
            mapping = signature_map.get(signature)
            if not mapping:
                continue
            uid = as_int(mapping.get("player_uid"))
            if uid is None:
                continue
            history = history_by_uid.get(uid)
            if not is_appearance(row.get("metrics") or {}, history):
                continue
            raw_stats = raw_stats_from_probe_row(row)
            if raw_stats is None:
                continue
            collected[key].append((uid, raw_stats))
    return collected


def _category_aggregate_score(
    category: str,
    comp_ids: set[int],
    reports: list[dict[str, Any]],
    signature_map: dict[str, dict[str, Any]],
    season_aggregates: dict[str, dict[int, dict[str, int]]],
    durations: dict[tuple[int, str, int], dict[str, Any]],
) -> tuple[int, int, int]:
    """Return (exact fields, compared fields, absolute error) for one duration map."""
    targets = season_aggregates.get(category, {})
    raw_rows = _raw_rows_by_uid(reports, signature_map)
    totals: dict[int, Counter[str]] = defaultdict(Counter)
    for key, entries in raw_rows.items():
        comp, _date, _opponent = key
        if comp not in comp_ids:
            continue
        duration = as_int((durations.get(key) or {}).get("minutes_played"))
        for uid, raw_stats in entries:
            minutes = decode_minutes_from_raw(raw_stats, duration)
            if minutes is not None:
                totals[uid]["minutes"] += minutes
            for field in ("goals", "assists", "passes_attempted", "passes_completed"):
                totals[uid][field] += int(raw_stats[field])
    exact = compared = absolute_error = 0
    for uid, values in targets.items():
        if uid not in totals:
            continue
        for field, expected in values.items():
            actual = int(totals[uid][field])
            compared += 1
            delta = abs(actual - int(expected))
            absolute_error += delta
            if delta == 0:
                exact += 1
    return exact, compared, absolute_error


def infer_match_durations(
    reports: list[dict[str, Any]],
    signature_map: dict[str, dict[str, Any]],
    season_aggregates: dict[str, dict[int, dict[str, int]]],
) -> tuple[dict[tuple[int, str, int], dict[str, Any]], dict[str, Any]]:
    """Infer match duration from named same-match history, then validate against season sums.

    The solver never copies aggregate values into individual match rows. It tests only
    90- and 120-minute fixture durations, and accepts an aggregate solution only when
    exactly one assignment reconciles all compared first-team season fields.
    """
    durations: dict[tuple[int, str, int], dict[str, Any]] = {}
    votes: dict[tuple[int, str, int], list[int]] = defaultdict(list)
    for report in reports:
        key = (int(report["competition_id"]), str(report["date"]), int(report["opponent_team_id"]))
        history_by_uid: dict[int, dict[str, Any]] = {}
        for item in report.get("candidate_player_history_rows", []):
            uid = as_int(item.get("player_uid"))
            if uid is not None:
                current = history_by_uid.get(uid)
                if current is None or (item.get("has_stats") is True and current.get("has_stats") is not True):
                    history_by_uid[uid] = item
        for row in report.get("anonymous_player_rows", []):
            mapping = signature_map.get(str(row.get("row_signature") or "").lower())
            if not mapping:
                continue
            uid = as_int(mapping.get("player_uid"))
            history = history_by_uid.get(uid) if uid is not None else None
            if not history or history.get("has_stats") is not True:
                continue
            history_minutes = as_int(history.get("minutes"))
            if history_minutes is None:
                continue
            raw_stats = raw_stats_from_probe_row(row)
            if raw_stats is None:
                continue
            left_at = raw_stats["left_at_minute"]
            entered_at = raw_stats["entered_at_minute"]
            # Only a row with no recorded exit gives an unambiguous full-time duration:
            # named minutes + the known entry clock. A player substituted at 90 is NOT
            # evidence that the match ended at 90; extra time may still follow.
            candidate_duration = None
            if left_at == 0:
                candidate_duration = history_minutes + entered_at
            if candidate_duration in (90, 120):
                votes[key].append(int(candidate_duration))

    for key, values in votes.items():
        unique = sorted(set(values))
        if len(unique) == 1:
            durations[key] = {
                "minutes_played": unique[0],
                "source": "same_match_named_history_full_time_votes",
                "vote_count": len(values),
            }

    # Cup totals provide a strong independent check for fixtures missing from the
    # rolling named-history window. Current first-team cup category combines IDs 661/662.
    raw_rows = _raw_rows_by_uid(reports, signature_map)
    category_specs = (
        ("cup", {661, 662}),
        ("continental", {637}),
    )
    aggregate_solver_audit: dict[str, Any] = {}
    for category, comp_ids in category_specs:
        category_keys = sorted({key for key in raw_rows if key[0] in comp_ids})
        unknown_keys = [key for key in category_keys if key not in durations]
        if not unknown_keys or len(unknown_keys) > 14 or not season_aggregates.get(category):
            aggregate_solver_audit[category] = {
                "unknown_fixtures": len(unknown_keys),
                "status": "not_attempted" if unknown_keys else "all_durations_from_history",
            }
            continue
        candidates: list[tuple[int, int, int, dict[tuple[int, str, int], int]]] = []
        # Enumerate only the duration unknowns, not player identities or statistics.
        for mask in range(1 << len(unknown_keys)):
            trial = dict(durations)
            assignment: dict[tuple[int, str, int], int] = {}
            for index, key in enumerate(unknown_keys):
                minute_value = 120 if (mask >> index) & 1 else 90
                assignment[key] = minute_value
                trial[key] = {"minutes_played": minute_value, "source": "aggregate_solver_candidate", "vote_count": 0}
            exact, compared, error = _category_aggregate_score(
                category, comp_ids, reports, signature_map, season_aggregates, trial
            )
            candidates.append((exact, compared, error, assignment))
        perfect = [x for x in candidates if x[1] > 0 and x[0] == x[1] and x[2] == 0]
        if len(perfect) == 1:
            assignment = perfect[0][3]
            for key, value in assignment.items():
                durations[key] = {
                    "minutes_played": value,
                    "source": "unique_exact_season_category_reconciliation",
                    "vote_count": 0,
                }
            aggregate_solver_audit[category] = {
                "unknown_fixtures": len(unknown_keys),
                "status": "unique_exact_solution",
                "compared_fields": perfect[0][1],
                "reconciled_fields": perfect[0][0],
                "absolute_error": perfect[0][2],
                "assigned_durations": {"|".join(map(str, key)): value for key, value in assignment.items()},
            }
        else:
            best = sorted(candidates, key=lambda x: (-x[0], x[2]))[0]
            aggregate_solver_audit[category] = {
                "unknown_fixtures": len(unknown_keys),
                "status": "no_unique_exact_solution",
                "best_reconciled_fields": best[0],
                "best_compared_fields": best[1],
                "best_absolute_error": best[2],
            }

    # League fixtures are regular 90-minute fixtures. For continental fixtures without
    # a named-history vote, only non-knockout stages receive the 90-minute default.
    for report in reports:
        key = (int(report["competition_id"]), str(report["date"]), int(report["opponent_team_id"]))
        if key in durations:
            continue
        comp = int(report["competition_id"])
        round_name = str(report.get("round") or "").lower()
        if comp == 7:
            durations[key] = {"minutes_played": 90, "source": "league_regulation_time", "vote_count": 0}
        elif comp == 637 and round_name not in {"final", "semi_final", "quarter_final"}:
            durations[key] = {"minutes_played": 90, "source": "continental_non_knockout_regulation_time", "vote_count": 0}

    audit = {
        "match_duration_minutes": {"|".join(map(str, key)): value for key, value in durations.items()},
        "history_vote_fixture_count": len(votes),
        "history_vote_conflicts": {
            "|".join(map(str, key)): sorted(set(values)) for key, values in votes.items() if len(set(values)) > 1
        },
        "aggregate_solver": aggregate_solver_audit,
        "unresolved_duration_fixtures": [
            "|".join(map(str, key)) for key in sorted(raw_rows) if key not in durations
        ],
    }
    return durations, audit


def audit_raw_history_crosschecks(
    reports: list[dict[str, Any]],
    signature_map: dict[str, dict[str, Any]],
    duration_map: dict[tuple[int, str, int], dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """Count direct raw-vs-named-history comparisons without filling missing values."""
    fields = ("goals", "assists", "passes_attempted", "passes_completed", "entered_at_minute", "left_at_minute", "minutes", "rating")
    result = {field: {"matched": 0, "tested": 0, "mismatches": 0} for field in fields}
    for report in reports:
        key = (int(report["competition_id"]), str(report["date"]), int(report["opponent_team_id"]))
        duration_info = duration_map.get(key)
        duration = as_int(duration_info.get("minutes_played")) if duration_info else None
        history_by_uid: dict[int, dict[str, Any]] = {}
        for history in report.get("candidate_player_history_rows", []):
            uid = as_int(history.get("player_uid"))
            if uid is not None:
                prior = history_by_uid.get(uid)
                if prior is None or (history.get("has_stats") is True and prior.get("has_stats") is not True):
                    history_by_uid[uid] = history
        for row in report.get("anonymous_player_rows", []):
            mapping = signature_map.get(str(row.get("row_signature") or "").lower())
            if not mapping:
                continue
            uid = as_int(mapping.get("player_uid"))
            history = history_by_uid.get(uid) if uid is not None else None
            if not history or history.get("has_stats") is not True:
                continue
            raw_stats = raw_stats_from_probe_row(row)
            if raw_stats is None:
                continue
            raw_values: dict[str, Any] = {
                "goals": raw_stats["goals"],
                "assists": raw_stats["assists"],
                "passes_attempted": raw_stats["passes_attempted"],
                "passes_completed": raw_stats["passes_completed"],
                "entered_at_minute": raw_stats["entered_at_minute"] if raw_stats["entered_at_minute"] > 0 else None,
                "left_at_minute": raw_stats["left_at_minute"] if raw_stats["left_at_minute"] > 0 else None,
                "minutes": decode_minutes_from_raw(raw_stats, duration),
                "rating": rating_from_raw_stats(raw_stats),
            }
            for field in fields:
                expected = history.get(field)
                actual = raw_values[field]
                if expected is None or actual is None:
                    continue
                if field == "rating":
                    try:
                        expected_value = float(expected)
                        actual_value = float(actual)
                    except (TypeError, ValueError):
                        continue
                    result[field]["tested"] += 1
                    if math.isclose(expected_value, actual_value, abs_tol=1e-9):
                        result[field]["matched"] += 1
                    else:
                        result[field]["mismatches"] += 1
                    continue
                expected_int = as_int(expected)
                actual_int = as_int(actual)
                if expected_int is None or actual_int is None:
                    continue
                result[field]["tested"] += 1
                if expected_int == actual_int:
                    result[field]["matched"] += 1
                else:
                    result[field]["mismatches"] += 1
    return result


def infer_singleton_signature_mappings(
    reports: list[dict[str, Any]],
    base_map: dict[str, dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Infer only a one-row/one-UID residual when same-match history is complete.

    A fixture is eligible only when the number of active named-history UIDs equals
    the active anonymous report rows, every already-cached active row is confirmed
    by that same-match history, and exactly one unknown row remains for exactly one
    unused named-history UID. All other cases stay unresolved.
    """
    evidence_by_signature: dict[str, list[dict[str, Any]]] = defaultdict(list)
    rejected: list[dict[str, Any]] = []
    for report in reports:
        history_rows = report.get("candidate_player_history_rows", [])
        active_uids: dict[int, dict[str, Any]] = {}
        history_by_uid: dict[int, dict[str, Any]] = {}
        for history in history_rows:
            uid = as_int(history.get("player_uid"))
            if uid is None:
                continue
            prior = history_by_uid.get(uid)
            if prior is None or (history.get("has_stats") is True and prior.get("has_stats") is not True):
                history_by_uid[uid] = history
            minutes = as_int(history.get("minutes"), 0) or 0
            if history.get("has_stats") is True or minutes > 0:
                active_uids[uid] = history
        if not active_uids:
            continue

        active_rows: list[dict[str, Any]] = []
        for row in report.get("anonymous_player_rows", []):
            sig = str(row.get("row_signature", "")).lower()
            mapping = base_map.get(sig)
            history = history_by_uid.get(int(mapping["player_uid"])) if mapping else None
            if is_appearance(row.get("metrics", {}), history):
                active_rows.append(row)
        if len(active_rows) != len(active_uids):
            continue

        cached_rows = [row for row in active_rows if str(row.get("row_signature", "")).lower() in base_map]
        cached_uids: list[int] = []
        cache_conflict = False
        for row in cached_rows:
            sig = str(row.get("row_signature", "")).lower()
            mapping = base_map[sig]
            uid = int(mapping["player_uid"])
            hist = history_by_uid.get(uid)
            if uid not in active_uids:
                cache_conflict = True
                break
            if hist is not None and hist.get("has_stats") is False and (as_int(hist.get("minutes"), 0) or 0) <= 0:
                cache_conflict = True
                break
            cached_uids.append(uid)
        if cache_conflict or len(cached_uids) != len(set(cached_uids)):
            continue

        unknown_rows = [row for row in active_rows if str(row.get("row_signature", "")).lower() not in base_map]
        unused_uids = sorted(set(active_uids) - set(cached_uids))
        if len(unknown_rows) == 1 and len(unused_uids) == 1:
            row = unknown_rows[0]
            sig = str(row.get("row_signature", "")).lower()
            uid = unused_uids[0]
            history = active_uids[uid]
            evidence_by_signature[sig].append({
                "player_uid": uid,
                "player_name": str(history.get("player_name") or ""),
                "competition_id": int(report["competition_id"]),
                "date": str(report["date"]),
                "opponent_team_id": int(report["opponent_team_id"]),
                "same_match_history_has_stats": history.get("has_stats") is True,
                "same_match_minutes": history.get("minutes"),
                "reason": "unique_single_remaining_row_and_named_history_uid_after_complete_match_roster_reconciliation",
            })

    inferred: dict[str, dict[str, Any]] = {}
    for sig, occurrences in evidence_by_signature.items():
        ids = {(int(x["player_uid"]), str(x["player_name"])) for x in occurrences}
        if len(ids) == 1 and next(iter(ids))[1]:
            uid, name = next(iter(ids))
            inferred[sig] = {
                "player_uid": uid,
                "player_name": name,
                "evidence": "single_remaining_same_match_named_history",
                "confidence": "high",
                "seed_competition_id": None,
                "derived_from_matches": occurrences,
            }
        elif len(ids) > 1:
            rejected.append({"signature": sig, "conflicting_assignments": sorted([{"player_uid": x[0], "player_name": x[1]} for x in ids]), "occurrences": occurrences})
    return inferred, [item for group in evidence_by_signature.values() for item in group], rejected


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("save", type=Path, help="Path to the current FM27 .fm save")
    parser.add_argument("export_dir", type=Path, help="Existing FM27 first-team export folder")
    parser.add_argument("--cache-file", type=Path, required=True, help="Formal cross-competition identity cache JSON")
    parser.add_argument("--team-id", type=int, default=TEAM_ID_DEFAULT)
    parser.add_argument("--competition-id", type=int, default=0,
                        help="0 = the four formal competitions in this season; never includes pre-season 131")
    parser.add_argument("--no-raw", action="store_true", help="Do not retain raw match-report byte windows in the probe JSON")
    parser.add_argument(
        "--reuse-probe", action="store_true",
        help="Repair identities from an existing player-report-probe.json; do not reopen the .fm save.",
    )
    args = parser.parse_args()

    if str(getattr(fmsave, "__version__", "unknown")) != SUPPORTED_FMSAVE_VERSION:
        raise RuntimeError(
            f"This helper requires fmsave=={SUPPORTED_FMSAVE_VERSION}; found {getattr(fmsave, '__version__', 'unknown')}"
        )
    save_path = args.save.expanduser().resolve()
    export_dir = args.export_dir.expanduser().resolve()
    cache_path = args.cache_file.expanduser().resolve()
    if not args.reuse_probe and not save_path.is_file():
        raise RuntimeError(f"FM27 save not found: {save_path}")
    if not cache_path.is_file():
        raise RuntimeError(f"Formal identity cache not found: {cache_path}")
    for required in ("fixtures.json", "player-match-stats.json", "player-season-stats.csv", "team-match-stats.json"):
        if not (export_dir / required).is_file():
            raise RuntimeError(f"Missing required existing export file: {export_dir / required}")
    if args.competition_id not in (0, *FORMAL_COMPETITION_IDS):
        raise RuntimeError(f"Unsupported competition id {args.competition_id}; use 0 or one of {FORMAL_COMPETITION_IDS}")
    comp_ids = set(FORMAL_COMPETITION_IDS if args.competition_id == 0 else (args.competition_id,))

    fixtures, fixture_index = load_formal_fixtures(export_dir, args.team_id, comp_ids)
    if not fixtures:
        raise RuntimeError("No played first-team formal fixtures were found in fixtures.json")
    roster_names = load_roster_names(export_dir, args.team_id)
    if not roster_names:
        raise RuntimeError("No first-team overall season-stat rows were found for the requested team")
    candidates = load_candidates(export_dir, comp_ids, roster_names)
    season_aggregates = load_season_aggregate_rows(export_dir, args.team_id)
    history_source = "player-match-stats-history-archive.json" if (export_dir / "player-match-stats-history-archive.json").is_file() else "player-match-stats.json"
    team_index = load_team_match_index(export_dir, args.team_id)
    signature_map, cache = load_identity_cache(cache_path, args.team_id, roster_names)
    rejected_cache_mappings = cache.get("rejected_mappings", [])
    rejected_cache_signatures = {str(x.get("signature", "")).lower() for x in rejected_cache_mappings if isinstance(x, dict)}
    if rejected_cache_mappings:
        print(f"Identity cache quarantined {len(rejected_cache_mappings)} stale mapping(s); only strict same-match reconciliation may restore them.")

    reports: list[dict[str, Any]] = []
    layout_meta: dict[str, Any] = {}
    source_meta: dict[str, Any] = {}

    if args.reuse_probe:
        probe_path = export_dir / "player-report-probe.json"
        if not probe_path.is_file():
            raise RuntimeError(f"--reuse-probe requested but raw probe is missing: {probe_path}")
        cached_probe = read_json(probe_path)
        cached_source = cached_probe.get("source") or {}
        if cached_source.get("game") != "FM27":
            raise RuntimeError("Cached probe is not from an FM27 save")
        if as_int(cached_source.get("team_id")) != args.team_id:
            raise RuntimeError("Cached probe team_id does not match the requested first team")
        if cached_source.get("section") != SECTION or as_int(cached_source.get("section_schema")) != EXPECTED_SCHEMA:
            raise RuntimeError("Cached probe does not contain the expected match_stats_cfg schema-6 source")
        if set(as_int(x) for x in cached_source.get("formal_competition_ids", [])) != comp_ids:
            raise RuntimeError("Cached probe formal competition scope does not match this run")
        if cached_source.get("save_file") and cached_source.get("save_file") != save_path.name:
            raise RuntimeError(
                f"Cached probe came from {cached_source.get('save_file')!r}, but SavePath names {save_path.name!r}"
            )
        save_info_path = export_dir / "save-info.json"
        if save_info_path.is_file():
            saved_info = read_json(save_info_path)
            if saved_info.get("game") != cached_source.get("game") or saved_info.get("build") != cached_source.get("game_build"):
                raise RuntimeError("Cached probe game/build does not match save-info.json in this export folder")
        reports = cached_probe.get("reports") or []
        if not isinstance(reports, list) or not reports:
            raise RuntimeError("Cached probe contains no detailed match reports")
        # Validate every fixture and restore the signature from the original raw record
        # prefix. The old v1.4 output stored the wrong bytes in row_signature, but retained
        # the correct raw_window_hex starting at anchor-100.
        seen_keys: set[tuple[int, str, int, int]] = set()
        for report in reports:
            comp = as_int(report.get("competition_id"))
            home = as_int(report.get("home_team_id"))
            away = as_int(report.get("away_team_id"))
            date_text = str(report.get("date", ""))
            if comp not in comp_ids or home is None or away is None or args.team_id not in (home, away):
                raise RuntimeError("Cached probe contains an out-of-scope match report")
            key = (comp, date_text, home, away)
            if key not in fixture_index or key in seen_keys:
                raise RuntimeError(f"Cached probe contains an unexpected or duplicate fixture report: {key}")
            seen_keys.add(key)
            # Refresh same-match named histories from player-match-stats.json.
            # This admits historical guests only on exact rows where they appeared,
            # while preventing stale candidate lists from older probe versions.
            report["candidate_player_history_rows"] = candidates.get(
                (comp, date_text, int(report.get("opponent_team_id"))), []
            )
            rows = report.get("anonymous_player_rows") or []
            for row in rows:
                row["row_signature"] = player_record_signature_from_probe_row(row)
                row["signature_offset_from_anchor"] = PLAYER_SIGNATURE_OFFSET_FROM_ANCHOR
                # v1.3 probes already retain the complete variable-length player record.
                # Older probes with a shorter window still contain all verified raw fields.
                raw_stats = raw_stats_from_probe_row(row)
                if raw_stats is not None:
                    row["raw_player_stats"] = raw_stats
        layout_meta = {
            key: cached_source.get(key)
            for key in (
                "layout_source_build", "layout_source_schema", "layout_exact_for_save_build",
                "layout_borrowed", "layout_note",
            )
        }
        source_meta = dict(cached_source)
        source_meta["signature_layout"] = {
            "bytes": PLAYER_SIGNATURE_BYTES,
            "offset_from_statistics_anchor": PLAYER_SIGNATURE_OFFSET_FROM_ANCHOR,
            "description": SIGNATURE_LAYOUT_NOTE,
            "corrected_from_cached_raw_window": True,
        }
        print("REUSE_PROBE: restored player signatures from the cached raw windows; the .fm save was not opened or reread.")
    else:
        from fmsave.readers._common import MATCH_REPORTS_SECTION
        save = fmsave.open(str(save_path))
        try:
            info = save.info
            if info.game != "FM27":
                raise RuntimeError(f"Expected FM27 save, got {info.game!r}")
            match, layout_meta = resolve_match_layout(info)
            layout = match.layout
            seed_pattern = re.compile(b"(?=" + re.escape(layout.anchor_run) + b")")
            with save._context.section(SECTION) as section:  # fmsave 0.12.4 private section accessor
                # fmsave==0.12.4 exposes index_entries(section, layout, file_name).
                # Do not pass check_borrowed: that keyword belongs to a later API.
                entries = index_entries(section, layout, info.file_name)
                view = memoryview(section)
                for start, size in entries:
                    raw_report = _decompress(view[start:start + size], layout)
                    if raw_report is None:
                        continue
                    header = _header(raw_report, layout)
                    if header is None:
                        continue
                    comp = int(header.competition_id)
                    if comp not in comp_ids:
                        continue
                    if args.team_id not in (header.home_team_id, header.away_team_id):
                        continue
                    is_home = args.team_id == header.home_team_id
                    home_id, away_id = int(header.home_team_id), int(header.away_team_id)
                    date_text = header.kick_off.date().isoformat()
                    fixture = fixture_index.get((comp, date_text, home_id, away_id))
                    if fixture is None:
                        # Do not silently add friendlies, unplayed records, or another team’s report.
                        continue
                    squads = _squads(raw_report, layout, seed_pattern)
                    if squads is None:
                        continue
                    anchors = squads.home if is_home else squads.away
                    opponent_id = away_id if is_home else home_id
                    kick_time = header.kick_off.time().isoformat()
                    team_key = (comp, home_id, away_id, date_text, kick_time, args.team_id)
                    expected = team_index.get(team_key)
                    history_rows = candidates.get((comp, date_text, opponent_id), [])
                    history_by_uid: dict[int, dict[str, Any]] = {}
                    for candidate in history_rows:
                        uid = as_int(candidate.get("player_uid"))
                        if uid is None:
                            continue
                        current = history_by_uid.get(uid)
                        if current is None or (candidate.get("has_stats") is True and current.get("has_stats") is not True):
                            history_by_uid[uid] = candidate

                    player_rows: list[dict[str, Any]] = []
                    sums: dict[str, float] = {}
                    for row_index, anchor in enumerate(anchors, start=1):
                        metrics = metric_values(raw_report, anchor, squads.detailed, layout)
                        for name, value in metrics.items():
                            if isinstance(value, (int, float)):
                                sums[name] = sums.get(name, 0.0) + float(value)
                        record_length = _record_length(raw_report, anchor, layout)
                        signature = player_record_signature(raw_report, anchor)
                        row = {
                            "row_index": row_index,
                            "anchor_offset": anchor,
                            "record_length": record_length,
                            "row_signature": signature,
                            "signature_offset_from_anchor": PLAYER_SIGNATURE_OFFSET_FROM_ANCHOR,
                            "metrics": metrics,
                        }
                        if not args.no_raw and record_length is not None:
                            lo = anchor + PLAYER_SIGNATURE_OFFSET_FROM_ANCHOR
                            hi = min(len(raw_report), anchor + record_length)
                            if lo < 0:
                                raise RuntimeError(f"Player record prefix precedes report start: anchor={anchor}")
                            row["raw_window_start"] = lo
                            raw_window = raw_report[lo:hi]
                            row["raw_window_hex"] = raw_window.hex()
                            row["raw_player_stats"] = decode_raw_player_stats(raw_window)
                        elif record_length is not None:
                            # Structured raw values are retained even when the user opts
                            # out of preserving raw hex in the diagnostic probe.
                            lo = anchor + PLAYER_SIGNATURE_OFFSET_FROM_ANCHOR
                            hi = min(len(raw_report), anchor + record_length)
                            if lo < 0:
                                raise RuntimeError(f"Player record prefix precedes report start: anchor={anchor}")
                            row["raw_player_stats"] = decode_raw_player_stats(raw_report[lo:hi])
                        player_rows.append(row)

                    check: dict[str, Any] = {}
                    for name in TEAM_SUM_FIELDS:
                        got = sums.get(name)
                        exp = expected.get(name) if expected else None
                        if expected is None or got is None or exp is None:
                            result = None
                        elif isinstance(exp, (int, float)):
                            tolerance = 0.015 if isinstance(exp, float) else 0.0
                            result = abs(float(got) - float(exp)) <= tolerance
                        else:
                            result = None
                        check[name] = {
                            "per_player_sum": round(got, 8) if got is not None else None,
                            "exported_team_total": exp,
                            "match": result,
                        }
                    report = {
                        "competition_id": comp,
                        "competition_name": fixture.get("competition_name"),
                        "round": fixture.get("round"),
                        "home_team_id": home_id,
                        "away_team_id": away_id,
                        "home_team_name": fixture.get("home_club_short_name") or fixture.get("home_club_name"),
                        "away_team_name": fixture.get("away_club_short_name") or fixture.get("away_club_name"),
                        "date": date_text,
                        "kick_off_time": kick_time,
                        "team_id": args.team_id,
                        "opponent_team_id": opponent_id,
                        "is_home": is_home,
                        "detailed_report": bool(squads.detailed),
                        "matchday_player_record_count": len(anchors),
                        "anonymous_player_rows": player_rows,
                        "candidate_player_history_rows": history_rows,
                        "team_total_check": check,
                    }
                    reports.append(report)
        finally:
            save.close()
        source_meta = {
            "save_file": save_path.name,
            "fmsave_version": getattr(fmsave, "__version__", "unknown"),
            "game": "FM27",
            "game_build": getattr(info, "build", None),
            "known_build": getattr(info, "known_build", None),
            "section": SECTION,
            "section_schema": info.section_schemas.get(SECTION),
            "team_id": args.team_id,
            "competition_id_filter": 0 if args.competition_id == 0 else args.competition_id,
            "formal_competition_ids": sorted(comp_ids),
            "excluded_non_competitive_ids": list(EXCLUDED_NON_COMPETITIVE_IDS),
            **layout_meta,
            "signature_layout": {
                "bytes": PLAYER_SIGNATURE_BYTES,
                "offset_from_statistics_anchor": PLAYER_SIGNATURE_OFFSET_FROM_ANCHOR,
                "description": SIGNATURE_LAYOUT_NOTE,
                "corrected_from_cached_raw_window": False,
            },
        }


    # Try only the strict one-remaining-row / one-remaining-UID case from complete
    # same-match player history. This can recover a player such as a cup-only keeper
    # without guessing from row order or position.
    inferred_map, inferred_evidence, rejected_inference = infer_singleton_signature_mappings(reports, signature_map)
    for sig, entry in inferred_map.items():
        if sig in signature_map:
            continue
        if any(int(existing["player_uid"]) == int(entry["player_uid"]) for existing in signature_map.values()):
            rejected_inference.append({"signature": sig, "reason": "player_uid_already_has_a_different_cached_signature", "player_uid": entry["player_uid"]})
            continue
        signature_map[sig] = entry

    # Attach match-duration evidence after singleton identity recovery so every trusted
    # signature mapping can contribute. This enables direct per-match minutes on rows
    # whose rolling named history has already expired.
    duration_map, duration_audit = infer_match_durations(reports, signature_map, season_aggregates)
    raw_history_crosschecks = audit_raw_history_crosschecks(reports, signature_map, duration_map)
    rating_crosscheck = raw_history_crosschecks.get("rating", {"matched": 0, "tested": 0, "mismatches": 0})
    rating_raw_enabled = (
        rating_crosscheck["tested"] >= MIN_RATING_CROSSCHECKS
        and rating_crosscheck["mismatches"] == 0
    )
    for report in reports:
        duration_key = (
            int(report["competition_id"]), str(report["date"]), int(report["opponent_team_id"])
        )
        duration_info = duration_map.get(duration_key)
        report["match_duration_minutes"] = duration_info.get("minutes_played") if duration_info else None
        report["match_duration_source"] = duration_info.get("source") if duration_info else "unresolved"
        report["match_duration_history_votes"] = duration_info.get("vote_count", 0) if duration_info else 0

    reports.sort(key=lambda x: (x["date"], x["kick_off_time"], x["competition_id"]))

    # Coverage and team-total reconciliation are calculated against all formal fixtures.
    expected_keys = set(fixture_index)
    actual_list = [(int(r["competition_id"]), str(r["date"]), int(r["home_team_id"]), int(r["away_team_id"])) for r in reports]
    actual_keys = set(actual_list)
    duplicate_keys = sorted({key for key in actual_list if actual_list.count(key) > 1})
    missing_keys = sorted(expected_keys - actual_keys)
    unexpected_keys = sorted(actual_keys - expected_keys)

    identified_rows: list[dict[str, Any]] = []
    unresolved_rows: list[dict[str, Any]] = []
    all_appearance_rows: list[dict[str, Any]] = []
    cache_usage: Counter[str] = Counter()
    cache_history_presence = 0
    duplicate_uid_conflicts: list[dict[str, Any]] = []
    candidate_history_conflicts: list[dict[str, Any]] = []
    unknown_signatures: Counter[str] = Counter()
    team_checks = {"comparisons": 0, "matches": 0, "mismatches": 0, "missing": 0}
    appearance_count = 0
    roster_row_count = 0
    zero_minute_exclusions: list[dict[str, Any]] = []

    for report in reports:
        fixture = fixture_index[(report["competition_id"], report["date"], report["home_team_id"], report["away_team_id"])]
        context = make_match_context(report, fixture)
        history_by_uid: dict[int, dict[str, Any]] = {}
        for history_row in report.get("candidate_player_history_rows", []):
            history_uid = as_int(history_row.get("player_uid"))
            if history_uid is None:
                continue
            previous = history_by_uid.get(history_uid)
            if previous is None or (history_row.get("has_stats") is True and previous.get("has_stats") is not True):
                history_by_uid[history_uid] = history_row
        pending: list[tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None, str | None]] = []
        for row in report["anonymous_player_rows"]:
            roster_row_count += 1
            sig = str(row.get("row_signature", "")).lower()
            mapping = signature_map.get(sig)
            mapped_history = history_by_uid.get(int(mapping["player_uid"])) if mapping else None
            metrics = row["metrics"]
            if not is_appearance(metrics, mapped_history):
                continue
            appearance_count += 1
            conflict_reason = None
            if mapping and mapped_history is not None:
                history_minutes = as_int(mapped_history.get("minutes"), 0) or 0
                if mapped_history.get("has_stats") is False and history_minutes <= 0:
                    conflict_reason = "same_match_history_has_no_player_stats"
                    candidate_history_conflicts.append({
                        "competition_id": report["competition_id"],
                        "date": report["date"],
                        "opponent_team_id": context["opponent_team_id"],
                        "signature": sig,
                        "cached_player_uid": mapping["player_uid"],
                        "cached_player_name": mapping["player_name"],
                        "reason": conflict_reason,
                    })
                    mapping = None
                    mapped_history = None
            pending.append((row, mapping, mapped_history, conflict_reason))

        uid_counts = Counter(int(mapping["player_uid"]) for _, mapping, _, _ in pending if mapping)
        duplicated = {uid for uid, count in uid_counts.items() if count > 1}
        for row, mapping, history, conflict_reason in pending:
            sig = str(row.get("row_signature", "")).lower()
            base = {
                "date": report["date"],
                "competition_id": report["competition_id"],
                "competition_name": context["competition_name"],
                "round": context["round"],
                "kick_off_time": report["kick_off_time"],
                "home_away": context["home_away"],
                "opponent_team_id": context["opponent_team_id"],
                "opponent_name": context["opponent_name"],
                "home_goals": context["home_goals"],
                "away_goals": context["away_goals"],
                "team_goals": context["team_goals"],
                "opponent_goals": context["opponent_goals"],
                "match_result": context["match_result"],
                "report_row_signature": sig,
                "report_row_index": row["row_index"],
            }
            base.update(row["metrics"])
            raw_stats = raw_stats_from_probe_row(row)
            duration_info = duration_map.get((int(report["competition_id"]), str(report["date"]), int(context["opponent_team_id"])))
            duration_value = as_int(duration_info.get("minutes_played")) if duration_info else None
            decoded_minutes = decode_minutes_from_raw(raw_stats, duration_value)
            raw_field_values = {
                "minutes": decoded_minutes,
                "entered_at_minute": (
                    raw_stats["entered_at_minute"] if raw_stats is not None and raw_stats["entered_at_minute"] > 0 else None
                ),
                "left_at_minute": (
                    raw_stats["left_at_minute"] if raw_stats is not None and raw_stats["left_at_minute"] > 0 else None
                ),
                "goals": raw_stats["goals"] if raw_stats is not None else None,
                "assists": raw_stats["assists"] if raw_stats is not None else None,
                "passes_attempted": raw_stats["passes_attempted"] if raw_stats is not None else None,
                "passes_completed": raw_stats["passes_completed"] if raw_stats is not None else None,
            }
            history_rating_value = None
            if history and history.get("rating") not in (None, ""):
                try:
                    history_rating_value = float(history.get("rating"))
                except (TypeError, ValueError):
                    history_rating_value = None
            raw_rating_hundredths = (
                as_int(raw_stats.get("rating_hundredths"))
                if rating_raw_enabled and raw_stats is not None else None
            )
            raw_rating_value = rating_from_raw_stats(raw_stats) if rating_raw_enabled else None
            if raw_rating_value is not None:
                rating_value = raw_rating_value
                rating_source = (
                    "raw_match_report_rating_crosschecked"
                    if history_rating_value is not None
                    else "raw_match_report_rating_recovered"
                )
            elif history_rating_value is not None:
                rating_value = history_rating_value
                rating_source = "retained_named_player_history"
            else:
                rating_value = None
                rating_source = "unavailable"

            effective_minutes = (
                decoded_minutes if decoded_minutes is not None
                else (as_int(history.get("minutes")) if history else None)
            )
            if effective_minutes is not None and effective_minutes <= 0:
                zero_minute_exclusions.append({
                    "date": report["date"],
                    "competition_id": report["competition_id"],
                    "opponent_team_id": context["opponent_team_id"],
                    "report_row_signature": sig,
                    "player_name": mapping.get("player_name") if mapping else None,
                    "minutes": effective_minutes,
                })
                continue

            raw_field_values["rating"] = rating_value
            raw_field_values["rating_raw_hundredths"] = raw_rating_hundredths if raw_rating_value is not None else None
            raw_field_values["rating_source"] = rating_source

            if mapping and int(mapping["player_uid"]) in duplicated:
                duplicate_uid_conflicts.append({
                    "competition_id": report["competition_id"], "date": report["date"],
                    "opponent_team_id": context["opponent_team_id"], "signature": sig,
                    "player_uid": mapping["player_uid"], "reason": "two report rows resolved to the same player UID in one match",
                })
                mapping = None
                history = None
            if mapping:
                uid = int(mapping["player_uid"])
                has_match_history = bool(history and (history.get("has_stats") is True or history.get("minutes") is not None))
                if has_match_history:
                    cache_history_presence += 1
                cache_usage[str(mapping.get("evidence", "validated_signature_cache"))] += 1
                evidence_type = str(mapping.get("evidence", "validated_signature_cache"))
                if evidence_type == "single_remaining_same_match_named_history":
                    identity_method = "unique_same_match_history_residual"
                    identity_confidence = "同场具名出场名单与详细报告出场行数量完全一致，且仅剩该球员与该记录一一对应"
                elif evidence_type == "prior_validated_signature_cache":
                    identity_method = "prior_named_history_validated_signature_cache_cross_competition"
                    identity_confidence = "签名映射曾在同一存档的旧报告中通过具名历史交叉检查；本场仅作为跨赛事签名转用"
                elif evidence_type == "unique_exact_season_vector":
                    identity_method = "unique_season_vector_signature_cache_cross_competition"
                    identity_confidence = "签名映射由同一存档唯一精确赛季统计向量确定；本场跨赛事转用并非独立同场证明"
                else:
                    identity_method = "unclassified_signature_cache_cross_competition"
                    identity_confidence = "签名缓存中的来源类型未分类，需检查身份审计"
                identified = {
                    **base,
                    "player_uid": uid,
                    "player_name": mapping["player_name"],
                    "identity_method": identity_method,
                    "identity_confidence": identity_confidence,
                    "named_history_available": has_match_history,
                    "position_code": history.get("position_code") if history else None,
                    "minutes": raw_field_values["minutes"] if raw_field_values["minutes"] is not None else (history.get("minutes") if history else None),
                    "entered_at_minute": raw_field_values["entered_at_minute"] if raw_field_values["entered_at_minute"] is not None else (history.get("entered_at_minute") if history else None),
                    "left_at_minute": raw_field_values["left_at_minute"] if raw_stats is not None else (history.get("left_at_minute") if history else None),
                    "rating": raw_field_values["rating"],
                    "rating_raw_hundredths": raw_field_values["rating_raw_hundredths"],
                    "rating_source": raw_field_values["rating_source"],
                    "goals": raw_field_values["goals"] if raw_field_values["goals"] is not None else (history.get("goals") if history else None),
                    "assists": raw_field_values["assists"] if raw_field_values["assists"] is not None else (history.get("assists") if history else None),
                    "passes_attempted": raw_field_values["passes_attempted"] if raw_field_values["passes_attempted"] is not None else (history.get("passes_attempted") if history else None),
                    "passes_completed": raw_field_values["passes_completed"] if raw_field_values["passes_completed"] is not None else (history.get("passes_completed") if history else None),
                }
                identified_rows.append(identified)
                all_appearance_rows.append({**identified, "identity_status": "identified"})
            else:
                if conflict_reason:
                    reason = conflict_reason
                elif sig in rejected_cache_signatures:
                    reason = "cached_mapping_quarantined_uid_absent_current_overall_and_unvalidated"
                elif sig not in signature_map:
                    reason = "signature_not_in_validated_cache"
                elif any(x.get("signature") == sig and x.get("date") == report["date"] for x in duplicate_uid_conflicts):
                    reason = "duplicate_uid_in_same_match"
                elif any(x.get("signature") == sig and x.get("date") == report["date"] for x in candidate_history_conflicts):
                    reason = "same_match_history_has_no_player_stats"
                else:
                    reason = "identity_conflict_requires_review"
                unknown_signatures[sig] += 1
                unresolved = {
                    **base,
                    "reason": reason,
                    **raw_field_values,
                    "position_code": None,
                    "rating": raw_field_values["rating"],
                    "rating_raw_hundredths": raw_field_values["rating_raw_hundredths"],
                    "rating_source": raw_field_values["rating_source"],
                }
                unresolved_rows.append(unresolved)
                all_appearance_rows.append({**unresolved, "identity_status": "unresolved"})

        for item in report.get("team_total_check", {}).values():
            match_value = item.get("match")
            if match_value is True:
                team_checks["comparisons"] += 1
                team_checks["matches"] += 1
            elif match_value is False:
                team_checks["comparisons"] += 1
                team_checks["mismatches"] += 1
            else:
                team_checks["missing"] += 1

    identified_rows.sort(key=lambda r: (r["date"], r["kick_off_time"], r["competition_id"], int(r["report_row_index"])))
    unresolved_rows.sort(key=lambda r: (r["date"], r["kick_off_time"], r["competition_id"], int(r["report_row_index"])))
    all_appearance_rows.sort(key=lambda r: (r["date"], r["kick_off_time"], r["competition_id"], int(r["report_row_index"])))

    # Write standard filenames consumed by the existing exporter and formal-scope mirrors.
    out_probe = export_dir / "player-report-probe.json"
    probe_payload = {
        "probe_version": "1.9-formal-stale-cache-quarantine",
        "purpose": "Targeted extraction of first-team player detail rows from formal competitions only.",
        "source": source_meta,
        "identity_status": "formal_identity_cache_with_unresolved_rows" if unresolved_rows else "formal_identity_cache_applied",
        "signature_layout": source_meta.get("signature_layout"),
        "replayed_from_existing_probe": bool(args.reuse_probe),
        "identity_cache": {
            "cache_file": cache_path.name,
            "rejected_stale_mapping_count": len(rejected_cache_mappings),
            "rejected_stale_mappings": rejected_cache_mappings,
            "seed_report_id": cache.get("seed_source", {}).get("report_id"),
            "seed_competition_id": cache.get("seed_source", {}).get("competition_id"),
            "mapping_count": len(signature_map),
            "mapped_appearance_rows": len(identified_rows),
            "mapped_rows_with_same_match_history": cache_history_presence,
            "mappings_by_evidence": dict(cache_usage),
            "note": "Existing identities transfer by exact four-byte signature from the validated league seed. A new signature is learned only when complete same-match history leaves exactly one active UID for exactly one unknown active report row. Sparse or conflicting matches are not guessed.",
        },
        "report_count": len(reports),
        "matchday_roster_rows": roster_row_count,
        "raw_activity_rows_detected": appearance_count,
        "actual_appearance_rows": len(all_appearance_rows),
        "excluded_zero_minute_rows": len(zero_minute_exclusions),
        "identified_appearance_rows": len(identified_rows),
        "unresolved_appearance_rows": len(unresolved_rows),
        "team_total_check": team_checks,
        "reports": reports,
    }
    write_json(out_probe, probe_payload)
    write_json(export_dir / "player-match-report-identified.json", identified_rows)
    write_json(export_dir / "player-report-identity-audit.json", {
        "audit_version": "1.9-formal-stale-cache-quarantine",
        "team_id": args.team_id,
        "competition_id": 0 if args.competition_id == 0 else args.competition_id,
        "formal_competition_ids": sorted(comp_ids),
        "excluded_non_competitive_competition_ids": list(EXCLUDED_NON_COMPETITIVE_IDS),
        "source": probe_payload["source"],
        "scope": {
            "detailed_report_matches": len(reports),
            "played_first_team_formal_competition_fixtures": len(fixtures),
            "played_fixtures_without_detailed_report": [list(x) for x in missing_keys],
            "unexpected_reports": [list(x) for x in unexpected_keys],
            "duplicate_report_keys": [list(x) for x in duplicate_keys],
            "matchday_roster_rows": roster_row_count,
            "raw_activity_rows_detected": appearance_count,
            "actual_appearance_rows": len(all_appearance_rows),
            "excluded_zero_minute_rows": len(zero_minute_exclusions),
            "identified_appearance_rows": len(identified_rows),
            "unresolved_appearance_rows": len(unresolved_rows),
            "identified_unique_players": len({r["player_uid"] for r in identified_rows}),
            "detail_metrics": list(TEAM_SUM_FIELDS),
            "raw_player_fields": list(RAW_PLAYER_FIELD_OFFSETS) + ["rating_hundredths"],
            "entered_at_minute_source": "fmsave==0.12.4 PlayerMatchStats.entered_at_minute; raw-window offset +71 is dynamically checked against same-match history where available.",
            "minutes_rows_decoded": sum(1 for row in all_appearance_rows if row.get("minutes") not in (None, "")),
            "rating_rows_available": sum(1 for row in identified_rows if row.get("rating") not in (None, "")),
        },
        "identity": {
            "method": "player_record_signature_anchor_minus_100_with_guarded_singleton_inference",
            "rejected_cache_mappings": rejected_cache_mappings,
        "named_history_source": history_source,
            "signature_layout": source_meta.get("signature_layout"),
            "signature_mapping_count": len(signature_map),
            "mapping_provenance": cache.get("seed_source", {}),
            "mappings_by_evidence": dict(cache_usage),
            "derived_singleton_signature_mappings": inferred_map,
            "derived_singleton_evidence": inferred_evidence,
            "rejected_singleton_inferences": rejected_inference,
            "same_match_history_rows_present": cache_history_presence,
            "unresolved_signatures": dict(sorted(unknown_signatures.items())),
            "duplicate_uid_conflicts": duplicate_uid_conflicts,
            "candidate_history_conflicts": candidate_history_conflicts,
            "cache_entries_not_in_current_overall_stats": [
                {"signature": sig, "player_uid": value["player_uid"], "player_name": value["player_name"]}
                for sig, value in signature_map.items() if int(value["player_uid"]) not in roster_names
            ],
            "limitations": [
                "The four-byte signature map was learned from the same save's league report; applying it to other formal competitions is a cross-competition transfer, not an independent row-by-row name proof for every cup/continental match.",
                "No row index, lineup order, or performance profile is treated as a player ID; only the four-byte record signature at statistics_anchor-100 is used.",
                "Goals, assists and pass attempts/completions are decoded from verified raw player-record offsets and cross-checked against named same-match history; season aggregates are not copied into individual rows.",
                "Minutes are decoded from raw entry/exit clocks only when the match duration is established by named-history votes, a unique exact category-aggregate solution, or a regular-time competition/stage rule. Otherwise they remain blank unless exact named history supplies them.",
                "Match-report rating is uint16 little-endian at raw-window +136 (statistics_anchor +36), divided by 100 and rounded half-up to one decimal. It is enabled only after at least 25 same-match named-history rating checks pass with zero mismatches.",
                "Rows with a verified zero-minute appearance are omitted from per-player CSV reports. Team-total reconciliation still uses every raw match-report row before this filter.",
                "FM27 27.0.1+2494687 remains upstream-unregistered in fmsave 0.12.4; the compatibility audit records local checks only and does not change upstream known_build status.",
                "Pre-season/non-competitive competition_id 131 is excluded from this report.",
            ],
        },
        "validation": {
            "fixture_coverage": {
                "expected_formal_fixtures": len(fixtures),
                "decoded_reports": len(reports),
                "missing_fixtures": len(missing_keys),
                "unexpected_reports": len(unexpected_keys),
                "duplicate_reports": len(duplicate_keys),
                "complete": not missing_keys and not unexpected_keys and not duplicate_keys,
            },
            "team_total_checks": team_checks,
            "all_active_rows_identified": len(unresolved_rows) == 0,
            "raw_player_field_offsets": RAW_PLAYER_FIELD_OFFSETS,
            "raw_player_field_reference_validation": RAW_PLAYER_FIELD_VALIDATION,
            "entered_at_minute_validation": {
                "native_source": "fmsave 0.12.4 PlayerMatchStats.entered_at_minute",
                "raw_window_offset": RAW_PLAYER_FIELD_OFFSETS["entered_at_minute"],
                "same_match_crosscheck": raw_history_crosschecks.get("entered_at_minute", {"matched": 0, "tested": 0, "mismatches": 0}),
            },
            "minute_formula": RAW_MINUTE_RULE,
            "match_duration_audit": duration_audit,
            "raw_history_crosschecks": raw_history_crosschecks,
            "rating_recovery": {
                "status": "raw_report_rating_locally_crosschecked" if rating_raw_enabled else "named_history_fallback_only",
                "source": "uint16 little-endian at raw-window +136 (statistics_anchor +36), divided by 100 and rounded half-up to one decimal",
                "raw_window_offset": RAW_RATING_FIELD_OFFSET,
                "anchor_relative_offset": RAW_RATING_FIELD_OFFSET - 100,
                "crosscheck_minimum": MIN_RATING_CROSSCHECKS,
                "crosscheck": rating_crosscheck,
                "raw_source_enabled": rating_raw_enabled,
                "available_rows": sum(1 for row in identified_rows if row.get("rating") not in (None, "")),
                "missing_rows": sum(1 for row in identified_rows if row.get("rating") in (None, "")),
                "total_identified_rows": len(identified_rows),
            },
            "zero_minute_exclusion": {
                "excluded_rows": len(zero_minute_exclusions),
                "by_competition": dict(Counter(str(row["competition_id"]) for row in zero_minute_exclusions)),
                "reason": "verified_minutes_zero",
                "team_total_checks_use_full_raw_report_rows": True,
            },
            "raw_field_coverage": {
                field: sum(1 for row in all_appearance_rows if row.get(field) not in (None, ""))
                for field in ("goals", "assists", "passes_attempted", "passes_completed", "entered_at_minute", "minutes", "rating", "rating_raw_hundredths")
            },
            "named_history_match_count": 0,
            "named_history_matches_passed": 0,
        "named_history_source": history_source,
            "named_history_note": "Named history supplies positions and cross-checks ratings/entry clocks; the raw match-report player record supplies detailed ratings plus goals, assists, entry/exit clocks and passing counts.",
            "duplicate_uid_within_match_rows": duplicate_uid_conflicts,
            "candidate_history_conflicts": candidate_history_conflicts,
            "formal_competitions_only": all(int(r["competition_id"]) in comp_ids for r in reports),
            "excluded_competition_131_rows": sum(1 for r in reports if int(r["competition_id"]) in EXCLUDED_NON_COMPETITIVE_IDS),
        },
    })
    write_csv(export_dir / "player-match-report-identified.csv", IDENTIFIED_FIELDS, identified_rows)
    write_csv(export_dir / "player-match-report-unresolved.csv", UNRESOLVED_FIELDS, unresolved_rows)
    write_csv(export_dir / "player-match-report-formal-all.csv", [
        *IDENTIFIED_FIELDS, "identity_status", "reason",
    ], all_appearance_rows)
    per_competition = {}
    for comp in sorted(comp_ids):
        comp_reports = [r for r in reports if int(r["competition_id"]) == comp]
        comp_identified = [r for r in identified_rows if int(r["competition_id"]) == comp]
        comp_unresolved = [r for r in unresolved_rows if int(r["competition_id"]) == comp]
        comp_checks = {"comparisons": 0, "matches": 0, "mismatches": 0, "missing": 0}
        for report in comp_reports:
            for item in report.get("team_total_check", {}).values():
                if item.get("match") is True:
                    comp_checks["comparisons"] += 1
                    comp_checks["matches"] += 1
                elif item.get("match") is False:
                    comp_checks["comparisons"] += 1
                    comp_checks["mismatches"] += 1
                else:
                    comp_checks["missing"] += 1
        per_competition[str(comp)] = {
            "expected_fixtures": sum(1 for x in fixtures if int(x["competition_id"]) == comp),
            "detailed_reports_found": len(comp_reports),
            "identified_appearances": len(comp_identified),
            "unresolved_appearances": len(comp_unresolved),
            "team_total_reconciliation": comp_checks,
        }
    raw_field_coverage = {
        field: {
            "nonempty": sum(1 for row in all_appearance_rows if row.get(field) not in (None, "")),
            "missing": sum(1 for row in all_appearance_rows if row.get(field) in (None, "")),
        }
        for field in ("goals", "assists", "passes_attempted", "passes_completed", "entered_at_minute", "minutes", "rating", "rating_raw_hundredths")
    }
    raw_field_coverage_by_competition: dict[str, dict[str, dict[str, int]]] = {}
    for comp in sorted(comp_ids):
        comp_rows = [row for row in all_appearance_rows if as_int(row.get("competition_id")) == comp]
        raw_field_coverage_by_competition[str(comp)] = {
            field: {
                "nonempty": sum(1 for row in comp_rows if row.get(field) not in (None, "")),
                "missing": sum(1 for row in comp_rows if row.get(field) in (None, "")),
            }
            for field in ("goals", "assists", "passes_attempted", "passes_completed", "entered_at_minute", "minutes", "rating", "rating_raw_hundredths")
        }
    write_json(export_dir / "player-match-report-formal-summary.json", {
        "report_scope": "first-team formal competitions only",
        "formal_competition_ids": sorted(comp_ids),
        "excluded_non_competitive_competition_ids": list(EXCLUDED_NON_COMPETITIVE_IDS),
        "expected_fixtures": len(fixtures),
        "detailed_reports_found": len(reports),
        "raw_activity_rows_detected": appearance_count,
        "active_player_appearances": len(all_appearance_rows),
        "excluded_zero_minute_rows": len(zero_minute_exclusions),
        "identified_appearances": len(identified_rows),
        "unresolved_appearances": len(unresolved_rows),
        "unique_players_identified": len({r["player_uid"] for r in identified_rows}),
        "team_total_reconciliation": team_checks,
        "per_competition": per_competition,
        "raw_player_field_coverage": raw_field_coverage,
        "raw_player_field_coverage_by_competition": raw_field_coverage_by_competition,
        "raw_history_crosschecks": raw_history_crosschecks,
        "match_duration_audit": duration_audit,
        "rating_recovery": {
            "source": "uint16 little-endian at raw-window +136 (statistics_anchor +36), divided by 100 and rounded half-up to one decimal",
            "available": raw_field_coverage["rating"]["nonempty"],
            "missing": raw_field_coverage["rating"]["missing"],
            "status": "raw_report_rating_locally_crosschecked" if rating_raw_enabled else "named_history_fallback_only",
            "crosscheck_minimum": MIN_RATING_CROSSCHECKS,
            "crosscheck": rating_crosscheck,
            "raw_source_enabled": rating_raw_enabled,
        },
        "zero_minute_exclusion": {
            "excluded_rows": len(zero_minute_exclusions),
            "by_competition": dict(Counter(str(row["competition_id"]) for row in zero_minute_exclusions)),
            "reason": "verified_minutes_zero",
            "team_total_checks_use_full_raw_report_rows": True,
        },
        "derived_singleton_signature_mappings": inferred_map,
        "missing_fixtures": [list(x) for x in missing_keys],
        "unresolved_signatures": dict(sorted(unknown_signatures.items())),
    })

    learned_cache = {**cache, "mappings": dict(cache.get("mappings", {}))}
    for sig, entry in inferred_map.items():
        if sig not in learned_cache["mappings"]:
            learned_cache["mappings"][sig] = entry
    learned_cache["updated_from_report"] = {
        "output_directory": export_dir.name,
        "derived_signature_count": len(inferred_map),
        "unresolved_signature_count": len(unknown_signatures),
    }
    write_json(export_dir / "FM27_PlayerIdentityCache_Formal_v1.1_learned.json", learned_cache)

    # Generate local compatibility evidence without changing fmsave's upstream build registration.
    validation_path = export_dir / "validation.json"
    validation = read_json(validation_path) if validation_path.is_file() else {}
    validation_readers = validation.get("readers", []) if isinstance(validation, dict) else []
    team_reader = next((item for item in validation_readers if item.get("reader") == "team_match_stats"), None)
    team_rows: list[dict[str, Any]] = []
    team_stats_path = export_dir / "team-match-stats.json"
    if team_stats_path.is_file():
        exported_team_rows = read_json(team_stats_path)
        if isinstance(exported_team_rows, list):
            team_rows = exported_team_rows
        elif isinstance(exported_team_rows, dict):
            team_rows = [value for value in exported_team_rows.values() if isinstance(value, dict)]
    own_team_rows = [row for row in team_rows if as_int(row.get("team_id")) == args.team_id]
    fixture_check_passed = not missing_keys and not unexpected_keys and not duplicate_keys
    total_check_passed = team_checks["mismatches"] == 0 and team_checks["missing"] == 0
    reader_passed = bool(team_reader and team_reader.get("status") == "ok")
    local_passed = reader_passed and fixture_check_passed and total_check_passed
    team_layout = (team_reader or {}).get("layout") or {}
    write_json(export_dir / "team-match-stats-compatibility.json", {
        "audit_version": "1.0-v1.4.3-local-compatibility",
        "game": source_meta.get("game"),
        "save_build": source_meta.get("game_build") or source_meta.get("build"),
        "save_known_build_upstream": source_meta.get("known_build"),
        "fmsave_version": source_meta.get("fmsave_version"),
        "section": SECTION,
        "save_section_schema": source_meta.get("section_schema"),
        "reader": {
            "name": "team_match_stats",
            "status": (team_reader or {}).get("status", "not_checked"),
            "record_count": (team_reader or {}).get("record_count"),
            "layout_region": team_layout.get("region"),
            "layout_source_build": team_layout.get("build") or source_meta.get("layout_source_build"),
            "layout_source_schema": team_layout.get("schema") or source_meta.get("layout_source_schema"),
            "save_schema": team_layout.get("save_schema") or source_meta.get("section_schema"),
            "layout_borrowed": bool(source_meta.get("layout_borrowed")),
        },
        "upstream_registration": {
            "status": "unverified_borrowed_layout" if source_meta.get("known_build") is False else "registered_or_not_marked_unverified",
            "registered_reference_build": REFERENCE_BUILD,
            "note": "This local audit does not alter fmsave known_build or make the save build upstream-registered.",
        },
        "local_assessment": "passed" if local_passed else "partial_or_unverified",
        "local_checks": {
            "team_match_stats_reader_passed": reader_passed,
            "managed_first_team_team_match_stats_rows": len(own_team_rows),
            "formal_fixture_coverage": {
                "expected": len(fixtures),
                "decoded": len(reports),
                "missing": len(missing_keys),
                "unexpected": len(unexpected_keys),
                "duplicates": len(duplicate_keys),
                "passed": fixture_check_passed,
            },
            "player_team_total_reconciliation": team_checks,
            "raw_player_field_crosschecks": {
                field: raw_history_crosschecks.get(field, {"matched": 0, "tested": 0, "mismatches": 0})
                for field in ("goals", "assists", "passes_attempted", "passes_completed", "entered_at_minute", "left_at_minute", "minutes", "rating")
            },
            "rating_field_crosscheck": {
                "raw_window_offset": RAW_RATING_FIELD_OFFSET,
                "anchor_relative_offset": RAW_RATING_FIELD_OFFSET - 100,
                "encoding": "uint16 little-endian hundredths; /100; half-up to one decimal",
                "minimum_required": MIN_RATING_CROSSCHECKS,
                **rating_crosscheck,
                "passed": rating_raw_enabled,
            },
            "zero_minute_rows_excluded": len(zero_minute_exclusions),
        },
        "limitations": [
            "Local evidence applies only to this checked save/build/schema and does not confer upstream registration.",
            "FM27 build 27.0.1+2494687 remains upstream-unverified in fmsave 0.12.4 and borrows the registered 27.0.0 schema-6 layout.",
            "Structural and data reconciliation are not a substitute for semantic validation on other saves.",
        ],
    })

    # Output a compact status for PowerShell diagnostics.
    print(f"Formal competitions: {','.join(str(x) for x in sorted(comp_ids))}")
    print(f"Formal fixtures expected: {len(fixtures)} | detailed reports found: {len(reports)} | missing: {len(missing_keys)}")
    print(f"Player appearances: {len(all_appearance_rows)} | raw activity rows: {appearance_count} | zero-minute rows skipped: {len(zero_minute_exclusions)}")
    print(f"Identified: {len(identified_rows)} | unresolved: {len(unresolved_rows)}")
    print(f"Ratings recovered: {sum(1 for row in identified_rows if row.get('rating') not in (None, ''))} | raw rating cross-check: {rating_crosscheck['matched']}/{rating_crosscheck['tested']}")
    print(f"Team-total reconciliation: {team_checks['matches']}/{team_checks['comparisons']} matched; {team_checks['mismatches']} mismatches; {team_checks['missing']} missing")
    if args.reuse_probe:
        print("REUSE_PROBE: existing raw byte windows were replayed; the .fm save was not opened or modified.")
    print(f"Outputs written to: {export_dir}")
    enrichment_script = Path(__file__).resolve().with_name("FM27_FormalPlayerReport_Enrichment_v1.1.py")
    subprocess.run([sys.executable, str(enrichment_script), str(export_dir)], check=True)
    if missing_keys or unexpected_keys or duplicate_keys or team_checks["mismatches"]:
        print("WARNING: coverage/team totals require review; the audit records the exact blockers.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise SystemExit(2)
