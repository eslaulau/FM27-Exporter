HISTORICAL EXPORT BUNDLE — NOT CURRENT GUIDANCE.
Generated with the retired v1.4.5 exporter and legacy first-team filter. The files below are preserved as originally exported. Fixed IDs, tactic/set-piece exports, position/role outputs and the old export scope do not describe current v1.5.0 behavior.
Current supported contract: see repository README_EXPORTER.md.

﻿FM27 FIRST-TEAM ONLY analysis export bundle v1.4.5 (formal competitions)
Default named player history uses a save-scoped route under FM27_PlayerMatchHistoryArchives beside the save file.
Overlapping fixture or named-row conflicts automatically fork a new save-specific archive branch; conflicting histories are never merged.
Parser version is pinned to fmsave==0.12.4; automatic upgrades are disabled.
Save path defaults to the configured FM27 2.fm; override with -SavePath when needed.
Optional -ReuseExportDir reuses an existing first-team export folder and regenerates only the detailed formal player reports.

Files include first-team fixtures, first-team own-side team-match-stats, player profiles/attributes,
first-team player-season-stats, first-team player-match-stats, tactics, set-pieces, selections,
save-info, parser validation and first-team-scope.json.
Per-player detailed match-report outputs: player-report-probe.json, player-match-report-identified.csv/json, player-match-report-unresolved.csv, player-match-report-formal-all.csv and player-match-report-formal-summary.json.
These detailed reports cover formal competitions 7, 637, 661 and 662; pre-season/non-competitive competition 131 is excluded.
The match-report helper performs a targeted read-only pass over match_stats_cfg with fmsave==0.12.4.
Identities use a persisted four-byte signature cache seeded from the validated full-season league report; cross-competition transfer limitations are recorded in the identity audit.
Unmapped player rows remain anonymous and are written to player-match-report-unresolved.csv.
Verified raw player-record offsets decode goals, assists, substitute entry/exit clocks, passes attempted and passes completed even when rolling named history is missing.
fmsave 0.12.4 adds PlayerMatchStats.entered_at_minute to named match history and PlayerSeasonStats.minutes_since_last_goal to overall club season stats.
Minutes are decoded from raw entry/exit clocks when match duration is verified by named-history votes, a unique exact season-category solution, or regular-time competition/stage rules.
Match ratings use the locally cross-validated uint16 little-endian field at raw-window +136 (statistics_anchor +36): hundredths divided by 100, rounded half-up to one decimal. Enable only after at least 25 exact same-match history checks pass with zero mismatches.
Rows with a confirmed 0-minute appearance are omitted from player-level match reports; team-total checks still use the full raw match report.
FM27 named match history is rolling (~20 rows per player/team spell across all competitions); preserve it by exporting regularly and keeping FM27_PlayerMatchHistoryArchive.
players.json contains only current first-team team_id 539 profiles; no reserve/youth profiles are kept.
Historical reserve/youth players are retained only on individual first-team match rows where they logged minutes; their full profiles and reserve statistics are excluded.
Reserve/youth match-sheet rows without minutes are removed per match, even for a guest who appeared in another match.
Opponent identity, competition, date, venue and score remain as match context only.
Opponent player profiles and opponent-side performance rows are excluded.
Additional named-player audit outputs: player-position-history.csv/json,
player-position-player-summary.csv, player-position-mask-evidence.csv,
player-position-role-code-audit.csv, player-current-tactic-slot-map.csv,
player-current-role-candidates.csv, player-current-role-candidate-summary.csv,
player-current-role-duty-permissions.csv, player-position-coverage.json and player-position-unmatched-joins.json.
The native catalog maps full current tactic masks to all 24 position IDs and lists eligible IP/OOP role candidates.
The role-duty permission file contains workbook-decoded combinations with editable/fixed-on/fixed-off options.
Candidate roles and permission lists are NOT the actual selected role or live personal-instruction values.
The save raw role bits do not uniquely identify the selected role; they are preserved, not guessed.
For FM27 27.0.1+2494687 with match_stats_cfg schema 6, fmsave 0.12.4 borrows the registered 27.0.0 schema-6 layout because 27.0.1 is not upstream-registered.
The generated team-match-stats-compatibility.json records the reader status, source layout, formal-fixture coverage, team totals and raw-field cross-checks for this save only.
A local compatibility pass does not change fmsave known_build and is not a claim of upstream verification for other saves/builds.
Named player history is joined to first-team fixtures by competition, date and opponent team ID.
Historical position and role_code values are preserved raw; provisional position alignment is checked
separately from the exact current tactic position ID. Selected role and current PI values remain undecoded.

IMPORTANT: FM27 builds newer than the parser registered build may be unverified.
Some fields or readers may be unavailable. Check validation.json and
native-diagnostics.txt before treating any exported data as complete.
FM27_FirstTeam_Filter_v1.2.2.py enforces strict first-team scope and per-match guest-minute filtering.
FM27_PlayerMatchReport_Recovery_v1.9_Formal.py reads each player signature at the statistics anchor minus 100 bytes and retains the full variable-length player record.
Raw verified offsets from the stored player-record window: goals +20, assists +56, left-at minute +67, entered-at minute +71, passes attempted +86 and passes completed +87.
Raw rating field: uint16 little-endian at raw-window +136 (statistics anchor +36), stored in hundredths and rounded half-up to one decimal after same-match history cross-validation.
Raw field extraction is cross-checked against named same-match history; duration solving uses exact season-category reconciliation only as a validation of fixture length, never to fill individual match statistics.
ReuseExportDir replays the existing raw player-report-probe.json and does not open the save for match_stats_cfg.
Cross-competition signature-cache transfer and same-match-history singleton inference are distinguished in player-report-identity-audit.json; conflicting candidates remain unresolved.
Individual goals, assists and pass totals are read from raw match records. Individual minutes are calculated from raw entry/exit clocks. Season aggregates only verify duration; they are never apportioned to players or matches.
A rating is not derived from the raw match-report schema in this build. The tool keeps any exact named-history rating and leaves missing ratings empty.
This tool reads the save only and never modifies it.
