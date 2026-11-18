#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Accumulate FM27 named per-player match history across repeated exports.

The game/parser keeps only a rolling ~20 match records per player/team spell,
shared across competitions. This tool preserves rows before they roll off.
It does not fabricate history and refuses snapshots whose overlapping played
fixture scores conflict with the existing archive (likely another save branch).
"""
from __future__ import annotations
import argparse, json, os, shutil, sys, tempfile
from pathlib import Path
from datetime import datetime, timezone

FORMAL = {7, 637, 661, 662}
STABLE_FIELDS = (
    "player_uid", "player_name", "date", "competition_id", "opponent_team_id",
    "has_stats", "position_code", "minutes", "entered_at_minute", "left_at_minute", "goals",
    "assists", "rating", "passes_attempted", "passes_completed",
)

def read_json(path: Path):
    with path.open('r', encoding='utf-8-sig') as f:
        return json.load(f)

def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
            json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write('\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def intv(v, default=None):
    try: return int(v)
    except (TypeError, ValueError): return default

def fixture_key(comp, date, opp):
    return f"{int(comp)}|{date}|{int(opp)}"

def fingerprint(f, team_id):
    home, away = intv(f.get('home_team_id')), intv(f.get('away_team_id'))
    if team_id not in (home, away): return None
    opp = away if home == team_id else home
    return {
        'competition_id': intv(f.get('competition_id')),
        'date': str(f.get('date') or ''),
        'opponent_team_id': opp,
        'home_team_id': home,
        'away_team_id': away,
        'home_goals': intv(f.get('home_goals')),
        'away_goals': intv(f.get('away_goals')),
        'played': bool(f.get('played')),
    }

VERSIONED_OPTIONAL_FIELDS = ("entered_at_minute",)


def stable_projection(row):
    return {k: row.get(k) for k in STABLE_FIELDS}


def stable_conflicts(previous, incoming):
    """Allow additive fields absent from legacy archives; never ignore an existing value conflict."""
    for field in STABLE_FIELDS:
        if field in VERSIONED_OPTIONAL_FIELDS and field not in previous:
            continue
        if previous.get(field) != incoming.get(field):
            return True
    return False

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--export-dir', required=True, type=Path)
    p.add_argument('--archive-dir', required=True, type=Path)
    p.add_argument('--team-id', type=int, default=539)
    p.add_argument('--club-uid', type=int, default=680)
    a = p.parse_args()
    export_dir = a.export_dir.resolve()
    archive_dir = a.archive_dir.resolve()
    required = ['first-team-scope.json','fixtures.json','player-match-stats.json','save-info.json']
    missing = [n for n in required if not (export_dir/n).is_file()]
    if missing:
        raise RuntimeError('Missing export inputs: '+', '.join(missing))
    scope = read_json(export_dir/'first-team-scope.json')
    if intv(scope.get('team_id')) != a.team_id or intv(scope.get('club_uid')) != a.club_uid:
        raise RuntimeError('First-team scope mismatch; refusing to mix another team/club.')
    save_info = read_json(export_dir/'save-info.json')
    if save_info.get('game') != 'FM27':
        raise RuntimeError('This archive accepts FM27 exports only.')
    fixtures = read_json(export_dir/'fixtures.json')
    stats = read_json(export_dir/'player-match-stats.json')
    if not isinstance(fixtures, list) or not isinstance(stats, list):
        raise RuntimeError('fixtures.json and player-match-stats.json must be JSON arrays.')

    fingerprints = {}
    for f in fixtures:
        fp = fingerprint(f, a.team_id)
        if not fp or not fp['played'] or fp['competition_id'] not in FORMAL:
            continue
        if fp['home_goals'] is None or fp['away_goals'] is None or not fp['date']:
            continue
        key = fixture_key(fp['competition_id'], fp['date'], fp['opponent_team_id'])
        prior = fingerprints.get(key)
        if prior and prior != fp:
            raise RuntimeError(f'Duplicate fixture fingerprint conflicts within this export: {key}')
        fingerprints[key] = fp

    archive_path = archive_dir/'player-match-history-archive.json'
    manifest_path = archive_dir/'archive-manifest.json'
    if archive_path.exists() != manifest_path.exists():
        raise RuntimeError('Archive data/manifest pair is incomplete; do not overwrite it manually.')
    if archive_path.exists():
        records_list = read_json(archive_path)
        manifest = read_json(manifest_path)
        if intv(manifest.get('team_id')) != a.team_id or intv(manifest.get('club_uid')) != a.club_uid:
            raise RuntimeError('Existing archive belongs to another team/club.')
        old_fps = manifest.get('fixture_fingerprints') or {}
        conflicts = [k for k,fp in fingerprints.items() if k in old_fps and old_fps[k] != fp]
        if conflicts:
            raise RuntimeError(
                'SAVE-BRANCH CONFLICT: '+str(len(conflicts))+
                ' overlapping first-team formal fixture result(s) differ from the archive. '
                'No data was changed. Use a separate archive directory for another career/save branch. '
                'Examples: '+', '.join(conflicts[:8])
            )
    else:
        records_list = []
        old_fps = {}
        manifest = {
            'archive_version': 2,
            'game': 'FM27',
            'team_id': a.team_id,
            'club_uid': a.club_uid,
            'formal_competition_ids': sorted(FORMAL),
            'excluded_competition_ids': [131],
            'fixture_fingerprints': {},
            'source_snapshots': [],
            'row_conflicts': [],
        }

    records = {}
    for row in records_list:
        try:
            key = fixture_key(row['competition_id'], row['date'], row['opponent_team_id'])+'|'+str(int(row['player_uid']))
        except (KeyError, TypeError, ValueError):
            continue
        records[key] = row

    imported = 0
    matched_fixture_keys = set()
    duplicate_conflicts = []
    ignored = 0
    for row in stats:
        try:
            uid = int(row['player_uid'])
            comp = int(row['competition_id'])
            date = str(row['date'])
            opp = int(row['opponent_team_id'])
        except (KeyError, TypeError, ValueError):
            ignored += 1
            continue
        if comp not in FORMAL:
            ignored += 1
            continue
        fk = fixture_key(comp, date, opp)
        if fk not in fingerprints:
            ignored += 1
            continue
        matched_fixture_keys.add(fk)
        record_key = fk+'|'+str(uid)
        prior = records.get(record_key)
        row_clean = dict(row)
        if prior is None:
            records[record_key] = row_clean
            imported += 1
        elif stable_conflicts(prior, row_clean):
            duplicate_conflicts.append(record_key)
        else:
            # Upgrade older 0.12.2 archive rows with fields introduced by 0.12.4.
            for field in VERSIONED_OPTIONAL_FIELDS:
                if field not in prior and field in row_clean:
                    prior[field] = row_clean[field]

    if duplicate_conflicts:
        raise RuntimeError(
            'PLAYER-ROW CONFLICT: same player/match key has different named-history values. '
            'No archive data was changed. Examples: '+', '.join(duplicate_conflicts[:8])
        )

    merged_fps = dict(old_fps)
    merged_fps.update(fingerprints)
    snapshot_id = str(export_dir.name)
    snapshots = list(manifest.get('source_snapshots') or [])
    if not any(x.get('snapshot_id') == snapshot_id for x in snapshots):
        snapshots.append({
            'snapshot_id': snapshot_id,
            'game_date': save_info.get('game_date'),
            'build': save_info.get('build'),
            'fmsave_version': save_info.get('fmsave_version'),
            'fixture_keys': len(fingerprints),
            'history_fixture_keys_in_snapshot': len(matched_fixture_keys),
            'rows_seen': len(stats),
            'rows_added': imported,
            'ignored_rows': ignored,
        })
    manifest.update({
        'archive_version': 2,
        'field_schema': 'v1.1-entered-at-minute',
        'updated_at_utc': datetime.now(timezone.utc).isoformat(),
        'fixture_fingerprints': merged_fps,
        'source_snapshots': snapshots,
        'record_count': len(records),
        'matched_fixture_key_count': len({k.rsplit('|',1)[0] for k in records}),
    })
    ordered = sorted(records.values(), key=lambda x:(int(x.get('competition_id') or 0),str(x.get('date') or ''),int(x.get('opponent_team_id') or 0),int(x.get('player_uid') or 0)))
    atomic_json(archive_path, ordered)
    atomic_json(manifest_path, manifest)
    # Copy a point-in-time view into the export so the recovery helper can use it.
    atomic_json(export_dir/'player-match-stats-history-archive.json', ordered)
    summary = {
        'archive_dir': str(archive_dir),
        'archive_rows': len(ordered),
        'archive_fixture_keys': manifest['matched_fixture_key_count'],
        'source_snapshots': len(snapshots),
        'rows_added_this_run': imported,
        'current_snapshot_history_fixture_keys': len(matched_fixture_keys),
        'current_snapshot_formal_fixture_keys': len(fingerprints),
        'ignored_rows': ignored,
        'branch_guard': 'passed',
    }
    atomic_json(export_dir/'player-match-history-archive-summary.json', summary)
    print('PLAYER MATCH HISTORY ARCHIVE OK')
    print(json.dumps(summary, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('ERROR: '+str(exc), file=sys.stderr)
        raise SystemExit(2)
