[CmdletBinding()]
param(
    [ValidateSet('all', 'save1', 'save2', 'save3')]
    [string]$SaveSet = 'all'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.IO.Compression.FileSystem

$privateRepo = 'eslaulau/FM27'
$sourceTag = 'fm'
$resultsTag = 'fm27-exports'
$privateCacheRef = 'd25a77071544f4bf9842389b5ca649dfdb5d2033'
$expectedCacheBlobSha = 'c4077ea938ecb6987e9262a90dba3554cd40ba35'
$privateCachePath = 'FM27-download-only-v1.4.5/FM27_PlayerIdentityCache_Formal_v1.1.json'
$cacheAssetName = 'FM27_PlayerMatchHistoryArchives.zip'

$manifest = @(
    [pscustomobject]@{ Slot = '1'; Key = 'save1'; Asset = 'Vanco_4Back_Vertical_01_run31-1.fm'; Bytes = [int64]110859875; Sha256 = '307ebeb47dba47ee1e06722398d647d93efa6cadb3ce85665187e83237360aa3' },
    [pscustomobject]@{ Slot = '2'; Key = 'save2'; Asset = 'Vanco_4Back_Vertical_01_run31-2.fm'; Bytes = [int64]111711774; Sha256 = '2afb1d78b1cde5d5beaa48d96df8f9a4a6c16cd651f95f9c003bf5922df6e1b6' },
    [pscustomobject]@{ Slot = '3'; Key = 'save3'; Asset = 'Vanco_4Back_Vertical_01_run31-3.fm'; Bytes = [int64]111138678; Sha256 = '610eba7688e95047903e0a1d76aec149b3756404bd0fde4d424f1e64b0143ca4' }
)

switch ($SaveSet) {
    'all'   { $selected = @($manifest) }
    'save1' { $selected = @($manifest | Where-Object Key -eq 'save1') }
    'save2' { $selected = @($manifest | Where-Object Key -eq 'save2') }
    'save3' { $selected = @($manifest | Where-Object Key -eq 'save3') }
    default { throw 'Invalid save selection.' }
}
if ([string]::IsNullOrWhiteSpace($env:GH_TOKEN)) { throw 'Missing FM27_ACCESS_TOKEN repository secret.' }
if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP) -or [string]::IsNullOrWhiteSpace($env:GITHUB_RUN_ID)) { throw 'This script must run inside GitHub Actions.' }

$ghPath = (Get-Command gh -ErrorAction Stop).Path
$repoRoot = Split-Path -Parent $PSScriptRoot
$exporterPath = Join-Path $repoRoot 'Run_FM27_Formal_Season_Export_v1.4.5.ps1'
if (-not (Test-Path -LiteralPath $exporterPath -PathType Leaf)) { throw 'Exporter main script is missing.' }

$runRoot = Join-Path $env:RUNNER_TEMP ('FM27-PrivateExport-' + $env:GITHUB_RUN_ID)
$downloadRoot = Join-Path $runRoot 'downloads'
if ([string]::IsNullOrWhiteSpace($env:GITHUB_WORKSPACE)) { throw 'Missing GitHub workspace path.' }
$saveRoot = Join-Path $env:GITHUB_WORKSPACE '_private-runtime\saves'
$historyCacheRoot = Join-Path $runRoot 'history-cache'
$packageRoot = Join-Path $runRoot 'private-packages'
$logRoot = Join-Path $runRoot 'runner-logs'
$privateCacheFile = Join-Path $repoRoot 'FM27_PlayerIdentityCache_Formal_v1.1.json'
$sourceReleaseApi = "repos/$privateRepo/releases/tags/$sourceTag"
$resultsReleaseUrl = "https://github.com/$privateRepo/releases/tag/$resultsTag"

