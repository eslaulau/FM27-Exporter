#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compare two FM27 tactics tested three times each over a full season.

Inputs are produced by Invoke-PublicExport.ps1:
  <runs-root>/<tactic>__run-1/save-manifest.json
  <runs-root>/<tactic>__run-1/FM27_Analysis_*/...

This is a descriptive comparison of six independent simulations. It does not expect
repeat simulations to have identical scores, and it does not infer unexported tactical
roles or personal instructions.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path
from typing import Any

FORMAL_COMPETITIONS = {7, 637, 661, 662}
TEAM_SUM_FIELDS = (
    "shots", "shots_on_target", "blocked_shots", "shots_outside_box",
    "clear_cut_chances", "fouls_made", "offsides", "yellow_cards", "red_cards",
    "crosses_attempted", "crosses_completed", "tackles_attempted", "tackles_completed",
    "aerial_challenges_attempted", "headers_won", "expected_goals",
    "non_penalty_expected_goals", "distance_km", "progressive_passes",
)
PLAYER_SUM_FIELDS = (
    "goals", "assists", "minutes", "passes_attempted", "passes_completed",
    "yellow_cards", "red_cards", "appearances", "starts",
    "substitute_appearances", "clean_sheets", "goals_conceded",
)


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    with path.open("r", encoding="utf-8-sig") as stream:
        return json.load(stream)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def as_int(value: Any) -> int | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return int(float(value))
    except (TypeError, ValueError, OverflowError):
        return None


def as_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def truthy(value: Any) -> bool:
    return value is True or str(value).strip().lower() in {"true", "1", "yes"}


def match_key(comp: Any, stage: Any, round_value: Any, opponent: Any, home: Any, date: Any = "") -> str:
    parts = [str(comp or ""), str(stage or ""), str(round_value or ""), str(opponent or ""), "H" if home else "A"]
    if not parts[1] and not parts[2]:
        parts.append(str(date or ""))
    return "|".join(parts)


def first_present(rows: list[dict[str, Any]], key: str) -> Any:
    for row in rows:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def numeric_mean(values: list[float]) -> float | None:
    clean = [v for v in values if v is not None and math.isfinite(v)]
    return statistics.mean(clean) if clean else None


