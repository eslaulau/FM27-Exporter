#!/usr/bin/env python3
"""Scope FM27 export artifacts to the managed first team and direct match opponents (v1.3.0).

The save is read-only. Tactical configurations are intentionally not exported or inferred:
the user supplies the tactic used for each match. Opponent data is limited to team-level
statistics in matches involving the managed first team.
"""
from __future__ import annotations
import argparse, csv, json
from collections import defaultdict
from pathlib import Path
from typing import Any

def as_int(value: Any) -> int | None:
    try: return None if value is None or value == "" else int(value)
    except (TypeError, ValueError): return None

def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8-sig") as f: return json.load(f)

def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")

def rows_from(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
        raise TypeError(f"{label} must be a JSON array of objects")
    return value

def csv_filter(path: Path, predicate):
    if not path.exists(): return [], []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f); fields = reader.fieldnames; source = list(reader)
    if not fields: raise RuntimeError(f"{path.name}: CSV has no header")
    kept = [r for r in source if predicate(r)]
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore"); w.writeheader(); w.writerows(kept)
    return source, kept

def match_key(row):
    return (as_int(row.get("competition_id")), as_int(row.get("home_team_id")),
            as_int(row.get("away_team_id")), str(row.get("date")))

def fixture_key(row, team_id):
    home, away = as_int(row.get("home_team_id")), as_int(row.get("away_team_id"))
    if team_id not in (home, away): return None
    return (as_int(row.get("competition_id")), str(row.get("date")), away if home == team_id else home)

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("export_dir", type=Path)
    ap.add_argument("--team-id", type=int, required=True)
    ap.add_argument("--club-uid", type=int, required=True)
    ap.add_argument("--club-name", required=True)
    a = ap.parse_args(); root = a.export_dir.expanduser().resolve()
    if not root.is_dir(): raise NotADirectoryError(root)

    fpath = root / "fixtures.json"; fixtures_raw = rows_from(read_json(fpath), fpath.name)
    fixtures = [r for r in fixtures_raw if a.team_id in
                (as_int(r.get("home_team_id")), as_int(r.get("away_team_id")))]
    if not fixtures: raise RuntimeError(f"No fixtures found for first-team ID {a.team_id}")
    write_json(fpath, fixtures)
    fixture_keys = {match_key(r) for r in fixtures}

    spath = root / "selections.json"; selections_raw = rows_from(read_json(spath), spath.name)
    selections = [r for r in selections_raw if as_int(r.get("team_id")) == a.team_id]
    selection_uids = {as_int(r.get("player_uid")) for r in selections}; selection_uids.discard(None)
    write_json(spath, selections)

    ppath = root / "players.json"; profiles_raw = rows_from(read_json(ppath), ppath.name)
    profiles = [r for r in profiles_raw if as_int(r.get("team_id")) == a.team_id]
    profile_uids = {as_int(r.get("uid")) for r in profiles}; profile_uids.discard(None)
    if not profiles: raise RuntimeError("players.json: no managed first-team profiles matched")
    if selection_uids - profile_uids:
        raise RuntimeError(f"Selection UIDs missing from first-team profiles: {sorted(selection_uids-profile_uids)}")
    write_json(ppath, profiles)

    mpath = root / "player-match-stats.json"; match_raw = rows_from(read_json(mpath), mpath.name)
    # Match-history rows also cover reserve/youth appearances. Join each row to a
    # managed-first-team fixture by competition, date and opponent team ID before keeping it.
    first_team_fixture_keys = {
        (as_int(f.get("competition_id")), str(f.get("date")),
         as_int(f.get("away_team_id")) if as_int(f.get("home_team_id")) == a.team_id
         else as_int(f.get("home_team_id")))
        for f in fixtures
    }
    def player_fixture_key(row):
        return (as_int(row.get("competition_id")), str(row.get("date")),
                as_int(row.get("opponent_team_id")))
    first_team_match_rows = [r for r in match_raw if player_fixture_key(r) in first_team_fixture_keys]
    guest_uids = {as_int(r.get("player_uid")) for r in first_team_match_rows
                  if r.get("has_stats") and (as_int(r.get("minutes")) or 0) > 0}
    guest_uids.discard(None)
    tracked_uids = profile_uids | selection_uids | guest_uids
    match = [r for r in first_team_match_rows if as_int(r.get("player_uid")) in tracked_uids]
    write_json(mpath, match)

    season_path = root / "player-season-stats.csv"
    season_source, season_kept = csv_filter(
        season_path, lambda r: as_int(r.get("team_id")) == a.team_id
        and as_int(r.get("player_uid")) in tracked_uids)

    tpath = root / "team-match-stats.json"; stats_raw = rows_from(read_json(tpath), tpath.name)
    stats = [r for r in stats_raw if a.team_id in
             (as_int(r.get("home_team_id")), as_int(r.get("away_team_id")))]
    if not stats: raise RuntimeError("No team-match-stats rows for managed first-team fixtures")
    grouped = defaultdict(list)
    for row in stats: grouped[match_key(row)].append(row)
    malformed = []
    for key, pair in grouped.items():
        homes = [x for x in pair if x.get("is_home") is True]
        aways = [x for x in pair if x.get("is_home") is False]
        if len(pair) != 2 or len(homes) != 1 or len(aways) != 1:
            malformed.append({"match": key, "rows": len(pair)})
        elif as_int(homes[0].get("team_id")) != key[1] or as_int(aways[0].get("team_id")) != key[2]:
            malformed.append({"match": key, "reason": "home/away team IDs disagree"})
    if malformed:
        raise RuntimeError(f"Expected exactly two team rows per match (home + away); {len(malformed)} match pairs failed. Refusing to claim opponent stats.")
    joined = set(grouped) & fixture_keys
    if grouped and not joined: raise RuntimeError("No team stats match keys join to filtered first-team fixtures")
    write_json(tpath, stats)

    removed_tactics = []
    for name in ("tactics.json", "set-pieces.json"):
        path = root / name
        if path.exists(): path.unlink(); removed_tactics.append(name)
    league = root / "league-tables.json"
    if league.exists(): league.unlink()

    scope = {
      "scope_version": "1.3.0-managed-first-team-match-opponents",
      "club_uid": a.club_uid, "club_name": a.club_name, "team_id": a.team_id,
      "policy": {
        "managed_club_resolution": "managed_clubs() UID; owned club team slot 0",
        "player_profiles": "managed first-team only; no reserve/youth or opponent profiles",
        "player_match_stats": "managed first-team roster and historical guests with actual first-team minutes",
        "player_season_stats": "tracked players, managed first-team team_id rows only",
        "selections": "managed first-team starters and substitutes only",
        "fixtures": "all matches involving managed first team; opponent identity, date, competition, venue and score retained",
        "team_match_stats": "both home and away team rows for each match involving managed first team",
        "opponent_data": "opponent team-level statistics only in direct matches; no opponent player data or unrelated matches",
        "tactics": "not exported, decoded, inferred or reconstructed; user supplies match-to-tactic mapping"
      },
      "counts": {
        "fixtures_before": len(fixtures_raw), "first_team_fixtures": len(fixtures),
        "played_first_team_fixtures": sum(bool(x.get("played")) for x in fixtures),
        "player_profiles_before": len(profiles_raw), "first_team_player_profiles": len(profiles),
        "current_first_team_selection": len(selections), "historical_players_with_minutes": len(guest_uids),
        "tracked_player_uids": len(tracked_uids), "player_match_stats_before": len(match_raw),
        "player_match_stats_after": len(match), "player_season_stats_before": len(season_source),
        "player_season_stats_after": len(season_kept), "team_match_stats_before": len(stats_raw),
        "team_match_stats_after": len(stats), "matches_with_two_team_rows": len(grouped),
        "team_stats_matches_joined_to_fixtures": len(joined),
        "tactical_configuration_files_removed": removed_tactics
      },
      "notes": [
        "The .fm save is never modified.",
        "No fixed club UID or team ID is embedded; identity is resolved from the save at runtime.",
        "Every retained team match must have exactly one home and one away team row.",
        "Opponent team statistics are retained only for matches involving the managed first team.",
        "Opponent player records and unrelated opponent matches are excluded.",
        "Tactical configurations are not exported or inferred; user supplies the tactic used in each match."
      ]
    }
    write_json(root / "first-team-scope.json", scope)
    print("FIRST-TEAM FILTER v1.3.0 COMPLETE")
    print(f"Club: {a.club_name} (UID {a.club_uid}) | first-team ID: {a.team_id}")
    print(f"Fixtures: {len(fixtures)} | player profiles: {len(profiles)} | tracked players: {len(tracked_uids)}")
    print(f"Team stats: {len(stats)} rows across {len(grouped)} matches; both home/away rows validated")
    print("Tactical configuration extraction/inference disabled; opponent player data excluded.")
    return 0

if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        print(f"FIRST-TEAM FILTER ERROR: {exc}")
        raise SystemExit(2)
