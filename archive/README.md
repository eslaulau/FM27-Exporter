# Archived exporter components

This directory contains retired code and automation retained for provenance and reproducibility. **Nothing under this directory is a supported current entry point.**

## Legacy exporters and trial pipeline

- `legacy-exporters/Run_FM27_Formal_Season_Export_v1.4.5.ps1`: retired exporter; its historical output used fixed team/club IDs and a wider tactical/position export scope.
- `legacy-exporters/FM27_FirstTeam_Filter_v1.2.2.py`: retired filter; includes old fixed-ID defaults and tactic/set-piece filtering behavior.
- `legacy-exporters/FM27_Tactic_Trial_Comparison_v1.0.py`: retired two-tactic/six-save comparison helper.
- `legacy-exporters/FM27_PlayerIdentityCache_Formal_v1.1.json`: cache belonging to the retired trial workflow; do not use as current club identity configuration.

## Disabled GitHub Actions workflows

`legacy-workflows/*.yml.disabled` preserves the previous public-save export and report-publishing workflow definitions. The `.disabled` suffix and location outside `.github/workflows/` ensure GitHub Actions does not register them as active workflows.

## Current supported path

Use only the root-level `Run_FM27_Formal_Season_Export_v1.5.0.ps1` and `FM27_FirstTeam_Filter_v1.3.0.py`. Follow [README_EXPORTER.md](../README_EXPORTER.md).

Do not delete archived reports or use their old instructions to configure a new export. The historical files are retained as evidence of earlier experiments, not as current guidance.
