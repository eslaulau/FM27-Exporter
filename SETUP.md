# Public FM27 exporter setup

## One-time migration

The three source saves currently live in the old `eslaulau/FM27` repository. The migration workflow copies them into this public repository's Release tagged `fm27-saves`.

1. Open the [one-time migration workflow](https://github.com/eslaulau/FM27-Exporter/actions/workflows/migrate-saves-to-public.yml).
2. Click **Run workflow**. It uses the existing `FM27_ACCESS_TOKEN` secret only to read the old source Release; upload to this repository uses GitHub's automatically provided token.
3. Wait for a green **Success** result. Confirm that [Release fm27-saves](https://github.com/eslaulau/FM27-Exporter/releases/tag/fm27-saves) contains all three `.fm` files.
4. Then delete the `FM27_ACCESS_TOKEN` secret from [Actions secrets](https://github.com/eslaulau/FM27-Exporter/settings/secrets/actions), and remove `.github/workflows/migrate-saves-to-public.yml` from the repository. The old private repository is no longer used.

If the migration fails, inspect the Actions log. The source save files are checked against their recorded sizes and SHA256 hashes before they are uploaded.

## Routine exports

1. Open [Export public FM27 saves](https://github.com/eslaulau/FM27-Exporter/actions/workflows/export-public-saves.yml).
2. Click **Run workflow** and choose `all`, `save1`, `save2`, or `save3`.
3. Reports, summary JSON, diagnostics and persistent player-match-history archives are uploaded to the public [Release fm27-exports](https://github.com/eslaulau/FM27-Exporter/releases/tag/fm27-exports).

No personal access token or private repository is required for routine exports.

## Public-data notice

The source `.fm` career saves, player identity mappings, reports, runner logs and history archives are intentionally public. Anyone can download them. The exporter only reads source saves; it does not modify the original files.

## Runner

The workflow uses the standard GitHub-hosted `windows-latest` runner and Python 3.12.
