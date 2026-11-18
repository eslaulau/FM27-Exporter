[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+$')]
    [string]$SourceRunId
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$repo = $env:GITHUB_REPOSITORY
if ([string]::IsNullOrWhiteSpace($repo) -or [string]::IsNullOrWhiteSpace($env:GH_TOKEN) -or
    [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP) -or [string]::IsNullOrWhiteSpace($env:GITHUB_WORKSPACE)) {
    throw 'Required GitHub Actions environment is missing.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$comparisonScript = Join-Path $repoRoot 'FM27_Tactic_Trial_Comparison_v1.0.py'
if (-not (Test-Path -LiteralPath $comparisonScript -PathType Leaf)) { throw 'Tactic comparison script is missing.' }

$ghPath = (Get-Command gh -ErrorAction Stop).Source
$pythonPath = (Get-Command python -ErrorAction Stop).Source
$workRoot = Join-Path $env:RUNNER_TEMP ('FM27-Analysis-Inputs-' + $SourceRunId + '-' + $env:GITHUB_RUN_ID)
$downloadRoot = Join-Path $workRoot 'downloads'
$diagnosticRoot = Join-Path $workRoot 'diagnostics'
$partialPackagesRoot = Join-Path $diagnosticRoot 'PartialPackages'
$artifactRoot = Join-Path $env:GITHUB_WORKSPACE '_analysis-artifact'
$runsRoot = Join-Path $artifactRoot 'runs'
$comparisonRoot = Join-Path $artifactRoot 'comparison'
foreach ($dir in @($downloadRoot, $runsRoot, $comparisonRoot)) {
    $null = New-Item -ItemType Directory -Path $dir -Force
}

$diagnosticAsset = 'FM27_TacticComparison_Diagnostics_' + $SourceRunId + '.zip'
Write-Host ('Downloading preserved six-trial diagnostics from run ' + $SourceRunId + '.')
& $ghPath release download 'fm27-exports' --repo $repo --pattern $diagnosticAsset --dir $downloadRoot --clobber
if ($LASTEXITCODE -ne 0) { throw ('Could not download diagnostic package ' + $diagnosticAsset + '.') }
$diagnosticZip = Join-Path $downloadRoot $diagnosticAsset
if (-not (Test-Path -LiteralPath $diagnosticZip -PathType Leaf)) { throw 'Downloaded diagnostic package is missing.' }
Expand-Archive -LiteralPath $diagnosticZip -DestinationPath $diagnosticRoot -Force
if (-not (Test-Path -LiteralPath $partialPackagesRoot -PathType Container)) { throw 'Diagnostic package contains no preserved trial exports.' }

$sourcePackages = @(Get-ChildItem -LiteralPath $partialPackagesRoot -Directory | Sort-Object Name)
if ($sourcePackages.Count -ne 6) { throw ('Expected six preserved trial packages; found ' + $sourcePackages.Count + '.') }

$requiredOutputs = @(
    'save-info.json', 'validation.json', 'first-team-scope.json',
    'fixtures.json', 'team-match-stats.json', 'tactics.json',
    'set-pieces.json', 'selections.json', 'players.json',
    'player-season-stats.csv', 'player-match-report-formal-all.csv',
    'player-match-report-formal-summary.json', 'player-report-identity-audit.json',
    'player-position-history.csv', 'player-current-tactic-slot-map.csv'
)
$manifestRows = @()
$inventory = @()

foreach ($sourcePackage in $sourcePackages) {
    $manifestPath = Join-Path $sourcePackage.FullName 'save-manifest.json'
    $exportContainer = Join-Path $sourcePackage.FullName 'Export'
    if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf) -or -not (Test-Path -LiteralPath $exportContainer -PathType Container)) {
        throw ('Incomplete preserved package: ' + $sourcePackage.Name)
    }

    $saveManifest = Get-Content -LiteralPath $manifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $tacticName = [string]$saveManifest.tactic_name
    $trialNumber = [int]$saveManifest.trial
    if ([string]::IsNullOrWhiteSpace($tacticName) -or $trialNumber -notin @(1, 2, 3)) {
        throw ('Invalid save manifest in package: ' + $sourcePackage.Name)
    }

    $candidateDirs = @(Get-ChildItem -LiteralPath $exportContainer -Directory -Filter 'FM27_Analysis_*')
    if ($candidateDirs.Count -eq 1) {
        $candidatePath = $candidateDirs[0].FullName
        $candidateName = $candidateDirs[0].Name
    } elseif ($candidateDirs.Count -eq 0 -and (Test-Path -LiteralPath (Join-Path $exportContainer 'save-info.json') -PathType Leaf)) {
        $candidatePath = $exportContainer
        $candidateName = 'FM27_Analysis_Recovered'
    } else {
        throw ('Expected a nested FM27_Analysis folder or flattened export files in ' + $sourcePackage.Name + '.')
    }

    $missingOutputs = @($requiredOutputs | Where-Object { -not (Test-Path -LiteralPath (Join-Path $candidatePath $_) -PathType Leaf) })
    if ($missingOutputs.Count -gt 0) {
        throw ('Trial package ' + $sourcePackage.Name + ' is missing required analysis inputs: ' + ($missingOutputs -join ', '))
    }

    $scope = Get-Content -LiteralPath (Join-Path $candidatePath 'first-team-scope.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$scope.team_id -ne 539 -or [int]$scope.club_uid -ne 680) {
        throw ('First-team scope mismatch in ' + $sourcePackage.Name)
    }

    $safeTactic = [regex]::Replace($tacticName, '[\\/:*?"<>|]', '_')
    $slotFolder = Join-Path $runsRoot ($safeTactic + '__run-' + $trialNumber)
    $analysisFolder = Join-Path $slotFolder $candidateName
    $null = New-Item -ItemType Directory -Path $analysisFolder -Force
    Copy-Item -LiteralPath $manifestPath -Destination (Join-Path $slotFolder 'save-manifest.json') -Force
    Get-ChildItem -LiteralPath $candidatePath -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $analysisFolder -Recurse -Force
    }

    $tactics = Get-Content -LiteralPath (Join-Path $candidatePath 'tactics.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $selections = Get-Content -LiteralPath (Join-Path $candidatePath 'selections.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    $inventory += [pscustomobject]@{
        tactic_name = $tacticName
        trial = $trialNumber
        source_asset = [string]$saveManifest.source_asset
        game_date = [string]((Get-Content -LiteralPath (Join-Path $candidatePath 'save-info.json') -Raw -Encoding UTF8 | ConvertFrom-Json).game_date)
        tactics_records = @($tactics).Count
        selections_records = @($selections).Count
        export_file_count = @(Get-ChildItem -LiteralPath $candidatePath -File -Recurse).Count
        report_files_missing = @()
    }
    $manifestRows += [pscustomobject]@{ tactic_name = $tacticName; trial = $trialNumber }
    Write-Host ('Prepared ' + $tacticName + ' trial ' + $trialNumber + ' with native tactic and player-position exports.')
}

