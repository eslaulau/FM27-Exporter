# FM27 v1.5.0 cloud export setup

No local PowerShell, Python, or ZIP extraction is required to run an export.

## Automatic export

1. Upload your FM27 `.fm` save file(s) to the repository Release tagged `fm27-saves`.
2. Publish the release. GitHub Actions automatically starts **FM27 v1.5.0 Cloud Season Export**.
3. Wait for the workflow run to finish.
4. Download the generated report ZIP from the [fm27-exports Release](https://github.com/eslaulau/FM27-Exporter/releases/tag/fm27-exports).

## Rerun or export only one save

1. Open the repository's **Actions** tab.
2. Select **FM27 v1.5.0 Cloud Season Export**.
3. Click **Run workflow**.
4. Enter the exact source `.fm` asset name to export only that file. Leave the field blank to export every `.fm` file in `fm27-saves`.
5. Start the workflow and retrieve the report from `fm27-exports`.

## What v1.5.0 exports

- Managed club and first-team identity are resolved from the save itself; no team ID needs to be entered.
- Only fixtures involving the managed first team are included.
- Both home and away team-stat rows for those fixtures are retained.
- First-team player data and detailed formal player reports are retained.
- Tactics and set pieces are not extracted or inferred. Supply the tactic-to-match mapping separately.
- The original save is read-only.

See [README_EXPORTER.md](README_EXPORTER.md) for the export contract and validation limitations.
