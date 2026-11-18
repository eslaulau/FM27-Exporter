# Public FM27 exporter setup

## Routine exports

The three source career saves have already been migrated to the public `fm27-saves` Release.

1. Open [Export public FM27 saves](https://github.com/eslaulau/FM27-Exporter/actions/workflows/export-public-saves.yml).
2. Click **Run workflow** and choose `all`, `save1`, `save2`, or `save3`.
3. Reports, summary JSON, diagnostics and persistent player-match-history archives are uploaded to the public [Release fm27-exports](https://github.com/eslaulau/FM27-Exporter/releases/tag/fm27-exports).

No personal access token or private repository is required for routine exports.

## Public source saves

The three validated source files are stored in [Release fm27-saves](https://github.com/eslaulau/FM27-Exporter/releases/tag/fm27-saves). Their recorded sizes and SHA256 hashes are checked before export.

## Public-data notice

The source `.fm` career saves, player identity mappings, reports, runner logs and history archives are intentionally public. Anyone can download them. The exporter only reads source saves; it does not modify the original files.

## Runner

The workflow uses the standard GitHub-hosted `windows-latest` runner and Python 3.12.
