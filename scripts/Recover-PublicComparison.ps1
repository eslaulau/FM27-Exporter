[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+$')]
    [string]$SourceRunId
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.IO.Compression.FileSystem

$repo = $env:GITHUB_REPOSITORY
$resultsTag = 'fm27-exports'
$teamId = 539
$clubUid = 680
if ([string]::IsNullOrWhiteSpace($repo) -or [string]::IsNullOrWhiteSpace($env:GH_TOKEN) -or
    [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP) -or [string]::IsNullOrWhiteSpace($env:GITHUB_RUN_ID) -or
    [string]::IsNullOrWhiteSpace($env:GITHUB_WORKSPACE)) {
    throw 'Required GitHub Actions environment is missing.'
}

$repoRoot = Split-Path -Parent $PSScriptRoot
$comparisonScript = Join-Path $repoRoot 'FM27_Tactic_Trial_Comparison_v1.0.py'
if (-not (Test-Path -LiteralPath $comparisonScript -PathType Leaf)) { throw 'Tactic comparison script is missing.' }
$ghPath = (Get-Command gh -ErrorAction Stop).Source
$runRoot = Join-Path $env:RUNNER_TEMP ('FM27-Recovery-' + $SourceRunId + '-' + $env:GITHUB_RUN_ID)
$downloadRoot = Join-Path $runRoot 'downloads'
$diagnosticRoot = Join-Path $runRoot 'diagnostics'
$partialPackagesRoot = Join-Path $diagnosticRoot 'PartialPackages'
$saveRoot = Join-Path $env:GITHUB_WORKSPACE '_recovered-runtime\saves'
$packageRoot = Join-Path $runRoot 'packages'
$comparisonRoot = Join-Path $runRoot 'comparison'
foreach ($dir in @($downloadRoot, $saveRoot, $packageRoot)) { $null = New-Item -ItemType Directory -Path $dir -Force }

$diagnosticAsset = 'FM27_TacticComparison_Diagnostics_' + $SourceRunId + '.zip'
Write-Host ('Downloading preserved diagnostic package from run ' + $SourceRunId + '.')
& $ghPath release download $resultsTag --repo $repo --pattern $diagnosticAsset --dir $downloadRoot --clobber
if ($LASTEXITCODE -ne 0) { throw ('Could not download diagnostic package ' + $diagnosticAsset + '.') }
$diagnosticZip = Join-Path $downloadRoot $diagnosticAsset
if (-not (Test-Path -LiteralPath $diagnosticZip -PathType Leaf)) { throw 'Downloaded diagnostic package is missing.' }
Expand-Archive -LiteralPath $diagnosticZip -DestinationPath $diagnosticRoot -Force
if (-not (Test-Path -LiteralPath $partialPackagesRoot -PathType Container)) { throw 'Diagnostic package contains no preserved trial exports.' }

$sourceFailurePath = Join-Path $diagnosticRoot 'failure.json'
if (Test-Path -LiteralPath $sourceFailurePath -PathType Leaf) {
    $sourceFailure = Get-Content -LiteralPath $sourceFailurePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([string]$sourceFailure.failed_stage -ne 'Build export summary') {
        throw ('Recovery is restricted to summary-stage failures. Source failed at: ' + [string]$sourceFailure.failed_stage)
    }
}

$requiredOutputs = @(
    'save-info.json', 'validation.json', 'first-team-scope.json',
    'fixtures.json', 'team-match-stats.json', 'players.json',
    'player-season-stats.csv', 'player-match-report-formal-all.csv',
    'player-match-report-formal-summary.json', 'player-report-identity-audit.json'
)
$sourcePackages = @(Get-ChildItem -LiteralPath $partialPackagesRoot -Directory | Sort-Object Name)
if ($sourcePackages.Count -ne 6) { throw ('Expected six preserved trial packages; found ' + $sourcePackages.Count + '.') }

$statusRows = @()
$manifestRows = @()
$uploadFiles = @()
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
        # The original package copy flattened the analysis directory into Export.
        $candidatePath = $exportContainer
        $candidateName = 'FM27_Analysis_Recovered'
    } else {
        throw ('Expected a nested FM27_Analysis folder or flattened export files in ' + $sourcePackage.Name + '.')
    }
    $missingOutputs = @()
    foreach ($requiredName in $requiredOutputs) {
        if (-not (Test-Path -LiteralPath (Join-Path $candidatePath $requiredName) -PathType Leaf)) { $missingOutputs += $requiredName }
    }
    $scopeCheck = $false
    $scopePath = Join-Path $candidatePath 'first-team-scope.json'
    if (Test-Path -LiteralPath $scopePath -PathType Leaf) {
        $scope = Get-Content -LiteralPath $scopePath -Raw -Encoding UTF8 | ConvertFrom-Json
        $scopeCheck = ([int]$scope.team_id -eq $teamId -and [int]$scope.club_uid -eq $clubUid)
    }
    $gameDate = ''
    $saveInfoPath = Join-Path $candidatePath 'save-info.json'
    if (Test-Path -LiteralPath $saveInfoPath -PathType Leaf) {
        $saveInfo = Get-Content -LiteralPath $saveInfoPath -Raw -Encoding UTF8 | ConvertFrom-Json
        $gameDate = [string]$saveInfo.game_date
    }
    if ($missingOutputs.Count -gt 0 -or -not $scopeCheck) {
        throw ('Preserved export failed required-output or first-team-scope validation: ' + [string]$saveManifest.source_asset)
    }

    $slotFolder = Join-Path $saveRoot $sourcePackage.Name
    $null = New-Item -ItemType Directory -Path $slotFolder -Force
    Copy-Item -LiteralPath $manifestPath -Destination $slotFolder -Force
    $slotAnalysisFolder = Join-Path $slotFolder $candidateName
    $null = New-Item -ItemType Directory -Path $slotAnalysisFolder -Force
    Get-ChildItem -LiteralPath $candidatePath -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $slotAnalysisFolder -Recurse -Force
    }

    $packageSlot = Join-Path $packageRoot $sourcePackage.Name
    $packageExportRoot = Join-Path $packageSlot 'Export'
    $packageAnalysisFolder = Join-Path $packageExportRoot $candidateName
    $null = New-Item -ItemType Directory -Path $packageAnalysisFolder -Force
    Get-ChildItem -LiteralPath $candidatePath -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $packageAnalysisFolder -Recurse -Force
    }
    Copy-Item -LiteralPath $manifestPath -Destination $packageSlot -Force
    $sourceLogs = Join-Path $sourcePackage.FullName 'RunnerLogs'
    if (Test-Path -LiteralPath $sourceLogs -PathType Container) {
        Copy-Item -LiteralPath $sourceLogs -Destination $packageSlot -Recurse -Force
    }

    $packageZip = Join-Path $runRoot ('FM27_FirstTeam_' + $sourcePackage.Name + '_' + $env:GITHUB_RUN_ID + '.zip')
    [System.IO.Compression.ZipFile]::CreateFromDirectory($packageSlot, $packageZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
    $uploadFiles += $packageZip
    $manifestRows += [pscustomobject]@{ tactic_name = $tacticName; trial = $trialNumber }
    $statusRows += [pscustomobject]@{
        tactic_name = $tacticName
        trial = $trialNumber
        source_asset = [string]$saveManifest.source_asset
        source_size_bytes = [int64]$saveManifest.size_bytes
        source_sha256 = [string]$saveManifest.sha256
        game_date = $gameDate
        status = 'exported'
        process_exit_code = 0
        output_directory_created = $true
        required_output_files_missing = @()
        first_team_scope_check_passed = $true
        report_zip_name = [System.IO.Path]::GetFileName($packageZip)
        recovered_from_run_id = $SourceRunId
    }
}

