#!/usr/bin/env python3
"""Strictly scope FM27 export artifacts to the managed first team (v1.2.2).

Player profiles are restricted to the actual managed first-team team_id. Historical
players assigned to reserve/youth teams are retained in first-team match history only
when they registered minutes in a first-team match. Unused reserve/youth match-sheet
entries and all reserve-team profile data are excluded.

The .fm save is read-only; only exported artifacts are filtered.
"""
from __future__ import annotations
import argparse, csv, json
from collections import defaultdict
from pathlib import Path
from typing import Any


def as_int(value: Any) -> int | None:
    try:
        return None if value is None or value == "" else int(value)
    except (TypeError, ValueError):
        return None


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def rows_from(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
        raise TypeError(f"{label} must be a JSON array of objects")
    return value


def filter_by_team(path: Path, team_id: int, *, required: bool = False) -> tuple[int, int]:
    if not path.exists():
        if required: raise FileNotFoundError(path)
        return 0, 0
    raw = rows_from(read_json(path), path.name)
    kept = [x for x in raw if as_int(x.get("team_id")) == team_id]
    if raw and not kept:
        raise RuntimeError(f"{path.name}: no rows matched first-team team_id={team_id}")
    write_json(path, kept)
    return len(raw), len(kept)


def csv_filter(path: Path, predicate) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    if not path.exists(): return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f); fields = reader.fieldnames; source = list(reader)
    if not fields: raise RuntimeError(f"{path.name}: CSV has no header")
    kept = [r for r in source if predicate(r)]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader(); w.writerows(kept)
    return source, kept


def write_role_audit(path: Path, history: list[dict[str, Any]]) -> None:
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for r in history:
        if not r.get("has_stats") or r.get("position_code") is None or r.get("role_code_raw") is None:
            continue
        key = (str(r["position_code"]), str(r["role_code_raw"]))
        g = groups.setdefault(key, {"mask": r.get("position_mask_hex") or "", "records": 0, "players": set()})
        g["records"] += 1; g["players"].add(str(r.get("player_name") or ""))
    fields = ["position_code", "position_mask_hex", "role_code_raw", "records", "unique_players", "players", "meaning"]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for (pc, rc), g in sorted(groups.items(), key=lambda x: (int(x[0][0]), int(x[0][1]))):
            names = sorted(x for x in g["players"] if x)
            w.writerow({"position_code":pc,"position_mask_hex":g["mask"],"role_code_raw":rc,
                        "records":g["records"],"unique_players":len(names),"players":";".join(names),
                        "meaning":"UNDECODED - preserve raw value"})


