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
- Player-detail parser completeness is checked against the matches still retained by fmsave's native team-match-stats reader. The season schedule is reported separately because FM27 does not retain a detailed report for every played fixture.
- Unresolved anonymous match rows remain unresolved; the exporter does not guess player identity.

## Compatibility note

For FM27 build 27.0.1+2494687 and `match_stats_cfg` schema 6, the player-report helper borrows the registered 27.0.0 schema-6 layout. For FM27 build 27.1.1+2511875 and schema 6, it borrows the registered 27.1.0 schema-6 layout already shipped in pinned `fmsave==0.14.3`. The helper selects the embedded per-report record variant before decoding squad anchors, player metrics and record lengths (the 27.1 variant adds five bytes inside player records). These target builds remain unregistered upstream; this is explicit structural compatibility, not a claim of upstream registration or full semantic validation. Inspect `player_report_layout` in `team-match-stats-compatibility.json` and compare exported values against in-game match reports.

The formal-report coverage audit compares native match-stat rows only against the dynamically discovered formal competition IDs. Friendly/pre-season matches and native-only competition IDs outside that scope are counted separately, not reported as missing formal player reports. `player-match-report-formal-summary.json` also includes `player_goal_reconciliation`, which compares the fixture score with every raw player-report row before identity and zero-minute filtering. Goal differences remain unattributed; the exporter does not assign an unverified scorer or assume an own goal. The first-team scope audit permits a competition-ID fallback only when the match date and ordered home/away team IDs identify exactly one played fixture; the original native competition ID is preserved.

For detailed player reports, the helper also reads the raw 16-bit position mask at raw-window offset +110 and the raw one-decimal rating stored as uint16 hundredths. The rating offset is selected per embedded report-record variant (rather than assuming the pre-27.1 offset). Position and rating raw sources are enabled only after at least 25 direct same-match named-history comparisons with zero mismatches. Zero position masks remain blank; unknown identities are not inferred from lineup order or preferred positions. The compatibility audit records each field's offset, sample count and cross-check result.

## Position semantics: candidate labels versus verified match positions

The raw match-position number and its UI meaning are separate claims. The exporter preserves the raw
`position_code` and may attach a `match_position_id_candidate` / `match_position_name_candidate`
when the number exactly matches a one-hot entry in the native tactic-position catalog. This catalog
match is only a candidate mapping. A same-match numeric cross-check against `fmsave` history confirms
that the number was decoded consistently; it does not prove what the number means on the match screen.

Each export now writes:

- `position-semantic-validation.json`: per-code coverage, candidate label, numeric cross-check scope,
  and explicit semantic-verification status.
- `position-semantic-review.csv`: up to three identified player/fixture samples per observed raw code.
  The CSV is a review queue, not proof. The samples reuse a compact shared set of fixtures so
one match screen can be used to inspect several position codes. The exact fixture list is repeated
in `position-semantic-validation.json`.

To complete a review, open each exact fixture in FM27 and inspect the match screen that explicitly
shows the player's position for that match. Do not substitute the player's preferred position, the
starting tactic slot, a role/duty, or the position used in another match. Record the exact UI text and
screenshot filename plus either its SHA-256 or immutable Git blob SHA-1 in the review CSV. The Git blob
SHA-1 is the exact content object identifier returned by GitHub; it is not a SHA-256 value. After the
screenshot has actually been inspected, mark the row `visual_review_status=confirmed` and fill the
normalized position ID/name, reviewer, and review date. Re-run `FM27_FormalPlayerReport_Enrichment_v1.1.py`
against the same report folder; existing review responses are carried forward.

A code is promoted only when at least three distinct fixtures have screenshot-backed, visually
reviewed evidence and all reviewed rows agree with the candidate. Evidence should cover at least two
identified players when the save contains more than one player for that code; a code used by only one
identified player can be checked across that player's distinct fixtures. Conflicting or mismatching
evidence blocks promotion. If a rare code appears in fewer than three distinct fixtures, the queue
keeps up to three distinct player/fixture samples (including different players in the same match) and
the audit reports that fixture diversity is insufficient; it does not promote the code globally.
Screenshot hashes and reviewer fields are metadata; the script does not itself inspect screenshot
pixels. Until visual review is complete, verified position fields remain blank and the raw code is
authoritative.

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
