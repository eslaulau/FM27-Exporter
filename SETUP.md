# Private save export setup

## Step 1 — create a fine-grained token

Open https://github.com/settings/personal-access-tokens/new and create a Fine-grained personal access token.

- Resource owner: eslaulau
- Repository access: Only select repositories
- Select only the private repository FM27
- Repository permissions: Contents = Read and write
- No Actions, Administration, Workflows or other permissions are needed
- Prefer a 30- or 90-day expiry

This token downloads source saves and the private player identity cache, and uploads reports to a private Release in FM27. It is never stored in this repository.

## Step 2 — add the token as an Actions secret

Open https://github.com/eslaulau/FM27-Exporter/settings/secrets/actions and create a repository secret:

- Name: FM27_ACCESS_TOKEN
- Secret: paste the fine-grained token

Do not paste the token into source code, an Issue, a workflow input, or chat.

## Step 3 — run the workflow

Open https://github.com/eslaulau/FM27-Exporter/actions/workflows/export-private-saves.yml and click Run workflow.

- all: export all three saves currently stored in the private FM27 Release tagged fm
- save1, save2, save3: export only that save

Results, runner logs, the run summary and the persistent player-match-history archive are uploaded only to the private FM27 Release tagged fm27-exports. No save or report is uploaded as an artifact to this public repository.

## Security boundaries

- The public repository contains exporter code and generic catalog data only.
- The source .fm files are downloaded from private Release fm and checked against pinned size and SHA256 values.
- FM27_PlayerIdentityCache_Formal_v1.1.json contains save-specific player identity data. It is fetched from a pinned private commit only at runtime and deleted from the workspace at the end of the run; it is not committed here.
- Export ZIPs and persistent history remain in private Release fm27-exports.
- The workflow is manual-dispatch only. It does not run on Pull Requests and does not expose its private token to PR jobs.
- Only trusted accounts should have write access to this public repository because write access permits manually starting the workflow.
- When the token expires, create a replacement and update the FM27_ACCESS_TOKEN secret.

## Runner cost

This workflow uses the standard GitHub-hosted windows-latest runner. GitHub states that standard GitHub-hosted runner usage in public repositories is free. Larger runners are not used.

Official billing reference: https://docs.github.com/en/actions/concepts/billing-and-usage
