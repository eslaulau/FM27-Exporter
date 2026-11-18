# FM27 Exporter

Windows-based, read-only first-team FM27 save exporter.

- Exporter version: **v1.4.5**
- Parser pin: **fmsave==0.12.4**
- Three source career saves are stored in the public `fm27-saves` Release.
- The player-identity cache, export reports, diagnostics and history archives are public.
- Routine exports use only this repository and its built-in GitHub Actions token. No private repository or personal access token is needed.

## Run an export

1. Open [Export public FM27 saves](https://github.com/eslaulau/FM27-Exporter/actions/workflows/export-public-saves.yml).
2. Click **Run workflow** and choose `all`, `save1`, `save2`, or `save3`.
3. Find generated reports in the public [Release fm27-exports](https://github.com/eslaulau/FM27-Exporter/releases/tag/fm27-exports).

See [SETUP.md](SETUP.md) for usage and [README_EXPORTER.md](README_EXPORTER.md) for exporter scope and validation.

**Public-data notice:** anyone can download the source `.fm` saves, player-identity cache, reports and history archives.
