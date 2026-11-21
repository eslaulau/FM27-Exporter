# FM27 Exporter

**Official workflow: v1.5.0 cloud automatic export through GitHub Actions.** The repository runs the exporter on GitHub-hosted Windows runners; users do not need to run PowerShell or install Python locally.

- Export engine: [Run_FM27_Formal_Season_Export_v1.5.0.ps1](Run_FM27_Formal_Season_Export_v1.5.0.ps1)
- First-team filter: [FM27_FirstTeam_Filter_v1.3.0.py](FM27_FirstTeam_Filter_v1.3.0.py)
- Full export contract: [README_EXPORTER.md](README_EXPORTER.md)
- Cloud workflow: [.github/workflows/fm27-v1.5-cloud-export.yml](.github/workflows/fm27-v1.5-cloud-export.yml)

## How cloud export runs

1. Upload one or more FM27 `.fm` save assets to the GitHub Release tagged `fm27-saves`.
2. Publishing that release automatically starts the v1.5.0 cloud export workflow.
3. To rerun an export or export a particular save, open **Actions → FM27 v1.5.0 Cloud Season Export → Run workflow**. Enter the exact `.fm` asset name to export only that save; leave it blank to process every `.fm` asset in `fm27-saves`.
4. The GitHub-hosted Windows runner downloads the saves, runs v1.5.0, validates the dynamic managed-club/first-team scope and required outputs, then publishes ZIP reports to the `fm27-exports` Release.
5. Open [Cloud export reports](https://github.com/eslaulau/FM27-Exporter/releases/tag/fm27-exports) to retrieve the results.

The workflow uses the v1.5.0 exporter and its pinned `fmsave==0.12.4` dependency. The original save is read-only. No fixed club UID or team ID is assumed.

## Export scope

The exporter resolves the managed club and its owned first team dynamically. It exports first-team fixtures and player data, plus both sides' team-level match statistics for direct first-team fixtures. It does not export or infer tactics, set pieces, tactic slots, roles, or opponent player data. The tactic used in each match must be supplied separately for tactical analysis.

## Validation boundary

A workflow success means the cloud job completed and its required files and dynamic first-team scope passed structural checks. It does not prove every decoded statistic is semantically correct for every FM27 build; inspect each report's validation and diagnostics.

## Historical material

Old exporter scripts and workflows are preserved under `archive/` for historical reference. They are not the v1.5.0 cloud execution path. Historical reports remain available as evidence, not as current exporter instructions.

## Public-data notice

Source `.fm` saves and report ZIPs published in Releases are publicly downloadable.
