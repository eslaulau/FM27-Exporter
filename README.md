# FM27 Exporter

Windows-based, read-only first-team FM27 save exporter.

- Exporter version: **v1.4.5**
- Parser pin: **fmsave==0.12.4**
- Source save files are stored as assets in this **public** repository's `fm27-saves` Release.
- The player-identity cache, export reports, diagnostics and history archives are also public.
- Routine exports use only this repository and its built-in GitHub Actions token. No private repository or personal access token is needed.

## First-time setup

1. Run the one-time **Migrate FM27 saves to public** workflow to copy the three existing save files from the old repository into the public `fm27-saves` Release.
2. After migration succeeds, remove the temporary `FM27_ACCESS_TOKEN` repository secret and delete the one-time migration workflow.
3. Run **Export public FM27 saves** whenever you want to export. Choose `all`, `save1`, `save2`, or `save3`.

See [SETUP.md](SETUP.md) for the short first-time migration steps and [README_EXPORTER.md](README_EXPORTER.md) for exporter scope and validation.

**Public-data notice:** anyone can download the source `.fm` saves, player-identity cache, reports and history archives from this repository.
