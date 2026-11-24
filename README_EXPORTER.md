# FM27 managed first-team + opponent match-stat exporter v1.5.0

## Official execution: manually triggered GitHub Actions cloud workflow

v1.5.0 runs on a GitHub-hosted Windows runner. The active workflow is [fm27-v1.5-cloud-export.yml](.github/workflows/fm27-v1.5-cloud-export.yml).

1. Upload the source `.fm` save to Release `fm27-saves`.
2. When you request an export, start **Actions → FM27 v1.5.0 Cloud Season Export → Run workflow**.
3. Supply the exact `.fm` asset filename. One workflow run exports exactly one save; automatic Release publishing triggers are disabled.
4. Before parsing, the workflow checks the downloaded file's byte length and SHA-256 against the source Release asset metadata. Each save is downloaded and exported inside its own isolated working directory.
5. The complete, uncompressed report folder is committed to `season-reports/<save-name>/<workflow-run-id>/` on the repository's default branch. Repeated exports are stored in separate run-ID folders. No ZIP is created and no report Release asset is uploaded.
6. The workflow verifies the committed report files against their Git blob IDs. Failure diagnostics are retained for 14 days as a workflow artifact.

The GitHub-hosted Windows runner executes the v1.5.0 PowerShell exporter. The workflow uses the pinned `fmsave==0.14.3` dependency; automatic parser upgrades are disabled. Users do not need local Python, PowerShell, or a local export installation.

## Scope and behavior

- Read-only parsing of FM27 .fm saves; the source save is never modified.
- Automatically resolves the managed club from the save's `managed_clubs()` entry.
- Automatically resolves the managed first-team ID from the managed club's owned team at slot 0. If exactly one managed club and exactly one first team cannot be established, export stops rather than guessing.
- Exports only fixtures involving the managed first team.
- Retains BOTH home and away rows from `team-match-stats.json` for those fixtures, and validates exactly one home row plus one away row per match.
- Retains managed first-team player profiles, selections, player match rows and season rows. Historical players are retained in player-match data only when their record confirms actual minutes.
- Retains opponent identity, competition, date, venue, score and opponent team-level match statistics only in direct matches against the managed first team.
- Excludes opponent player profiles, opponent player records and unrelated matches.
- Tactical configurations, set-piece configurations, current tactic slots, historical tactic inference and role inference are deliberately not exported. The user supplies the tactic used for each match.
- Detailed player match reports for formal competitions discovered from the managed team's save-local fixture rules; match-rule family 1 (friendlies/pre-season) is excluded. Competition IDs are never hardcoded.
- Unresolved anonymous match rows remain unresolved; the exporter does not guess player identity.

## Compatibility note

For FM27 build 27.0.1+2494687 and `match_stats_cfg` schema 6, fmsave 0.14.3 can try a shared registered FM27 schema-6 layout even though this exact build remains unregistered. The player-report helper explicitly selects the registered 27.0.0 schema-6 layout. This is structural compatibility, not an upstream build-registration or in-game field-verification claim. Inspect `team-match-stats-compatibility.json` and compare its values against in-game match reports.

## Report location and validation

Browse the generated report folders under [season-reports/](season-reports/). Each export is stored as:

```
season-reports/
  <save-name>/
    <workflow-run-id>/
      FM27_Analysis_<timestamp>/
        save-info.json
        validation.json
        first-team-scope.json
        fixtures.json
        team-match-stats.json
        players.json
        ...
```

Review `cloud-export-manifest.json`, `cloud-export-summary.json`, `managed-club.json`, `validation.json`, `first-team-scope.json`, `player-report-identity-audit.json`, `team-match-stats-compatibility.json` (if present), `export-warnings.txt` (if present), and `native-diagnostics.txt`.

A completed workflow means the source asset integrity check, required output checks, dynamic first-team scope check, repository commit, and Git blob readback checks passed. Paired-row checks prove two-sided structure and fixture joins, not semantic accuracy of every decoded statistic.

## Local development

The PowerShell script and Python filter remain in the repository for maintenance and CI validation. Local execution is not the supported user-facing export procedure.
