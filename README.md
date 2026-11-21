# FM27 Exporter

**Current supported entry point: local exporter v1.5.0 only.** This repository is organized around read-only analysis of an FM27 save using the managed first team as the scope.

- Main script: [Run_FM27_Formal_Season_Export_v1.5.0.ps1](Run_FM27_Formal_Season_Export_v1.5.0.ps1)
- Filter: [FM27_FirstTeam_Filter_v1.3.0.py](FM27_FirstTeam_Filter_v1.3.0.py)
- Full specification: [README_EXPORTER.md](README_EXPORTER.md)
- Windows setup: [SETUP.md](SETUP.md)
- Historical/retired code: [archive/README.md](archive/README.md)
- Historical reports: [season-reports/README.md](season-reports/README.md)

## What the current exporter does

The exporter resolves the managed club and its owned first team dynamically from the save. It keeps first-team fixtures and player data, plus both sides' team-level match statistics for direct first-team fixtures. It does **not** export or infer tactics, set pieces, tactic slots, roles, or opponent player data. The user supplies the tactic used in each match.

The source save is read-only and is not modified. The current local exporter pins `fmsave==0.12.4`; compatibility of a particular FM27 build and decoded fields must still be checked in that export's validation and diagnostics.

## Run locally

Requires Windows PowerShell 5.1 and Python 3.12+.

```powershell
python -m pip install --disable-pip-version-check fmsave==0.12.4
.\Run_FM27_Formal_Season_Export_v1.5.0.ps1 -SavePath "D:\FM27\games\your-save.fm"
```

If `-SavePath` is omitted, the script attempts the standard FM27 save folder under the current Windows user's Documents directory.

## Source saves and published historical outputs

- [Source-save Release](https://github.com/eslaulau/FM27-Exporter/releases/tag/fm27-saves)
- [Historical export Release](https://github.com/eslaulau/FM27-Exporter/releases/tag/fm27-exports)

Release contents can change; check the actual asset list rather than assuming a fixed number of saves or tactic groups. Old reports remain available as historical evidence and are **not** current exporter specifications.

## Retired automation

The previous six-save/two-tactic GitHub Actions pipeline and its report-publishing workflows have been disabled and preserved under `archive/legacy-workflows/`. They are not part of the v1.5.0 local export path. There are no supported `/export tactic1`, `/export tactic2`, or ChatGPT-triggered cloud export commands in the current setup.

## Public-data notice

The source `.fm` saves, identity mappings, reports, diagnostics and history archives in public Releases/repository paths are publicly downloadable.
