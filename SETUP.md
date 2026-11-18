# Public FM27 exporter setup

## Chat-driven export

You can ask ChatGPT to start an export directly. It sends an owner-authenticated command to the [FM27 Export Control issue](https://github.com/eslaulau/FM27-Exporter/issues/1), and GitHub Actions starts automatically.

Commands:
- `/export all` — export all three saves
- `/export tactic1` — export the first tactic group
- `/export tactic2` — export the second tactic group
- (new tactic groups can be added to the release)

The workflow posts the run result and links back to the control issue. Only comments authored by the repository owner are accepted as commands.

## Manual fallback

Open [Export public FM27 saves](https://github.com/eslaulau/FM27-Exporter/actions/workflows/export-public-saves.yml), click **Run workflow**, and choose a save set.

## Results and source files

The three source career saves are stored in the public [Release fm27-saves](https://github.com/eslaulau/FM27-Exporter/releases/tag/fm27-saves). Reports, summary JSON, diagnostics and persistent player-match-history archives are uploaded to the public [Release fm27-exports](https://github.com/eslaulau/FM27-Exporter/releases/tag/fm27-exports).

No personal access token or private repository is required for routine exports.

## Public-data notice

The source `.fm` career saves, player identity mappings, reports, runner logs and history archives are intentionally public. Anyone can download them. The exporter only reads source saves; it does not modify the original files.

## Runner

The workflow uses the standard GitHub-hosted `windows-latest` runner and Python 3.12.