$tacticNames = @($manifestRows | Select-Object -ExpandProperty tactic_name -Unique | Sort-Object)
if ($tacticNames.Count -ne 2) { throw ('Expected two tactic groups; found ' + $tacticNames.Count + '.') }
foreach ($tacticName in $tacticNames) {
    $group = @($manifestRows | Where-Object tactic_name -eq $tacticName | Sort-Object trial)
    if ($group.Count -ne 3 -or (@($group | ForEach-Object { [int]$_.trial }) -join ',') -ne '1,2,3') {
        throw ('Preserved trials are incomplete for tactic: ' + $tacticName)
    }
}

foreach ($file in @('catalog.json', 'FM27_Role_PI_Permissions.csv', 'FM27_PlayerIdentityCache_Formal_v1.1.json')) {
    $sourcePath = Join-Path $repoRoot $file
    if (Test-Path -LiteralPath $sourcePath -PathType Leaf) {
        Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $artifactRoot $file) -Force
    }
}

Write-Host 'Rebuilding base six-trial comparison from the preserved exports.'
& $pythonPath $comparisonScript --runs-root $runsRoot --output-dir $comparisonRoot --team-id 539 --club-uid 680
if ($LASTEXITCODE -ne 0) { throw 'Base six-trial comparison failed.' }

$inventoryPath = Join-Path $artifactRoot 'analysis-input-inventory.json'
[ordered]@{
    source_run_id = $SourceRunId
    prepared_by_run_id = $env:GITHUB_RUN_ID
    repository = $repo
    tactic_names = [string[]]$tacticNames
    trial_inventory = @($inventory)
    native_tactic_exports_included = $true
    player_position_history_included = $true
    selected_native_tactic_settings = 'tactics.json and selections.json preserved per trial'
} | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $inventoryPath -Encoding UTF8

Write-Host ('Analysis input bundle prepared: ' + $artifactRoot)
Write-Host 'The bundle contains all six complete first-team exports, native tactics.json/selections.json, position history, role/position catalog and base comparison outputs.'
