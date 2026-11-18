# FM27 Exporter

Windows-based, read-only first-team FM27 save exporter.

- Exporter version: **v1.4.5**
- Parser pin: **fmsave==0.12.4**
- Three source career saves are stored in the public `fm27-saves` Release.
- The player-identity cache, export reports, diagnostics and history archives are public.
- Routine exports use this repository's built-in GitHub Actions token. No private repository or personal access token is needed.

## Run an export

You can ask ChatGPT to export a save. ChatGPT posts an owner-authenticated command to the [FM27 Export Control issue](https://github.com/eslaulau/FM27-Exporter/issues/1), which starts GitHub Actions automatically.

Supported commands:
- `/export all`
- `/export save1`
- `/export save2`
- `/export save3`

You can also start the [Export public FM27 saves](https://github.com/eslaulau/FM27-Exporter/actions/workflows/export-public-saves.yml) workflow manually. Choose `all`, `save1`, `save2`, or `save3`.

Reports are published to the public [Release fm27-exports](https://github.com/eslaulau/FM27-Exporter/releases/tag/fm27-exports).

See [SETUP.md](SETUP.md) for usage and [README_EXPORTER.md](README_EXPORTER.md) for exporter scope and validation.

**Public-data notice:** anyone can download the source `.fm` saves, player-identity cache, reports and history archives.
