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

## Match-position masks: native catalog validation

The player match report stores a raw 16-bit position mask at raw-window offset +110
(`statistics_anchor +10`). The exporter cross-checks that value against the same-match
named player-history `position_code` field. Once at least 25 direct comparisons are
available and every comparison matches (zero mismatches), the mask is decoded by exact
equality with `catalog.json` `positions[].mask`.

This is a direct lookup against the native FM27 position-mask catalog. It does **not**
infer position from a player's preferred positions, lineup order, current tactic slot,
role, duty, or formation. No game screenshot or manual review is required.

Each export writes `position-semantic-validation.json`, which records:
- the raw field location and encoding;
- native catalog provenance (bundle hash, resolver metadata and position entries);
- the number of same-match named-history cross-checks and whether the 25-row/zero-mismatch
  gate passed;
- every observed raw code, its exact mask, mapped native position ID/name, row coverage,
  and verification status.

Exact examples from the current native catalog include `1=GK`, `4=DR`, `8=DL`,
`16=DC`, `128=DMC`, `1024=MC`, `2048=AMR`, `4096=AML`, `8192=AMC`,
and `16384=ST`. Other exact single-bit entries such as wing-back or wide-midfield
positions are also supported when they occur in the save. Unknown, compound, or non-matching
masks remain unmapped instead of being guessed.

The decoded mask is a match-position classification, separate from player role and duty. A
base mask `16=DC` identifies centre-back but does not distinguish `DCL` from `DCR`.
Role decoding is handled independently from the raw `role_code` byte, as described below.
The raw `position_code` is always retained in the source reports. The legacy
`position-semantic-review.csv` from earlier exports is not used by the new validator.

## Match role codes: native flag and position-context decoding

The named player match-history reader exposes `unknown.role_code` as a raw unsigned byte.
The exporter does not interpret it as a role-array index. Instead, it derives a flag mask
using `role_bit_mask = 1 << role_code`, then requires an exact match against
`catalog.json` `roles[].flags`.

Because the same flag may be used by an in-possession role and a different
out-of-possession role, decoding is restricted to phase 0 (in possession). The resulting
role must also be present in `catalog.json` `role_eligibility[base_position_id][0]`
for that player's stored match-position code. A matching phase-1 role is recorded as an
alternative, but is never substituted as the match-history role label.

Examples supported by the current native catalog include:
- `role_code=12` at `GK` → `BallPlayingGoalkeeper`（出球门将）
- `role_code=24` at `DC` → `BallPlayingCentreBack`（出球中卫）
- `role_code=43` at `AMR/AML` → `PlaymakingWinger`（组织型边锋）
- `role_code=56` at `MC/AMC` → `ChannelMidfielder`（肋部中场）

The mapping has been corroborated against the role badges and named players shown in
the in-possession formation diagrams for Brighton's 6–1 Ajax match on 18 March 2027
(`3/3.png`) and 4–0 Sunderland match on 9 May 2027 (`3/4.png`). This visual sample
covers role codes `1, 2, 3, 12, 24, 31, 43, 56`.

Each export writes `role-code-semantic-validation.json` and extends
`player-match-report-role-code-audit-enriched.csv`. The identified enriched CSV includes
the original `role_code_raw`, bit mask, candidate role, verified in-possession role,
phase, and any phase-1 alternative. A code-position combination that fails the native
eligibility table is not force-decoded: for example, one observed `role_code=27` row at
`ST` is retained as raw because `InsideForward` is not eligible at `ST`. The raw byte
is always preserved; no role is inferred from array order, player attributes, or lineup
order. The exporter does not claim that this byte independently identifies the
out-of-possession role.

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
