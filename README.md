# FM27 Exporter

**Official workflow: v1.5.0 manual cloud export through GitHub Actions.** The repository runs the exporter on GitHub-hosted Windows runners; users do not need to run PowerShell or install Python locally.

- Export engine: [Run_FM27_Formal_Season_Export_v1.5.0.ps1](Run_FM27_Formal_Season_Export_v1.5.0.ps1)
- First-team filter: [FM27_FirstTeam_Filter_v1.3.0.py](FM27_FirstTeam_Filter_v1.3.0.py)
- Full export contract: [README_EXPORTER.md](README_EXPORTER.md)
- Cloud workflow: [.github/workflows/fm27-v1.5-cloud-export.yml](.github/workflows/fm27-v1.5-cloud-export.yml)

## How cloud export runs

1. Upload the FM27 `.fm` save asset to the GitHub Release tagged `fm27-saves`.
2. When you want an export, manually start **Actions → FM27 v1.5.0 Cloud Season Export → Run workflow**.
3. Enter the exact `.fm` asset filename. Each run processes exactly one requested save; there is no automatic Release trigger and no blank-input "export all" mode.
4. The GitHub-hosted Windows runner verifies the Release asset's SHA-256 digest and byte length before parsing, runs the v1.5.0 exporter in a save-specific working directory, and validates the required outputs and managed first-team scope.
5. The workflow publishes the report ZIP and summary JSON to the `fm27-exports` Release, then reads the Release back and verifies each uploaded asset's size and SHA-256 digest.
6. On success, the complete report folder is also retained as a 30-day workflow artifact. On failure, runner diagnostics are retained as a 14-day artifact.

The workflow uses the v1.5.0 exporter and its pinned `fmsave==0.12.4` dependency. The original save is read-only. No fixed club UID or team ID is assumed.

## Export scope

The exporter resolves the managed club and its owned first team dynamically. It exports first-team fixtures and player data, plus both sides' team-level match statistics for direct first-team fixtures. It does not export or infer tactics, set pieces, tactic slots, roles, or opponent player data. The tactic used in each match must be supplied separately for tactical analysis.

## Validation boundary

A workflow success means the source asset integrity check, required output checks, dynamic first-team scope check, and published asset readback checks passed. It does not prove every decoded statistic is semantically correct for every FM27 build; inspect each report's validation and diagnostics.

## Historical material

Old exporter scripts and workflows are preserved under `archive/` for historical reference. They are not the v1.5.0 cloud execution path. Historical reports remain available as evidence, not as current exporter instructions.

## Public-data notice

Source `.fm` saves and report ZIPs published in Releases are publicly downloadable.