def stats_pack(values: list[float]) -> dict[str, float | None]:
    clean = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not clean:
        return {"mean": None, "stdev": None, "min": None, "max": None}
    return {
        "mean": statistics.mean(clean),
        "stdev": statistics.pstdev(clean) if len(clean) > 1 else 0.0,
        "min": min(clean),
        "max": max(clean),
    }


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fields is None:
        fields = []
        for row in rows:
            for key in row:
                if key not in fields:
                    fields.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def discover_trials(runs_root: Path, team_id: int, club_uid: int) -> list[dict[str, Any]]:
    trials: list[dict[str, Any]] = []
    for manifest_path in sorted(runs_root.glob("*/save-manifest.json")):
        manifest = read_json(manifest_path, {})
        if not isinstance(manifest, dict):
            continue
        tactic = str(manifest.get("tactic_name") or "")
        trial = as_int(manifest.get("trial"))
        if not tactic or trial not in (1, 2, 3):
            continue
        slot_dir = manifest_path.parent
        candidates = sorted(
            (p for p in slot_dir.glob("FM27_Analysis_*") if p.is_dir()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if not candidates:
            continue
        export_dir = candidates[0]
        scope = read_json(export_dir / "first-team-scope.json", {})
        if as_int(scope.get("team_id")) != team_id or as_int(scope.get("club_uid")) != club_uid:
            raise RuntimeError(f"First-team scope mismatch for {manifest_path.name}")
        fixtures = read_json(export_dir / "fixtures.json", [])
        if not isinstance(fixtures, list):
            raise RuntimeError(f"fixtures.json is not a list for {manifest_path}")
        trials.append({
            "tactic_name": tactic,
            "trial": trial,
            "source_asset": manifest.get("source_asset", ""),
            "source_sha256": manifest.get("sha256", ""),
            "source_size_bytes": as_int(manifest.get("size_bytes")),
            "game_date": str((read_json(export_dir / "save-info.json", {}) or {}).get("game_date") or ""),
            "slot_dir": slot_dir,
            "export_dir": export_dir,
            "fixtures": fixtures,
        })

    trials.sort(key=lambda x: (x["tactic_name"].casefold(), x["trial"]))
    if len(trials) != 6:
        raise RuntimeError(f"Expected six complete exports for comparison; discovered {len(trials)}.")
    groups: dict[str, list[int]] = defaultdict(list)
    for item in trials:
        groups[item["tactic_name"]].append(item["trial"])
    if len(groups) != 2 or any(sorted(values) != [1, 2, 3] for values in groups.values()):
        raise RuntimeError("Comparison requires exactly two tactics with trials -1, -2 and -3.")
    return trials


def analyze_trial(item: dict[str, Any], team_id: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    export_dir: Path = item["export_dir"]
    fixtures = item["fixtures"]
    matches: list[dict[str, Any]] = []

    for fixture in fixtures:
        comp = as_int(fixture.get("competition_id"))
        home_id = as_int(fixture.get("home_team_id"))
        away_id = as_int(fixture.get("away_team_id"))
        if comp not in FORMAL_COMPETITIONS or team_id not in (home_id, away_id) or not truthy(fixture.get("played")):
            continue
        is_home = home_id == team_id
        opponent_id = away_id if is_home else home_id
        team_goals = as_int(fixture.get("home_goals" if is_home else "away_goals"))
        opponent_goals = as_int(fixture.get("away_goals" if is_home else "home_goals"))
        if team_goals is None or opponent_goals is None:
            result = "?"
            points = None
        elif team_goals > opponent_goals:
            result, points = "W", 3
        elif team_goals == opponent_goals:
            result, points = "D", 1
        else:
            result, points = "L", 0
        opponent_name = fixture.get("away_club_short_name" if is_home else "home_club_short_name") or fixture.get("away_club_name" if is_home else "home_club_name") or ""
        row = {
            "tactic_name": item["tactic_name"], "trial": item["trial"],
            "source_asset": item["source_asset"],
            "date": fixture.get("date", ""),
            "competition_id": comp, "competition_name": fixture.get("competition_name", ""),
            "stage_id": fixture.get("stage_id"), "round": fixture.get("round"),
            "home_away": "主场" if is_home else "客场",
            "opponent_team_id": opponent_id, "opponent": opponent_name,
            "team_goals": team_goals, "opponent_goals": opponent_goals,
            "result": result, "points": points,
            "fixture_key": match_key(comp, fixture.get("stage_id"), fixture.get("round"), opponent_id, is_home, fixture.get("date")),
        }
        matches.append(row)

    match_csv = read_csv(export_dir / "player-match-report-formal-all.csv")
    match_groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in match_csv:
        comp = as_int(row.get("competition_id"))
        if comp not in FORMAL_COMPETITIONS:
            continue
        home_away = str(row.get("home_away") or "")
        is_home = home_away in {"主场", "Home", "home", "H"}
        key = match_key(
            comp, row.get("stage_id"), row.get("round"),
            row.get("opponent_team_id"), is_home, row.get("date"),
        )
        match_groups[key].append(row)

    team_metrics_by_key: dict[str, dict[str, Any]] = {}
    for key, rows in match_groups.items():
        metrics: dict[str, Any] = {}
        for field in TEAM_SUM_FIELDS:
            value = as_float(first_present(rows, field))
            if value is not None:
                metrics[field] = value
        team_metrics_by_key[key] = metrics

    for match in matches:
        match.update(team_metrics_by_key.get(match["fixture_key"], {}))

    wins = sum(1 for row in matches if row["result"] == "W")
    draws = sum(1 for row in matches if row["result"] == "D")
    losses = sum(1 for row in matches if row["result"] == "L")
    scored = [row for row in matches if row["team_goals"] is not None and row["opponent_goals"] is not None]
    gf = sum(int(row["team_goals"]) for row in scored)
    ga = sum(int(row["opponent_goals"]) for row in scored)
    points = sum(int(row["points"]) for row in matches if row["points"] is not None)
    clean_sheets = sum(1 for row in scored if row["opponent_goals"] == 0)
    failed_to_score = sum(1 for row in scored if row["team_goals"] == 0)

    home_rows = [row for row in matches if row["home_away"] == "主场"]
    away_rows = [row for row in matches if row["home_away"] == "客场"]
    def split_pack(rows: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "matches": len(rows),
            "wins": sum(1 for row in rows if row["result"] == "W"),
            "draws": sum(1 for row in rows if row["result"] == "D"),
            "losses": sum(1 for row in rows if row["result"] == "L"),
            "points": sum(int(row["points"]) for row in rows if row["points"] is not None),
            "goals_for": sum(int(row["team_goals"]) for row in rows if row["team_goals"] is not None),
            "goals_against": sum(int(row["opponent_goals"]) for row in rows if row["opponent_goals"] is not None),
        }

    player_rows = match_csv
    identified_rows = [row for row in player_rows if as_int(row.get("player_uid")) is not None and str(row.get("player_name") or "").strip()]
    player_totals: dict[tuple[str, str], dict[str, Any]] = {}
    for row in identified_rows:
        uid = str(row.get("player_uid") or "")
        name = str(row.get("player_name") or "")
        key = (uid, name)
        target = player_totals.setdefault(key, {
            "tactic_name": item["tactic_name"], "trial": item["trial"],
            "player_uid": uid, "player_name": name, "appearances": 0,
            "minutes": 0, "goals": 0, "assists": 0, "passes_attempted": 0,
            "passes_completed": 0, "ratings": [], "rating_rows": 0,
        })
        target["appearances"] += 1
        for field in ("minutes", "goals", "assists", "passes_attempted", "passes_completed"):
            value = as_int(row.get(field))
            if value is not None:
                target[field] += value
        rating = as_float(row.get("rating"))
        if rating is not None:
            target["ratings"].append(rating)
            target["rating_rows"] += 1

    player_summary: list[dict[str, Any]] = []
    for target in player_totals.values():
        ratings = target.pop("ratings")
        target["average_rating"] = numeric_mean(ratings)
        target["rating_rows"] = target["rating_rows"]
        target["pass_completion_pct"] = (
            round(100 * target["passes_completed"] / target["passes_attempted"], 2)
            if target["passes_attempted"] else None
        )
        player_summary.append(target)

    loss_draw_rows: list[dict[str, Any]] = []
    match_index = {row["fixture_key"]: row for row in matches}
    for key, rows in match_groups.items():
        context = match_index.get(key)
        if not context or context["result"] not in {"L", "D"}:
            continue
        for row in rows:
            uid = row.get("player_uid") or ""
            name = row.get("player_name") or ""
            is_identified = bool(str(uid).strip() and str(name).strip())
            loss_draw_rows.append({
                "tactic_name": item["tactic_name"], "trial": item["trial"],
                "date": context["date"], "competition_name": context["competition_name"],
                "round": context["round"], "home_away": context["home_away"],
                "opponent": context["opponent"],
                "score": f'{context["team_goals"]}-{context["opponent_goals"]}',
                "result": context["result"],
                "player_uid": uid, "player_name": name if is_identified else "身份未确认",
                "identity_status": row.get("identity_status") or ("identified" if is_identified else "unresolved"),
                "minutes": as_int(row.get("minutes")),
                "rating": as_float(row.get("rating")),
                "goals": as_int(row.get("goals")),
                "assists": as_int(row.get("assists")),
                "passes_attempted": as_int(row.get("passes_attempted")),
                "passes_completed": as_int(row.get("passes_completed")),
                "shots": as_int(row.get("shots")),
                "shots_on_target": as_int(row.get("shots_on_target")),
                "expected_goals": as_float(row.get("expected_goals")),
                "tackles_attempted": as_int(row.get("tackles_attempted")),
                "tackles_completed": as_int(row.get("tackles_completed")),
            })

    overall_season_rows = [
        row for row in read_csv(export_dir / "player-season-stats.csv")
        if as_int(row.get("team_id")) == team_id and str(row.get("kind") or "").lower() == "overall"
    ]
    season_players: list[dict[str, Any]] = []
    for row in overall_season_rows:
        cooked: dict[str, Any] = {
            "tactic_name": item["tactic_name"], "trial": item["trial"],
            "player_uid": row.get("player_uid", ""), "player_name": row.get("player_name", ""),
        }
        for field in PLAYER_SUM_FIELDS:
            value = as_int(row.get(field))
            if value is not None:
                cooked[field] = value
        for field in ("average_rating", "rating"):
            value = as_float(row.get(field))
            if value is not None:
                cooked[field] = value
        season_players.append(cooked)

    report_summary = read_json(export_dir / "player-match-report-formal-summary.json", {}) or {}
    identity_audit = read_json(export_dir / "player-report-identity-audit.json", {}) or {}
    compatibility = read_json(export_dir / "team-match-stats-compatibility.json", {}) or {}
    scope = read_json(export_dir / "first-team-scope.json", {}) or {}
    validation = read_json(export_dir / "validation.json", {}) or {}

    team_metric_means = {}
    for field in TEAM_SUM_FIELDS:
        vals = [as_float(row.get(field)) for row in matches]
        clean = [v for v in vals if v is not None]
        if clean:
            team_metric_means[field] = numeric_mean(clean)

    summary = {
        "tactic_name": item["tactic_name"], "trial": item["trial"],
        "source_asset": item["source_asset"], "source_sha256": item["source_sha256"],
        "source_size_bytes": item["source_size_bytes"], "game_date": item["game_date"],
        "matches": len(matches), "matches_with_score": len(scored),
        "unknown_score_matches": len(matches) - len(scored),
        "wins": wins, "draws": draws, "losses": losses,
        "points": points, "goals_for": gf, "goals_against": ga, "goal_difference": gf - ga,
        "points_per_game": round(points / len(matches), 4) if matches else None,
        "win_rate_pct": round(wins * 100 / len(matches), 2) if matches else None,
        "goals_for_per_game": round(gf / len(matches), 3) if matches else None,
        "goals_against_per_game": round(ga / len(matches), 3) if matches else None,
        "clean_sheets": clean_sheets, "failed_to_score": failed_to_score,
        "home": split_pack(home_rows), "away": split_pack(away_rows),
        "team_match_metrics_mean": team_metric_means,
        "player_report": {
            "expected_fixtures": report_summary.get("expected_fixtures"),
            "detailed_reports_found": report_summary.get("detailed_reports_found"),
            "identified_appearances": report_summary.get("identified_appearances"),
            "unresolved_appearances": report_summary.get("unresolved_appearances"),
            "team_total_reconciliation": report_summary.get("team_total_reconciliation"),
            "identity_audit_status": identity_audit.get("status") or identity_audit.get("validation_status"),
        },
        "team_match_stats_compatibility": compatibility,
        "first_team_scope": scope,
        "validation": validation,
    }
    return summary, matches, loss_draw_rows, {"players": player_summary, "season_players": season_players}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--team-id", type=int, default=539)
    parser.add_argument("--club-uid", type=int, default=680)
    args = parser.parse_args()

    trials = discover_trials(args.runs_root.resolve(), args.team_id, args.club_uid)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    trial_summaries: list[dict[str, Any]] = []
    all_matches: list[dict[str, Any]] = []
    all_loss_draw_rows: list[dict[str, Any]] = []
    all_player_rows: list[dict[str, Any]] = []
    all_season_player_rows: list[dict[str, Any]] = []
    full_results: list[dict[str, Any]] = []

    for item in trials:
        summary, matches, loss_draw_rows, player_data = analyze_trial(item, args.team_id)
        trial_summaries.append(summary)
        all_matches.extend(matches)
        all_loss_draw_rows.extend(loss_draw_rows)
        all_player_rows.extend(player_data["players"])
        all_season_player_rows.extend(player_data["season_players"])
        full_results.append({
            "summary": summary,
            "matches": matches,
            "loss_draw_player_performance": loss_draw_rows,
            "players": player_data["players"],
            "season_players": player_data["season_players"],
            "export_dir": str(item["export_dir"]),
        })

    tactic_names = sorted({x["tactic_name"] for x in trial_summaries}, key=str.casefold)
    metric_fields = [
        "matches", "wins", "draws", "losses", "points", "goals_for",
        "goals_against", "goal_difference", "points_per_game", "win_rate_pct",
        "goals_for_per_game", "goals_against_per_game", "clean_sheets", "failed_to_score",
    ]
    tactic_summaries: list[dict[str, Any]] = []
    for tactic in tactic_names:
        group = [row for row in trial_summaries if row["tactic_name"] == tactic]
        packed: dict[str, Any] = {"tactic_name": tactic, "trials": len(group)}
        for metric in metric_fields:
            info = stats_pack([as_float(row.get(metric)) for row in group])
            packed[metric + "_mean"] = info["mean"]
            packed[metric + "_stdev"] = info["stdev"]
            packed[metric + "_min"] = info["min"]
            packed[metric + "_max"] = info["max"]
        packed["trial_results"] = [
            {"trial": row["trial"], "points_per_game": row["points_per_game"],
             "goal_difference": row["goal_difference"], "wins": row["wins"],
             "draws": row["draws"], "losses": row["losses"]}
            for row in sorted(group, key=lambda x: x["trial"])
        ]
        tactic_summaries.append(packed)

    tactic_deltas: dict[str, Any] = {}
    if len(tactic_summaries) == 2:
        first, second = tactic_summaries
        for metric in ("points_per_game", "goal_difference", "wins", "draws", "losses", "goals_for", "goals_against", "clean_sheets"):
            a = first.get(metric + "_mean")
            b = second.get(metric + "_mean")
            tactic_deltas[metric] = (a - b) if a is not None and b is not None else None
        ppg_a = first.get("points_per_game_mean")
        ppg_b = second.get("points_per_game_mean")
        if ppg_a is None or ppg_b is None or abs(ppg_a - ppg_b) < 0.0001:
            provisional_leader = "未分出高下"
        else:
            provisional_leader = first["tactic_name"] if ppg_a > ppg_b else second["tactic_name"]
        tactic_deltas["points_per_game_leader"] = provisional_leader
        tactic_deltas["comparison_order"] = [first["tactic_name"], second["tactic_name"]]

    fixture_sets: dict[str, set[str]] = {}
    for item in full_results:
        key = f'{item["summary"]["tactic_name"]}#{item["summary"]["trial"]}'
        fixture_sets[key] = {row["fixture_key"] for row in item["matches"]}
    fixture_counts = {k: len(v) for k, v in fixture_sets.items()}
    common_same_tactic: dict[str, int] = {}
    for tactic in tactic_names:
        sets = [fixture_sets[f"{tactic}#{trial}"] for trial in (1, 2, 3)]
        common_same_tactic[tactic] = len(set.intersection(*sets)) if sets else 0

    player_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in all_player_rows:
        player_groups[(row["tactic_name"], str(row["player_uid"]), str(row["player_name"]))].append(row)
    player_comparison: list[dict[str, Any]] = []
    for (tactic, uid, name), rows in sorted(player_groups.items()):
        out: dict[str, Any] = {
            "tactic_name": tactic, "player_uid": uid, "player_name": name,
            "trials_present": len({row["trial"] for row in rows}),
        }
        for field in ("appearances", "minutes", "goals", "assists", "passes_attempted", "passes_completed"):
            per_run = [as_float(row.get(field)) for row in rows]
            values = [v for v in per_run if v is not None]
            out[field + "_mean_per_trial"] = numeric_mean(values)
            out[field + "_total_across_trials"] = sum(values) if values else 0
        ratings = [as_float(row.get("average_rating")) for row in rows]
        out["average_rating_mean"] = numeric_mean([v for v in ratings if v is not None])
        player_comparison.append(out)

    write_csv(args.output_dir / "trial-summary.csv", trial_summaries)
    write_csv(args.output_dir / "tactic-average-summary.csv", tactic_summaries)
    write_csv(args.output_dir / "match-results-by-trial.csv", all_matches)
    write_csv(args.output_dir / "loss-draw-match-player-performance.csv", all_loss_draw_rows)
    write_csv(args.output_dir / "player-season-comparison.csv", player_comparison)
    write_csv(args.output_dir / "player-season-aggregate-source.csv", all_season_player_rows)

    fixture_trial_rows: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for match in all_matches:
        fixture_trial_rows[(match["tactic_name"], match["fixture_key"])].append(match)
    fixture_spread_rows: list[dict[str, Any]] = []
    for (tactic, fixture_id), rows in sorted(fixture_trial_rows.items()):
        if len(rows) < 2:
            continue
        fixture_spread_rows.append({
            "tactic_name": tactic, "fixture_key": fixture_id,
            "trials_present": len(rows),
            "opponent": rows[0]["opponent"],
            "home_away": rows[0]["home_away"],
            "results_across_trials": "/".join(f'{row["trial"]}:{row["result"]} {row["team_goals"]}-{row["opponent_goals"]}' for row in sorted(rows, key=lambda x: x["trial"])),
            "points_mean": numeric_mean([as_float(row["points"]) for row in rows]),
            "goals_for_mean": numeric_mean([as_float(row["team_goals"]) for row in rows]),
            "goals_against_mean": numeric_mean([as_float(row["opponent_goals"]) for row in rows]),
        })
    write_csv(args.output_dir / "same-fixture-variation.csv", fixture_spread_rows)

    comparison = {
        "analysis_version": "1.0",
        "team_id": args.team_id,
        "club_uid": args.club_uid,
        "trials": trial_summaries,
        "tactic_comparison": tactic_summaries,
        "tactic_deltas_first_minus_second": tactic_deltas,
        "fixture_set_counts": fixture_counts,
        "common_fixtures_across_three_trials_by_tactic": common_same_tactic,
        "loss_draw_matches": len({(x["tactic_name"], x["trial"], x["date"], x["competition_name"], x["opponent"]) for x in all_loss_draw_rows}),
        "loss_draw_player_rows": len(all_loss_draw_rows),
        "notes": [
            "Each -1, -2 and -3 save is treated as an independent full-season simulation trial.",
            "Different scores among repeated tests are expected; they are not treated as data corruption.",
            "Team results are calculated from played first-team fixtures in formal competitions 7, 637, 661 and 662.",
            "Team-match metrics are taken from the first non-empty repeated team row in each detailed formal match report.",
            "Player match outputs include unresolved identities explicitly; unresolved rows are not guessed or assigned names.",
            "Player comparison uses identified players from player-match-report-formal-all.csv; the native overall season rows are preserved separately.",
            "Use three-run means and standard deviations as descriptive evidence only; three trials are not enough for statistical significance claims.",
            "The parser does not reliably decode the actual selected role and live personal instructions; raw settings and position evidence remain in the individual exports.",
            "The actual tactic may change during the season. The current tactics.json is a save snapshot and does not prove historical instructions for every match."
        ],
    }
    write_json(args.output_dir / "comparison-summary.json", comparison)

    lines = [
        "# FM27 两套战术六次完整赛季对比",
        "",
        f"球队范围：team_id={args.team_id}, club_uid={args.club_uid}",
        "统计范围：正式比赛 competition_id 7、637、661、662。",
        "",
        "## 三次测试均值",
        "",
        "| 战术 | 场均积分 | 平均胜 | 平均平 | 平均负 | 平均进球 | 平均失球 | 平均净胜球 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    def fmt(value: Any) -> str:
        return "—" if value is None else f"{value:.2f}" if isinstance(value, (int, float)) else str(value)
    for row in tactic_summaries:
        lines.append(
            f'| {row["tactic_name"]} | {fmt(row.get("points_per_game_mean"))} | '
            f'{fmt(row.get("wins_mean"))} | {fmt(row.get("draws_mean"))} | {fmt(row.get("losses_mean"))} | '
            f'{fmt(row.get("goals_for_mean"))} | {fmt(row.get("goals_against_mean"))} | {fmt(row.get("goal_difference_mean"))} |'
        )
    lines += ["", "## 每次测试单独结果", "", "| 战术 | 测试 | 场次 | 胜-平-负 | 积分 | 进球 | 失球 | 净胜球 | 场均积分 |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in trial_summaries:
        lines.append(
            f'| {row["tactic_name"]} | {row["trial"]} | {row["matches"]} | '
            f'{row["wins"]}-{row["draws"]}-{row["losses"]} | {row["points"]} | '
            f'{row["goals_for"]} | {row["goals_against"]} | {row["goal_difference"]} | {fmt(row["points_per_game"])} |'
        )
    lines += [
        "",
        "## 输球与平局逐场球员表现",
        "",
        f"共整理 {comparison['loss_draw_matches']} 场输球/平局，{len(all_loss_draw_rows)} 条球员行，详见 loss-draw-match-player-performance.csv。",
        "",
        "## 方法与限制",
        "",
    ]
    lines.extend(f"- {note}" for note in comparison["notes"])
    (args.output_dir / "comparison-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("FM27 SIX-TRIAL TACTIC COMPARISON COMPLETE")
    print(f"Tactics: {len(tactic_names)} | full-season trials: {len(trial_summaries)}")
    for row in tactic_summaries:
        print(f'{row["tactic_name"]}: mean PPG={row["points_per_game_mean"]}, mean W-D-L={row["wins_mean"]}-{row["draws_mean"]}-{row["losses_mean"]}, mean GD={row["goal_difference_mean"]}')
    print(f"Loss/draw player rows: {len(all_loss_draw_rows)}")
    print(f"Output: {args.output_dir}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        import sys
        print(f"COMPARISON ANALYSIS ERROR: {exc}", file=sys.stderr)
        raise
