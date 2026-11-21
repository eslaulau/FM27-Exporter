# FM27 managed first-team + opponent match-stat exporter v1.5.0

## Official execution: GitHub Actions cloud workflow

v1.5.0 is executed in the cloud, not as a required local PowerShell workflow. The active workflow is [fm27-v1.5-cloud-export.yml](.github/workflows/fm27-v1.5-cloud-export.yml).

- Publishing a GitHub Release tagged `fm27-saves` automatically triggers cloud export of its non-empty `.fm` assets.
- A manual run is available under **Actions → FM27 v1.5.0 Cloud Season Export → Run workflow**.
- Enter an exact `.fm` asset name to process one save; leave it blank to process all `.fm` assets in `fm27-saves`.
- The GitHub-hosted Windows runner executes this v1.5.0 PowerShell exporter and publishes report ZIPs to Release `fm27-exports`.
- Users do not need local Python, PowerShell, or a local export installation.

The workflow installs and verifies pinned `fmsave==0.12.4`; automatic parser upgrades are disabled.

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
- Detailed player match reports for formal competition IDs 7, 637, 661 and 662; excludes non-competitive ID 131.
- Unresolved anonymous match rows remain unresolved; the exporter does not guess player identity.

## Compatibility note

For FM27 build 27.0.1+2494687 and `match_stats_cfg` schema 6, an explicitly labelled experimental compatibility path is included. It borrows the registered 27.0.0 schema-6 layout and is not an upstream verification claim. Inspect `team-match-stats-compatibility.json` when present and compare its values against an in-game match report.

## Output and validation

Download the generated ZIP packages from the [fm27-exports Release](https://github.com/eslaulau/FM27-Exporter/releases/tag/fm27-exports). Review `managed-club.json`, `validation.json`, `first-team-scope.json`, `player-report-identity-audit.json`, `team-match-stats-compatibility.json` (if present), `export-warnings.txt` (if present), and `native-diagnostics.txt`.

A completed workflow means the cloud job completed and required files plus dynamic first-team scope passed structural checks. Paired-row checks prove two-sided structure and fixture joins, not semantic accuracy of every decoded statistic.

## Local development

The PowerShell script and Python filter remain in the repository for maintenance and CI validation. Local execution is not the supported user-facing export procedure.
