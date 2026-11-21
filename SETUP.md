# Local FM27 exporter setup

This is the setup guide for the **current local exporter v1.5.0**. Older cloud workflows and tactic-group commands are retired; see [archive/README.md](archive/README.md).

## Requirements

- Windows PowerShell 5.1
- Python 3.12 or newer
- An FM27 career save (`.fm`)

## Install the pinned parser

```powershell
python -m pip install --disable-pip-version-check fmsave==0.12.4
```

## Run the export

Download the repository ZIP from GitHub and extract the complete folder. Keep the main script and its helper files together; do not copy only the `.ps1` file.

From PowerShell in the extracted repository folder:

```powershell
.\Run_FM27_Formal_Season_Export_v1.5.0.ps1 -SavePath "D:\FM27\games\your-save.fm"
```

If `-SavePath` is omitted, the script attempts the standard FM27 save folder under the current Windows user's Documents directory.

## Important scope rules

- The managed club and first-team ID are resolved from the save; do not enter or hardcode team IDs.
- Only fixtures involving the managed first team are included.
- Both home and away team-stat rows for those fixtures are retained.
- Tactics and set pieces are not extracted or inferred. Supply the tactic-to-match mapping separately when analyzing a season.
- The original save is read-only.

## Validate the output

Before using the report for tactical conclusions, inspect `managed-club.json`, `validation.json`, `first-team-scope.json`, `team-match-stats-compatibility.json` (if present), `export-warnings.txt` (if present), and `native-diagnostics.txt`. A successful process exit does not prove every decoded field is semantically correct.

See [README_EXPORTER.md](README_EXPORTER.md) for the complete export contract.