foreach ($dir in @($downloadRoot, $saveRoot, $historyCacheRoot, $packageRoot, $logRoot)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

$statuses = New-Object System.Collections.Generic.List[object]
$uploadFiles = New-Object System.Collections.Generic.List[string]

try {
    # Validate access to the private source release without printing private metadata.
    $releaseJson = & $ghPath api $sourceReleaseApi 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read the private FM27 source release.' }
    $sourceRelease = ($releaseJson -join '') | ConvertFrom-Json
    $availableAssets = @($sourceRelease.assets | ForEach-Object { $_.name })
    foreach ($item in $selected) {
        if ($availableAssets -notcontains $item.Asset) { throw 'A selected source save asset is missing.' }
    }

    # Retrieve the player-specific identity cache at runtime only. It is never committed publicly.
    $cacheApi = "repos/$privateRepo/contents/$privateCachePath" + "?ref=$privateCacheRef"
    $cacheJson = & $ghPath api $cacheApi 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot retrieve the private player-identity cache.' }
    $cacheObject = ($cacheJson -join '') | ConvertFrom-Json
    if ($cacheObject.sha -ne $expectedCacheBlobSha -or [string]::IsNullOrWhiteSpace($cacheObject.content)) { throw 'Private player-identity cache version mismatch.' }
    $cacheBytes = [Convert]::FromBase64String(($cacheObject.content -replace '\s', ''))
    [System.IO.File]::WriteAllBytes($privateCacheFile, $cacheBytes)

    # Restore persistent history from the private results release, if available.
    & $ghPath release view $resultsTag --repo $privateRepo *> $null
    $resultsReleaseExists = ($LASTEXITCODE -eq 0)
    if ($resultsReleaseExists) {
        & $ghPath release download $resultsTag --repo $privateRepo --pattern $cacheAssetName --dir $downloadRoot --clobber *> $null
        if ($LASTEXITCODE -eq 0) { Expand-Archive -LiteralPath (Join-Path $downloadRoot $cacheAssetName) -DestinationPath $historyCacheRoot -Force }
    }

    $powershellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    foreach ($item in $selected) {
        $slotFolder = Join-Path $saveRoot ('slot-' + $item.Slot)
        New-Item -ItemType Directory -Path $slotFolder -Force | Out-Null

        # Stable per-save folders keep archive routing deterministic between workflow runs.
        $priorSlotCache = Join-Path $historyCacheRoot ('slot-' + $item.Slot)
        $cachedArchivePath = Join-Path $priorSlotCache 'FM27_PlayerMatchHistoryArchives'
        if (Test-Path -LiteralPath $cachedArchivePath -PathType Container) { Copy-Item -LiteralPath $cachedArchivePath -Destination $slotFolder -Recurse -Force }

        & $ghPath release download $sourceTag --repo $privateRepo --pattern $item.Asset --dir $downloadRoot --clobber *> $null
        if ($LASTEXITCODE -ne 0) { throw 'A selected private save could not be downloaded.' }
        $downloadedSave = Join-Path $downloadRoot $item.Asset
        if (-not (Test-Path -LiteralPath $downloadedSave -PathType Leaf)) { throw 'A selected private save download is missing.' }
        $saveInfo = Get-Item -LiteralPath $downloadedSave
        if ($saveInfo.Length -ne $item.Bytes) { throw 'A selected private save failed its expected file-size check.' }
        $actualHash = (Get-FileHash -LiteralPath $downloadedSave -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actualHash -ne $item.Sha256) { throw 'A selected private save failed its SHA256 integrity check.' }

        $savePath = Join-Path $slotFolder $item.Asset
        Copy-Item -LiteralPath $downloadedSave -Destination $savePath -Force
        $stdoutPath = Join-Path $logRoot ('slot-' + $item.Slot + '.stdout.txt')
        $stderrPath = Join-Path $logRoot ('slot-' + $item.Slot + '.stderr.txt')
        $argumentLine = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $exporterPath + '" -SavePath "' + $savePath + '"'
        $proc = Start-Process -FilePath $powershellExe -ArgumentList $argumentLine -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath

        $candidate = Get-ChildItem -LiteralPath $slotFolder -Directory -Filter 'FM27_Analysis_*' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        $packageSlot = Join-Path $packageRoot ('slot-' + $item.Slot)
        New-Item -ItemType Directory -Path $packageSlot -Force | Out-Null
        if ($candidate) { Copy-Item -LiteralPath $candidate.FullName -Destination (Join-Path $packageSlot 'Export') -Recurse -Force }
        $runnerLogFolder = Join-Path $packageSlot 'RunnerLogs'
        New-Item -ItemType Directory -Path $runnerLogFolder -Force | Out-Null
        foreach ($logFile in @($stdoutPath, $stderrPath)) { if (Test-Path -LiteralPath $logFile -PathType Leaf) { Copy-Item -LiteralPath $logFile -Destination $runnerLogFolder -Force } }

        $requiredOutputs = @('save-info.json', 'validation.json', 'first-team-scope.json', 'fixtures.json', 'players.json')
        $missingOutputs = @()
        if ($candidate) {
            foreach ($requiredName in $requiredOutputs) { if (-not (Test-Path -LiteralPath (Join-Path $candidate.FullName $requiredName) -PathType Leaf)) { $missingOutputs += $requiredName } }
        }
        else { $missingOutputs = $requiredOutputs }

        $scopeCheck = $false
        if ($candidate -and (Test-Path -LiteralPath (Join-Path $candidate.FullName 'first-team-scope.json'))) {
            try {
                $scope = Get-Content -LiteralPath (Join-Path $candidate.FullName 'first-team-scope.json') -Raw -Encoding UTF8 | ConvertFrom-Json
                $scopeCheck = ([int]$scope.team_id -eq 539 -and [int]$scope.club_uid -eq 680)
            }
            catch { $scopeCheck = $false }
        }

        $status = if ($proc.ExitCode -eq 0 -and $missingOutputs.Count -eq 0 -and $scopeCheck) { 'exported' } else { 'partial_or_failed' }
        $packageZip = Join-Path $runRoot ('FM27_FirstTeam_Export_' + $env:GITHUB_RUN_ID + '_slot' + $item.Slot + '.zip')
        [System.IO.Compression.ZipFile]::CreateFromDirectory($packageSlot, $packageZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
        $uploadFiles.Add($packageZip)
        $statuses.Add([pscustomobject]@{
            slot = $item.Slot
            status = $status
            process_exit_code = [int]$proc.ExitCode
            output_directory_created = [bool]($null -ne $candidate)
            required_output_files_missing = $missingOutputs
            first_team_scope_check_passed = [bool]$scopeCheck
            report_zip_name = [System.IO.Path]::GetFileName($packageZip)
        })
    }

    # Persist updated per-save history archives. ZipFile includes the hidden .routes folder.
    foreach ($item in $manifest) {
        $slotFolder = Join-Path $saveRoot ('slot-' + $item.Slot)
        $slotArchivePath = Join-Path $slotFolder 'FM27_PlayerMatchHistoryArchives'
        if (Test-Path -LiteralPath $slotArchivePath -PathType Container) {
            $targetSlotCache = Join-Path $historyCacheRoot ('slot-' + $item.Slot)
            New-Item -ItemType Directory -Path $targetSlotCache -Force | Out-Null
            $targetArchive = Join-Path $targetSlotCache 'FM27_PlayerMatchHistoryArchives'
            if (Test-Path -LiteralPath $targetArchive) { Remove-Item -LiteralPath $targetArchive -Recurse -Force }
            Copy-Item -LiteralPath $slotArchivePath -Destination $targetSlotCache -Recurse -Force
        }
    }

    if ((Get-ChildItem -LiteralPath $historyCacheRoot -Force -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0) {
        $historyZip = Join-Path $runRoot $cacheAssetName
        [System.IO.Compression.ZipFile]::CreateFromDirectory($historyCacheRoot, $historyZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
        $uploadFiles.Add($historyZip)
    }

    $summary = [ordered]@{
        exporter_version = '1.4.5'
        parser_version = 'fmsave==0.12.4'
        run_id = $env:GITHUB_RUN_ID
        created_at_utc = [DateTime]::UtcNow.ToString('o')
        selected_save_slots = @($selected | ForEach-Object { $_.Slot })
        results = @($statuses)
        notes = @(
            'Source saves and player identity cache remain in the private FM27 repository.',
            'Inspect validation.json, first-team-scope.json, player-report-identity-audit.json and any export-warnings.txt.',
            'The FM27 27.0.1+2494687 team-match-stats compatibility path is experimental where labelled.'
        )
    }
    $summaryPath = Join-Path $runRoot ('FM27_Export_' + $env:GITHUB_RUN_ID + '_summary.json')
    $summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    $uploadFiles.Add($summaryPath)

    if (-not $resultsReleaseExists) {
        & $ghPath release create $resultsTag --repo $privateRepo --target main --title 'FM27 Private Export Results' --notes 'Private storage for FM27 first-team export packages and persistent player-match-history archives.' *> $null
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the private results release.' }
    }
    if ($uploadFiles.Count -gt 0) {
        $uploadArgs = @('release', 'upload', $resultsTag) + @($uploadFiles.ToArray()) + @('--repo', $privateRepo, '--clobber')
        & $ghPath @uploadArgs *> $null
        if ($LASTEXITCODE -ne 0) { throw 'Could not upload report packages to the private FM27 release.' }
    }

    $failedCount = @($statuses | Where-Object status -ne 'exported').Count
    Write-Host ('Private export packages uploaded. Completed slots: ' + (@($statuses | Where-Object status -eq 'exported').Count) + '/' + $statuses.Count)
    Write-Host $resultsReleaseUrl
    if ($failedCount -gt 0) { throw 'One or more exports are partial or failed. Inspect the private report ZIP and summary JSON.' }
}
catch {
    # Keep private filenames, paths and parser output out of public Actions logs.
    Write-Host 'Private export stopped. Check the token configuration and inspect the private FM27 results release if one was created.' -ForegroundColor Red
    throw 'Private export failed. Detailed diagnostics must remain in private storage.'
}
finally {
    if (Test-Path -LiteralPath $privateCacheFile -PathType Leaf) { Remove-Item -LiteralPath $privateCacheFile -Force -ErrorAction SilentlyContinue }
}
