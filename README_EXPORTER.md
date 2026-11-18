# FM27 first-team save exporter v1.4.5

## Features

- Read-only parsing of FM27 .fm saves; the source save is never modified.
- Installs and verifies pinned fmsave==0.12.4; no automatic parser upgrades.
- Exports managed first-team profiles/attributes, season and match data, fixtures, tactics, set pieces and selections.
- Detailed player match reports for formal competition IDs 7, 637, 661 and 662; excludes non-competitive ID 131.
- Unresolved anonymous match rows remain unresolved; the exporter does not guess player identity.

## Configured scope

This release is configured for team_id=539 and club_uid=680. Verify and update those IDs before using it for a different managed club.

For FM27 build 27.0.1+2494687 and match_stats_cfg schema 6, an explicitly labelled experimental compatibility path is included. It is not an upstream verification claim. Inspect team-match-stats-compatibility.json when present.

The actual selected role and live personal instructions are not reliably decoded. Candidate roles and permission audits are not the actual selected tactic settings.

## Local use

Requires Windows PowerShell 5.1 and Python 3.12+.

    python -m pip install --disable-pip-version-check fmsave==0.12.4
    .\Run_FM27_Formal_Season_Export_v1.4.5.ps1 -SavePath "D:\FM27\games\your-save.fm"

If -SavePath is omitted, the script tries the standard FM27 save folder under the current Windows user's Documents directory.

## Cloud use

Complete SETUP.md first. The workflow reads private saves on a standard Windows runner and uploads results only to private FM27 Release fm27-exports.

## Validate results

Review validation.json, first-team-scope.json, player-report-identity-audit.json, team-match-stats-compatibility.json (if present), export-warnings.txt (if present), and native-diagnostics.txt.

A completed script process does not mean every exported field has been fully validated.