def fixture_key_from_fixture(row: dict[str, Any], team_id: int):
    home, away = as_int(row.get("home_team_id")), as_int(row.get("away_team_id"))
    if team_id not in (home, away): return None
    opp = away if home == team_id else home
    return (as_int(row.get("competition_id")), str(row.get("date")), opp)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("export_dir", type=Path); ap.add_argument("--team-id", type=int, default=539); ap.add_argument("--club-uid", type=int, default=680)
    a = ap.parse_args(); root = a.export_dir.expanduser().resolve()
    if not root.is_dir(): raise NotADirectoryError(root)

    # Match context: only fixtures involving the managed first team.
    fpath = root / "fixtures.json"; fixtures_raw = rows_from(read_json(fpath), fpath.name)
    fixtures = [r for r in fixtures_raw if a.team_id in (as_int(r.get("home_team_id")), as_int(r.get("away_team_id")))]
    if not fixtures: raise RuntimeError(f"No fixtures found for team_id={a.team_id}")
    write_json(fpath, fixtures)
    played_fixture_keys = {fixture_key_from_fixture(r, a.team_id) for r in fixtures if r.get("played")}
    played_fixture_keys.discard(None)

    # Selection: only the explicit managed first-team XI and substitutes.
    spath = root / "selections.json"; selection_raw = rows_from(read_json(spath), spath.name)
    selections = [r for r in selection_raw if as_int(r.get("team_id")) == a.team_id]
    selection_uids = {as_int(r.get("player_uid")) for r in selections}; selection_uids.discard(None)
    write_json(spath, selections)

    # History identifies first-team participants. Only users who actually logged minutes
    # outside the current first-team roster are retained as historical first-team guests.
    hpath = root / "player-position-history.json"
    history_raw = rows_from(read_json(hpath), hpath.name)
    appearance_uids = {as_int(r.get("player_uid")) for r in history_raw
                       if r.get("has_stats") and (as_int(r.get("minutes")) or 0) > 0}
    appearance_uids.discard(None)

    # Current player profile file is strict: team_id must be the first-team team.
    ppath = root / "players.json"; profiles_raw = rows_from(read_json(ppath), ppath.name)
    profiles = [r for r in profiles_raw if as_int(r.get("team_id")) == a.team_id]
    profile_uids = {as_int(r.get("uid")) for r in profiles}; profile_uids.discard(None)
    if not profiles: raise RuntimeError("players.json: no profiles matched the managed first-team team_id")
    if selection_uids - profile_uids:
        raise RuntimeError(f"First-team selection UIDs missing from first-team profiles: {sorted(selection_uids-profile_uids)}")
    write_json(ppath, profiles)

    historical_guest_uids = appearance_uids - profile_uids
    tracked_uids = profile_uids | selection_uids | appearance_uids

    # Current first-team profiles retain their full first-team match-sheet history.
    # Historical guests (currently assigned outside team_id 539) are retained per row
    # only when that exact first-team fixture record has actual minutes and stats.
    def has_played_minutes(row: dict[str, Any]) -> bool:
        return bool(row.get("has_stats")) and (as_int(row.get("minutes")) or 0) > 0

    history = [r for r in history_raw if (
        as_int(r.get("player_uid")) in profile_uids or
        (as_int(r.get("player_uid")) in historical_guest_uids and has_played_minutes(r))
    )]
    write_json(hpath, history)
    def history_row_key(r: dict[str, Any]):
        return (as_int(r.get("player_uid")), as_int(r.get("competition_id")),
                str(r.get("date")), as_int(r.get("opponent_team_id")))
    history_keys = {history_row_key(r) for r in history}

    mpath = root / "player-match-stats.json"; match_raw = rows_from(read_json(mpath), mpath.name)
    match = [r for r in match_raw if as_int(r.get("player_uid")) in tracked_uids and history_row_key(r) in history_keys]
    write_json(mpath, match)

    # Per-player summary, history CSV and role audit follow the exact retained history rows.
    sp = root / "player-position-player-summary.csv"
    if sp.exists():
        _, summary_kept = csv_filter(sp, lambda r: as_int(r.get("player_uid")) in tracked_uids)
        history_counts = {}
        stats_counts = {}
        for r in history:
            uid = as_int(r.get("player_uid"))
            history_counts[uid] = history_counts.get(uid, 0) + 1
            if r.get("has_stats"):
                stats_counts[uid] = stats_counts.get(uid, 0) + 1
        with sp.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f); fields = reader.fieldnames; summary_rows = list(reader)
        for row in summary_rows:
            uid = as_int(row.get("player_uid"))
            if uid in historical_guest_uids:
                row["named_match_records"] = str(history_counts.get(uid, 0))
                row["matches_with_stats"] = str(stats_counts.get(uid, 0))
        with sp.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader(); writer.writerows(summary_rows)
    hp_csv = root / "player-position-history.csv"
    if hp_csv.exists(): csv_filter(hp_csv, lambda r: history_row_key(r) in history_keys)
    role_audit = root / "player-position-role-code-audit.csv"
    write_role_audit(role_audit, history)

    # Season aggregates: first-team team_id rows only (never reserve team aggregates).
    season_path = root / "player-season-stats.csv"
    season_source, season_kept = csv_filter(season_path, lambda r: as_int(r.get("team_id")) == a.team_id and as_int(r.get("player_uid")) in tracked_uids)

    # Match report statistics: retain only our own side.
    tpath = root / "team-match-stats.json"; tm_before, tm_after = filter_by_team(tpath, a.team_id, required=True)

    # Current first-team tactic and set pieces only.
    tactical_counts = {}
    for fn in ("tactics.json", "set-pieces.json"):
        before, after = filter_by_team(root / fn, a.team_id); tactical_counts[fn] = {"before":before,"after":after}
    league = root / "league-tables.json"
    if league.exists(): league.unlink()

    # Update position coverage to reflect the exact post-filter scope.
    cpath = root / "player-position-coverage.json"
    if cpath.exists():
        cov = read_json(cpath)
        hist_keys = {(as_int(r.get("competition_id")), str(r.get("date")), as_int(r.get("opponent_team_id"))) for r in history}
        missing = []
        for f in fixtures:
            key = fixture_key_from_fixture(f, a.team_id)
            if f.get("played") and key not in hist_keys:
                opp_id = key[2]
                opp_name = f.get("away_club_short_name") if as_int(f.get("home_team_id")) == a.team_id else f.get("home_club_short_name")
                missing.append({"date":f.get("date"),"competition_id":f.get("competition_id"),"opponent":opp_name,"opponent_team_id":opp_id})
        cov.update({
            "candidate_player_history_rows_joined_to_first_team": len(history),
            "joined_player_history_rows": len(history),
            "joined_rows_with_stats": sum(bool(r.get("has_stats")) for r in history),
            "joined_rows_with_position_code": sum(r.get("position_code") is not None for r in history),
            "joined_rows_with_role_code": sum(r.get("role_code_raw") is not None for r in history),
            "unique_players_with_history": len({as_int(r.get("player_uid")) for r in history}),
            "fixtures_with_named_player_history": len(hist_keys),
            "fixtures_without_named_player_history": missing,
        })
        write_json(cpath, cov)

    missing_profiles = sorted(appearance_uids - profile_uids)
    scope = {
        "scope_version":"1.2.2-strict-first-team",
        "club_uid":a.club_uid,"team_id":a.team_id,
        "policy":{
            "player_profiles":"current first-team team_id only; no B/reserve/youth team profiles",
            "historical_participants":"non-first-team-assigned players retained only on individual first-team match rows where they logged minutes; no full profile or reserve data",
            "player_season_stats":"tracked players, first-team team_id rows only",
            "player_match_stats":"all retained first-team roster match-sheet rows; non-first-team guests only on exact rows where they logged minutes",
            "fixtures":"all first-team fixtures, including scheduled fixtures; opponent identity/date/venue/competition/score metadata only",
            "team_match_stats":"only the managed first team's own team row",
            "tactics_and_selections":"managed first team only",
            "opponent_data":"identity and match context only; no opponent player profiles or opponent team-performance rows"
        },
        "counts":{
            "fixtures_before":len(fixtures_raw),"first_team_fixtures":len(fixtures),"played_first_team_fixtures":sum(bool(r.get("played")) for r in fixtures),
            "player_profiles_before":len(profiles_raw),"first_team_player_profiles":len(profiles),
            "current_first_team_selection":len(selections),"players_with_first_team_minutes":len(appearance_uids),
            "historical_guests_with_first_team_minutes":len(historical_guest_uids),
            "historical_guest_nonappearance_rows_removed":sum(1 for r in history_raw if as_int(r.get("player_uid")) in historical_guest_uids and not has_played_minutes(r)),
            "historical_appearance_players_without_current_first_team_profile":len(missing_profiles),
            "tracked_player_uids":len(tracked_uids),"player_season_stats_before":len(season_source),"player_season_stats_after":len(season_kept),
            "player_match_stats_before":len(match_raw),"player_match_stats_after":len(match),"team_match_stats_before":tm_before,"team_match_stats_after":tm_after,
            "tactical_data":tactical_counts,"history_fixture_keys":len({(as_int(r.get("competition_id")),str(r.get("date")),as_int(r.get("opponent_team_id"))) for r in history}),
            "fixtures_without_named_history":len([r for r in fixtures if r.get("played") and fixture_key_from_fixture(r,a.team_id) not in {(as_int(h.get("competition_id")),str(h.get("date")),as_int(h.get("opponent_team_id"))) for h in history}])
        },
        "historical_appearance_uids_without_current_first_team_profile":missing_profiles,
        "selection_uids_missing_from_first_team_profiles":[],
        "notes":[
            "players.json contains only records whose current team_id is the managed first-team ID.",
            "Reserve/youth players who logged minutes remain identifiable only on those exact first-team match-history rows; their full profiles and reserve-team data are excluded.",
            "Reserve/youth match-sheet rows without actual minutes are removed individually, even for a guest who appeared in another first-team match.",
            "Opponent identity, venue, date, competition and score remain as match context.",
            "The .fm save is never modified; only generated export files are filtered."
        ]
    }
    write_json(root / "first-team-scope.json", scope)
    print("FIRST-TEAM FILTER v1.2.2 COMPLETE")
    removed_guest_rows = scope["counts"]["historical_guest_nonappearance_rows_removed"]
    print(f"First-team profiles: {len(profiles)} | historical guests with minutes: {len(historical_guest_uids)} | guest nonappearance rows removed: {removed_guest_rows} | current selection: {len(selections)}")
    print(f"Fixtures: {len(fixtures)} ({scope['counts']['played_first_team_fixtures']} played) | player-match rows: {len(match)} | own team-match rows: {tm_after}")
    print("No reserve/youth profiles, reserve-team season rows, opponent profiles or opponent-side team-match rows remain.")
    return 0

if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        print(f"FIRST-TEAM FILTER ERROR: {exc}")
        raise SystemExit(2)
