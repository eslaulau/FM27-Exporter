[CmdletBinding()]
param(
    [string]$AssetName,
    [string]$SourceReleaseTag = 'fm27-exports'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.IO.Compression.FileSystem

$repo = $env:GITHUB_REPOSITORY
$resultsTag = 'fm27-exports'
$sourceReleaseTag = $SourceReleaseTag
$teamId = 539
$clubUid = 680

if ([string]::IsNullOrWhiteSpace($repo) -or
    [string]::IsNullOrWhiteSpace($env:GH_TOKEN) -or
    [string]::IsNullOrWhiteSpace($env:RUNNER_TEMP) -or
    [string]::IsNullOrWhiteSpace($env:GITHUB_RUN_ID) -or
    [string]::IsNullOrWhiteSpace($env:GITHUB_WORKSPACE)) {
    throw 'Required GitHub Actions environment is missing.'
}

$ghPath = (Get-Command gh -ErrorAction Stop).Source
$repoRoot = Split-Path -Parent $PSScriptRoot
$exporterPath = Join-Path $repoRoot 'Run_FM27_Formal_Season_Export_v1.4.5.ps1'
if (-not (Test-Path -LiteralPath $exporterPath -PathType Leaf)) {
    throw 'Formal v1.4.5 season exporter is missing.'
}

$runRoot = Join-Path $env:RUNNER_TEMP ('FM27-Season-Export-' + $env:GITHUB_RUN_ID)
$downloadRoot = Join-Path $runRoot 'downloads'
$saveRoot = Join-Path $runRoot 'saves'
$packageRoot = Join-Path $env:GITHUB_WORKSPACE '_season-export-packages'
$logRoot = Join-Path $runRoot 'runner-logs'
foreach ($dir in @($downloadRoot, $saveRoot, $packageRoot, $logRoot)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

$stage = 'Read source assets'
Write-Host ('Reading source .fm assets from public Release ' + $sourceReleaseTag)
$releaseJson = & $ghPath api ("repos/$repo/releases/tags/$sourceReleaseTag")
if ($LASTEXITCODE -ne 0) { throw ('Cannot read public Release ' + $sourceReleaseTag) }
$release = ($releaseJson -join '') | ConvertFrom-Json

if ([string]::IsNullOrWhiteSpace($AssetName)) {
    $latestSaves = @($release.assets |
        Where-Object { [string]$_.name -match '\.fm$' } |
        Sort-Object @{ Expression = { [datetime]$_.updated_at }; Descending = $true } |
        Select-Object -First 2)
    if ($latestSaves.Count -ne 2) {
        throw ('Expected two latest .fm assets in Release ' + $sourceReleaseTag + '; found ' + $latestSaves.Count)
    }
} else {
    if ($AssetName -notmatch '\.fm$') { throw 'AssetName must identify a .fm save file.' }
    $latestSaves = @($release.assets | Where-Object { [string]$_.name -ceq $AssetName })
    if ($latestSaves.Count -ne 1) {
        throw ('Expected exactly one asset named ' + $AssetName + ' in Release ' + $sourceReleaseTag + '; found ' + $latestSaves.Count)
    }
    Write-Host ('Selected exact source save asset: ' + $AssetName)
}

$requiredOutputs = @(
    'save-info.json',
    'validation.json',
    'first-team-scope.json',
    'fixtures.json',
    'team-match-stats.json',
    'players.json',
    'player-season-stats.csv',
    'player-match-report-formal-all.csv',
    'player-match-report-formal-summary.json',
    'player-report-identity-audit.json'
)

$summary = New-Object System.Collections.Generic.List[object]
$uploadFiles = New-Object System.Collections.Generic.List[string]
$completed = New-Object System.Collections.Generic.List[string]
$powershellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'

foreach ($asset in $latestSaves) {
    $assetName = [string]$asset.name
    $baseName = [System.IO.Path]::GetFileNameWithoutExtension($assetName)
    $safeName = [regex]::Replace($baseName, '[^A-Za-z0-9._-]', '_')
    $slotFolder = Join-Path $saveRoot $safeName
    New-Item -ItemType Directory -Path $slotFolder -Force | Out-Null

    $stage = 'Download and verify ' + $assetName
    Write-Host ('Downloading source save asset: ' + $assetName)
    & $ghPath release download $sourceReleaseTag --repo $repo --pattern $assetName --dir $downloadRoot --clobber
    if ($LASTEXITCODE -ne 0) { throw ('Could not download ' + $assetName) }

    $downloadedSave = Join-Path $downloadRoot $assetName
    if (-not (Test-Path -LiteralPath $downloadedSave -PathType Leaf)) {
        throw ('Downloaded save is missing: ' + $assetName)
    }
    $saveInfo = Get-Item -LiteralPath $downloadedSave
    if ($saveInfo.Length -ne [int64]$asset.size) {
        throw ('Release asset byte count changed during download: ' + $assetName)
    }
    $sourceSha256 = (Get-FileHash -LiteralPath $downloadedSave -Algorithm SHA256).Hash.ToLowerInvariant()
    $savePath = Join-Path $slotFolder $assetName
    Copy-Item -LiteralPath $downloadedSave -Destination $savePath -Force

    $saveManifest = [ordered]@{
        source_repository = $repo
        source_release = $sourceReleaseTag
        source_release_url = [string]$release.html_url
        source_asset = $assetName
        source_asset_id = [int64]$asset.id
        source_uploaded_at = [string]$asset.updated_at
        source_size_bytes = [int64]$asset.size
        source_sha256 = $sourceSha256
        team_id = $teamId
        club_uid = $clubUid
        exporter = 'Run_FM27_Formal_Season_Export_v1.4.5.ps1'
        fmsave_version = '0.12.4'
    }
    $saveManifestPath = Join-Path $slotFolder 'save-manifest.json'
    $saveManifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $saveManifestPath -Encoding UTF8

    $stdoutPath = Join-Path $logRoot ($safeName + '.stdout.txt')
    $stderrPath = Join-Path $logRoot ($safeName + '.stderr.txt')
    $stage = 'Run formal season exporter for ' + $assetName
    Write-Host ('Running formal full-season export: ' + $assetName)
    $argumentLine = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $exporterPath + '" -SavePath "' + $savePath + '"'
    $proc = Start-Process -FilePath $powershellExe -ArgumentList $argumentLine -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath
    if ($proc.ExitCode -ne 0) {
        throw ('Season exporter failed for ' + $assetName + ' with exit code ' + $proc.ExitCode)
    }

    $candidate = Get-ChildItem -LiteralPath $slotFolder -Directory -Filter 'FM27_Analysis_*' -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $candidate) { throw ('Exporter created no FM27_Analysis folder for ' + $assetName) }

    $stage = 'Validate exported report for ' + $assetName
    $missingOutputs = @($requiredOutputs | Where-Object {
        -not (Test-Path -LiteralPath (Join-Path $candidate.FullName $_) -PathType Leaf)
    })
    if ($missingOutputs.Count -gt 0) {
        throw ('Export for ' + $assetName + ' is missing required files: ' + ($missingOutputs -join ', '))
    }

    $scopePath = Join-Path $candidate.FullName 'first-team-scope.json'
    $scope = Get-Content -LiteralPath $scopePath -Raw -Encoding UTF8 | ConvertFrom-Json
    if ([int]$scope.team_id -ne $teamId -or [int]$scope.club_uid -ne $clubUid) {
        throw ('First-team scope mismatch for ' + $assetName)
    }

    $saveInfoPath = Join-Path $candidate.FullName 'save-info.json'
    $exportSaveInfo = Get-Content -LiteralPath $saveInfoPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $validationPath = Join-Path $candidate.FullName 'validation.json'
    $validation = Get-Content -LiteralPath $validationPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $validationStatus = 'validation.json present'
    if ($validation.PSObject.Properties.Name -contains 'status') { $validationStatus = [string]$validation.status }

    $packageSlot = Join-Path $packageRoot $safeName
    $exportFolder = Join-Path $packageSlot $candidate.Name
    New-Item -ItemType Directory -Path $exportFolder -Force | Out-Null
    Copy-Item -LiteralPath $candidate.FullName -Destination $exportFolder -Recurse -Force
    Copy-Item -LiteralPath $saveManifestPath -Destination $packageSlot -Force
    $runnerLogs = Join-Path $packageSlot 'RunnerLogs'
    New-Item -ItemType Directory -Path $runnerLogs -Force | Out-Null
    foreach ($logPath in @($stdoutPath, $stderrPath)) {
        if (Test-Path -LiteralPath $logPath -PathType Leaf) {
            Copy-Item -LiteralPath $logPath -Destination $runnerLogs -Force
        }
    }

    $packageZip = Join-Path $runRoot ('FM27_SeasonExport_' + $safeName + '_' + $env:GITHUB_RUN_ID + '.zip')
    [System.IO.Compression.ZipFile]::CreateFromDirectory($packageSlot, $packageZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
    $uploadFiles.Add($packageZip)
    $completed.Add($assetName)

    $summary.Add([pscustomobject]@{
        source_asset = $assetName
        source_uploaded_at = [string]$asset.updated_at
        source_size_bytes = [int64]$asset.size
        source_sha256 = $sourceSha256
        game_date = [string]$exportSaveInfo.game_date
        first_team_scope_verified = $true
        required_export_files = $requiredOutputs
        validation_status = $validationStatus
        package = [System.IO.Path]::GetFileName($packageZip)
    })
    Write-Host ('Validated and packaged season report: ' + $assetName)
}

$indexSchema = if ([string]::IsNullOrWhiteSpace($AssetName)) { 'fm27-latest-two-season-exports-v1' } else { 'fm27-season-export-index-v1' }
$index = [ordered]@{
    schema = $indexSchema
    workflow_run_id = [int64]$env:GITHUB_RUN_ID
    generated_at_utc = [datetime]::UtcNow.ToString('o')
    source_repository = $repo
    source_release = $sourceReleaseTag
    source_release_url = [string]$release.html_url
    exporter = 'FM27 formal season exporter v1.4.5'
    fmsave_version = '0.12.4'
    team_id = $teamId
    club_uid = $clubUid
    source_assets = @($summary.ToArray())
}
$indexFileName = if ([string]::IsNullOrWhiteSpace($AssetName)) { 'FM27_LatestTwo_SeasonExport_Index_' + $env:GITHUB_RUN_ID + '.json' } else { 'FM27_SeasonExport_Index_' + $env:GITHUB_RUN_ID + '.json' }
$indexPath = Join-Path $packageRoot $indexFileName
$index | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $indexPath -Encoding UTF8

$uploadFiles.Add($indexPath)
$stage = 'Publish public season report packages'
Write-Host ('Publishing ' + $uploadFiles.Count + ' report assets to Release ' + $resultsTag)
& $ghPath release upload $resultsTag --repo $repo @uploadFiles --clobber
if ($LASTEXITCODE -ne 0) { throw 'Could not upload season report packages to the public Release.' }

Write-Host 'Published season reports:'
$uploadFiles | ForEach-Object { Write-Host (' - ' + (Split-Path -Leaf $_)) }
Write-Host 'Season export completed with source size, SHA256 and first-team scope verification.'
