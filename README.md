# FM27 Exporter

Windows-based, read-only FM27 exporter. The v1.5.0 local bundle scopes player data to the managed first team and preserves both teams' match statistics for direct fixtures.

- Local exporter version: **v1.5.0** (`Run_FM27_Formal_Season_Export_v1.5.0.ps1`)
- Parser pin: **fmsave==0.12.4**
- Three source career saves are stored in the public `fm27-saves` Release.
- The player-identity cache, export reports, diagnostics and history archives are public.
- Routine exports use this repository's built-in GitHub Actions token. No private repository or personal access token is needed.

## Run an export

You can ask ChatGPT to export a save. ChatGPT posts an owner-authenticated command to the [FM27 Export Control issue](https://github.com/eslaulau/FM27-Exporter/issues/1), which starts GitHub Actions automatically.

Supported commands:
- `/export all`
- `/export tactic1`
- `/export tactic2`
- `/recover RUN_ID`：从失败运行的诊断包恢复已完成的报告，不重新解析 `.fm` 存档
- `/validate`：只进行语法与存档清单预检

You can also start the [Export public FM27 saves](https://github.com/eslaulau/FM27-Exporter/actions/workflows/export-public-saves.yml) workflow manually. Choose `all`, `tactic1`, or `tactic2`.

Reports are published to the public [Release fm27-exports](https://github.com/eslaulau/FM27-Exporter/releases/tag/fm27-exports).

The v1.5.0 local exporter resolves the managed club and first-team ID from the save, retains home + away team statistics for direct matches, and does not extract or infer tactics. See [README_EXPORTER.md](README_EXPORTER.md) for its exact scope. The public six-save Actions workflow remains a separate trial-comparison pipeline.

**Public-data notice:** anyone can download the source `.fm` saves, player-identity cache, reports and history archives.
