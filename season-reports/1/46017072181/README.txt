FM27 managed first-team + opponent match-stat export bundle v1.5.0 (formal competitions)
Default named player history uses a save-scoped route under FM27_PlayerMatchHistoryArchives beside the save file.
Overlapping fixture or named-row conflicts automatically fork a new save-specific archive branch; conflicting histories are never merged.
Parser version is pinned to fmsave==0.14.3; automatic upgrades are disabled.
Save path defaults to the configured FM27 2.fm; override with -SavePath when needed.
Optional -ReuseExportDir reuses an existing first-team export folder and regenerates only the detailed formal player reports.

Files include managed first-team fixtures, both home and away team statistics for those fixtures, and first-team player profiles/attributes,
first-team player-season-stats, first-team player-match-stats and first-team selections,
managed-club.json, save-info, parser validation and first-team-scope.json.
Per-player detailed match-report outputs: player-report-probe.json, player-match-report-identified.csv/json, player-match-report-unresolved.csv, player-match-report-formal-all.csv and player-match-report-formal-summary.json.
Formal competitions are discovered dynamically from this save because competition IDs are save-local; friendly/pre-season match-rule family 1 is excluded.
Player-detail extraction is reconciled against reports retained by the native team-match-stats reader; not every played fixture remains stored in an FM27 save.
The match-report helper performs a targeted read-only pass over match_stats_cfg with fmsave==0.14.3.
Identities use a persisted four-byte signature cache seeded from the validated full-season league report; cross-competition transfer limitations are recorded in the identity audit.
Unmapped player rows remain anonymous and are written to player-match-report-unresolved.csv.
Verified raw player-record offsets decode goals, assists, substitute entry/exit clocks, passes attempted and passes completed even when rolling named history is missing.
The pinned fmsave version exposes PlayerMatchStats.entered_at_minute and PlayerSeasonStats.minutes_since_last_goal for named match history and overall club season stats.
Minutes are decoded from raw entry/exit clocks when match duration is verified by named-history votes, a unique exact season-category solution, or regular-time competition/stage rules.
Match ratings use a variant-aware uint16 little-endian hundredths field. The embedded report-record variant selects the raw-window offset; see rating_recovery.raw_window_offset and anchor_relative_offset in player-match-report-formal-summary.json. Enable only after at least 25 exact same-match history checks pass with zero mismatches.
Rows with a confirmed 0-minute appearance are omitted from player-level match reports; team-total checks still use the full raw match report.
FM27 named match history is rolling (~20 rows per player/team spell across all competitions); preserve it by exporting regularly and keeping FM27_PlayerMatchHistoryArchive.
Managed club and first-team ID are resolved from the save at runtime; no club/team ID is hardcoded.
players.json contains only current managed first-team profiles; no reserve/youth or opponent profiles are kept.
Historical reserve/youth players are retained only on individual first-team match rows where they logged minutes; their full profiles and reserve statistics are excluded.
Reserve/youth match-sheet rows without minutes are removed per match, even for a guest who appeared in another match.
Opponent identity, competition, date, venue and score remain as match context; opponent team-level statistics are retained for direct matches.
Opponent player profiles and unrelated opponent matches are excluded; opponent-side team statistics for direct matches are retained.
Tactical configurations, set-piece configurations, current tactic slots and historical tactic inference are deliberately not exported.
For save builds without an exact fmsave 0.14.3 registration, the helper records the borrowed registered schema-6 layout and embedded report-record variant. Local structural checks do not register the target build or independently verify every decoded field in-game.
The generated team-match-stats-compatibility.json records the reader status, borrowed layout, formal-fixture coverage, team totals and raw-field cross-checks for this save only.
A local compatibility pass does not change fmsave known_build and is not a claim of upstream verification for other saves/builds.
Named player history is joined to first-team fixtures by competition, date and opponent team ID.
Tactical configurations and inferred historical formations are not exported. User supplies the tactic used for each match.

IMPORTANT: FM27 builds newer than the parser registered build may be unverified.
Some fields or readers may be unavailable. Check validation.json and
native-diagnostics.txt before treating any exported data as complete.
FM27_FirstTeam_Filter_v1.3.0.py enforces dynamic managed first-team scope and paired home/away match statistics.
FM27_PlayerMatchReport_Recovery_v1.9_Formal.py reads each player signature at the statistics anchor minus 100 bytes and retains the full variable-length player record.
Raw verified offsets from the stored player-record window: goals +20, assists +56, left-at minute +67, entered-at minute +71, passes attempted +86 and passes completed +87.
Raw rating field: variant-aware uint16 little-endian hundredths; the selected raw-window and statistics-anchor offsets are recorded in player-match-report-formal-summary.json and follow the embedded report-record variant.
Raw field extraction is cross-checked against named same-match history; duration solving uses exact season-category reconciliation only as a validation of fixture length, never to fill individual match statistics.
ReuseExportDir replays the existing raw player-report-probe.json and does not open the save for match_stats_cfg.
Cross-competition signature-cache transfer and same-match-history singleton inference are distinguished in player-report-identity-audit.json; conflicting candidates remain unresolved.
Individual goals, assists and pass totals are read from raw match records. The player-goal audit reads raw_player_stats/goals from every unfiltered report row, never normalized metrics, and flags missing raw values as incomplete instead of treating them as zero. Individual minutes are calculated from raw entry/exit clocks. Season aggregates only verify duration; they are never apportioned to players or matches.
This tool reads the save only and never modifies it.
