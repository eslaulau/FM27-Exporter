# FM27 managed first-team + opponent match-stat exporter v1.5.0

## Scope and behavior

- Read-only parsing of FM27 .fm saves; the source save is never modified.
- Installs and verifies pinned `fmsave==0.12.4`; no automatic parser upgrades.
- Automatically resolves the managed club from the save's `managed_clubs()` entry.
- Automatically resolves the managed first-team ID from the managed club's owned team at slot 0. If exactly one managed club and exactly one first team cannot be established, export stops rather than guessing.
- Exports only fixtures involving the managed first team.
- Retains BOTH home and away rows from `team-match-stats.json` for those fixtures, and validates exactly one home row plus one away row per match.
- Retains managed first-team player profiles, selections, player match rows and season rows. Historical players are retained in player-match data only when their record confirms actual minutes.
- Retains opponent identity, competition, date, venue, score and opponent team-level match statistics only in direct matches against the managed first team.
- Excludes opponent player profiles, opponent player match records and unrelated matches.
- Tactical configurations, set-piece configurations, current tactic slots, historical tactic inference and role inference are deliberately not exported. The user supplies the tactic used for each match.
- Detailed player match reports for formal competition IDs 7, 637, 661 and 662; excludes non-competitive ID 131.
- Unresolved anonymous match rows remain unresolved; the exporter does not guess player identity.

## Compatibility note

For FM27 build 27.0.1+2494687 and `match_stats_cfg` schema 6, an explicitly labelled experimental compatibility path is included. It borrows the registered 27.0.0 schema-6 layout and is not an upstream verification claim. Inspect `team-match-stats-compatibility.json` when present and compare its values against an in-game match report.

## Local use

Requires Windows PowerShell 5.1 and Python 3.12+.

```powershell
python -m pip install --disable-pip-version-check fmsave==0.12.4
.\Run_FM27_Formal_Season_Export_v1.5.0.ps1 -SavePath "D:\FM27\games\your-save.fm"
```

If `-SavePath` is omitted, the script tries the standard FM27 save folder under the current Windows user's Documents directory.

## Reuse mode

`-ReuseExportDir` reuses an existing compatible v1.5.0 export folder to regenerate detailed formal player reports. Its `first-team-scope.json` supplies the dynamic club UID, club name and first-team ID.

## Cloud use

The public-save Actions workflow is a separate six-save tactic-comparison pipeline. This v1.5.0 local exporter is not silently substituted into that pipeline; the latter still has its own trial manifest and comparison assumptions.

## Validate results

Review `managed-club.json`, `validation.json`, `first-team-scope.json`, `player-report-identity-audit.json`, `team-match-stats-compatibility.json` (if present), `export-warnings.txt` (if present), and `native-diagnostics.txt`.

A completed script process does not mean every exported field has been fully validated. Paired-row checks prove two-sided structure and fixture joins, not semantic accuracy of every decoded statistic.