$tacticNames = @($manifestRows | Select-Object -ExpandProperty tactic_name -Unique | Sort-Object)
if ($tacticNames.Count -ne 2) { throw ('Expected two tactic groups, found ' + $tacticNames.Count + '.') }
foreach ($tacticName in $tacticNames) {
    $group = @($manifestRows | Where-Object tactic_name -eq $tacticName | Sort-Object trial)
    if ($group.Count -ne 3 -or (@($group | ForEach-Object { [int]$_.trial }) -join ',') -ne '1,2,3') {
        throw ('Preserved trials are incomplete for tactic: ' + $tacticName)
    }
}

Write-Host 'Rebuilding comparison from the six preserved exports. The FM27 saves will not be re-parsed.'
$pythonPath = (Get-Command python -ErrorAction Stop).Source
& $pythonPath $comparisonScript --runs-root $saveRoot --output-dir $comparisonRoot --team-id $teamId --club-uid $clubUid
if ($LASTEXITCODE -ne 0) { throw 'Rebuilding comparison from preserved exports failed.' }

$comparisonZip = Join-Path $runRoot ('FM27_Tactic_Comparison_' + $env:GITHUB_RUN_ID + '.zip')
[System.IO.Compression.ZipFile]::CreateFromDirectory($comparisonRoot, $comparisonZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
$uploadFiles += $comparisonZip

$summary = [ordered]@{
    exporter_version = '1.4.5'
    parser_version = 'fmsave==0.12.4'
    run_id = $env:GITHUB_RUN_ID
    recovered_from_run_id = $SourceRunId
    created_at_utc = [DateTime]::UtcNow.ToString('o')
    repository = $repo
    source_release = 'fm27-saves'
    selected_save_set = 'all'
    test_saves = [object[]]$statusRows
    tactic_names = [string[]]$tacticNames
    comparison_zip_name = [System.IO.Path]::GetFileName($comparisonZip)
    notes = @(
        'The six full-season exports were recovered from the preserved diagnostic package; no source FM27 save was re-parsed.',
        'The -1, -2 and -3 saves are treated as three independent full-season simulation trials for each tactic.',
        'Different scores across repeat simulations are expected; comparisons use per-trial outcomes, averages and variation.',
        'The source run failed only while building its export summary, after all six exports and comparison analysis had completed.'
    )
}
$summaryPath = Join-Path $runRoot ('FM27_Tactic_Comparison_' + $env:GITHUB_RUN_ID + '_summary.json')
ConvertTo-Json -InputObject $summary -Depth 12 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
$uploadFiles += $summaryPath

Write-Host 'Publishing six preserved trial packages, comparison reports and recovered summary.'
$uploadArgs = @('release', 'upload', $resultsTag) + $uploadFiles + @('--repo', $repo, '--clobber')
& $ghPath @uploadArgs
if ($LASTEXITCODE -ne 0) { throw 'Could not publish recovered trial packages and comparison reports.' }

$comparisonSummaryPath = Join-Path $comparisonRoot 'comparison-summary.json'
if (Test-Path -LiteralPath $comparisonSummaryPath -PathType Leaf) {
    $comparisonSummary = Get-Content -LiteralPath $comparisonSummaryPath -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($row in $comparisonSummary.tactic_comparison) {
        Write-Host ('Recovered result: ' + $row.tactic_name + ' mean PPG=' + $row.points_per_game_mean + ', mean W-D-L=' + $row.wins_mean + '-' + $row.draws_mean + '-' + $row.losses_mean + ', mean GD=' + $row.goal_difference_mean)
    }
}
Write-Host ('Recovery complete. Reports: https://github.com/' + $repo + '/releases/tag/' + $resultsTag)
