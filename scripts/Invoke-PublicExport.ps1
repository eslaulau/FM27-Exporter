[CmdletBinding()]
param(
    [ValidateSet('all', 'tactic1', 'tactic2')]
    [string]$SaveSet = 'all'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
Add-Type -AssemblyName System.IO.Compression.FileSystem

$repo = $env:GITHUB_REPOSITORY
$sourceTag = 'fm27-saves'
$resultsTag = 'fm27-exports'
$historyAssetName = 'FM27_PlayerMatchHistoryArchives.zip'
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
$comparisonScript = Join-Path $repoRoot 'FM27_Tactic_Trial_Comparison_v1.0.py'
$identityCachePath = Join-Path $repoRoot 'FM27_PlayerIdentityCache_Formal_v1.1.json'
foreach ($requiredPath in @($exporterPath, $comparisonScript, $identityCachePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw ('Required exporter file is missing: ' + (Split-Path -Leaf $requiredPath))
    }
}

$runRoot = Join-Path $env:RUNNER_TEMP ('FM27-TacticComparison-' + $env:GITHUB_RUN_ID)
$downloadRoot = Join-Path $runRoot 'downloads'
$saveRoot = Join-Path $env:GITHUB_WORKSPACE '_public-runtime\saves'
$historyCacheRoot = Join-Path $runRoot 'history-cache'
$packageRoot = Join-Path $runRoot 'packages'
$logRoot = Join-Path $runRoot 'runner-logs'
$comparisonRoot = Join-Path $runRoot 'comparison'
$resultsReleaseExists = $false
$stage = 'Initialize'

foreach ($dir in @($downloadRoot, $saveRoot, $historyCacheRoot, $packageRoot, $logRoot)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

$statuses = New-Object System.Collections.Generic.List[object]
$uploadFiles = New-Object System.Collections.Generic.List[string]
$manifest = @()

try {
    $stage = 'Prepare public results release'
    Write-Host 'Preparing public report release.'
    & $ghPath release view $resultsTag --repo $repo *> $null
    $resultsReleaseExists = ($LASTEXITCODE -eq 0)
    if (-not $resultsReleaseExists) {
        & $ghPath release create $resultsTag --repo $repo --target main --title 'FM27 Tactic Comparison Results' --notes 'Public FM27 six-trial tactical comparison: individual full-season exports, match/player analysis, summary and persistent history archives.' *> $null
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the public results release.' }
        $resultsReleaseExists = $true
    }

    $stage = 'Discover and validate the six public tactic saves'
    Write-Host 'Reading public save manifest from Release fm27-saves.'
    $releaseJson = & $ghPath api ("repos/$repo/releases/tags/$sourceTag") 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Cannot read public source release fm27-saves.' }
    $sourceRelease = ($releaseJson -join '') | ConvertFrom-Json

    foreach ($asset in @($sourceRelease.assets)) {
        if ([string]$asset.name -match '^(?<tactic>.+)-(?<trial>[1-3])\.fm$') {
            $tacticName = [string]$Matches['tactic']
            $trialNumber = [int]$Matches['trial']
            $safeTactic = ($tacticName -replace '[^A-Za-z0-9._-]', '_')
            $key = $safeTactic + '__run-' + $trialNumber
            $manifest += [pscustomobject]@{
                TacticName = $tacticName
                Trial = $trialNumber
                Key = $key
                Asset = [string]$asset.name
                Bytes = [int64]$asset.size
                Sha256 = ''
            }
        }
    }

    if ($manifest.Count -ne 6) {
        throw ('Expected exactly six .fm files named TacticName-1/2/3.fm in Release fm27-saves; found ' + $manifest.Count + '.')
    }

    $tacticNames = @($manifest | Select-Object -ExpandProperty TacticName -Unique | Sort-Object)
    if ($tacticNames.Count -ne 2) { throw ('Expected exactly two tactic groups; found ' + $tacticNames.Count + '.') }
    foreach ($tacticName in $tacticNames) {
        $group = @($manifest | Where-Object TacticName -eq $tacticName | Sort-Object Trial)
        $trialSequence = (@($group | ForEach-Object { [int]$_.Trial }) -join ',')
        if ($group.Count -ne 3 -or $trialSequence -ne '1,2,3') {
            throw ('Tactic group "' + $tacticName + '" must contain exactly -1, -2 and -3 saves.')
        }
    }

    if ($SaveSet -eq 'tactic1') { $manifest = @($manifest | Where-Object TacticName -eq $tacticNames[0]) }
    elseif ($SaveSet -eq 'tactic2') { $manifest = @($manifest | Where-Object TacticName -eq $tacticNames[1]) }
    $manifest = @($manifest | Sort-Object TacticName, Trial)

    Write-Host ('Tactic groups: ' + ($tacticNames -join ' | '))
    Write-Host ('Selected test saves: ' + $manifest.Count)

    $stage = 'Restore previous public history archive'
    Write-Host 'Restoring previous per-save history archives, if present.'
    & $ghPath release download $resultsTag --repo $repo --pattern $historyAssetName --dir $downloadRoot --clobber *> $null
    if ($LASTEXITCODE -eq 0) {
        Expand-Archive -LiteralPath (Join-Path $downloadRoot $historyAssetName) -DestinationPath $historyCacheRoot -Force
    }

    $powershellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    foreach ($item in $manifest) {
        $stage = 'Download and verify ' + $item.Asset
        Write-Host ('Downloading and verifying ' + $item.Asset)
        $slotFolder = Join-Path $saveRoot $item.Key
        New-Item -ItemType Directory -Path $slotFolder -Force | Out-Null

        $priorSlotCache = Join-Path $historyCacheRoot $item.Key
        $cachedArchivePath = Join-Path $priorSlotCache 'FM27_PlayerMatchHistoryArchives'
        if (Test-Path -LiteralPath $cachedArchivePath -PathType Container) {
            Copy-Item -LiteralPath $cachedArchivePath -Destination $slotFolder -Recurse -Force
        }

        & $ghPath release download $sourceTag --repo $repo --pattern $item.Asset --dir $downloadRoot --clobber *> $null
        if ($LASTEXITCODE -ne 0) { throw ('Could not download ' + $item.Asset + '.') }
        $downloadedSave = Join-Path $downloadRoot $item.Asset
        if (-not (Test-Path -LiteralPath $downloadedSave -PathType Leaf)) { throw ('Downloaded save is missing: ' + $item.Asset) }

        $saveInfo = Get-Item -LiteralPath $downloadedSave
        if ($saveInfo.Length -ne $item.Bytes) { throw ('Release asset size changed during download: ' + $item.Asset) }
        $item.Sha256 = (Get-FileHash -LiteralPath $downloadedSave -Algorithm SHA256).Hash.ToLowerInvariant()

        $savePath = Join-Path $slotFolder $item.Asset
        Copy-Item -LiteralPath $downloadedSave -Destination $savePath -Force
        $saveManifest = [ordered]@{
            tactic_name = $item.TacticName
            trial = $item.Trial
            source_asset = $item.Asset
            size_bytes = $item.Bytes
            sha256 = $item.Sha256
            source_release = $sourceTag
            team_id = $teamId
            club_uid = $clubUid
        }
        $saveManifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $slotFolder 'save-manifest.json') -Encoding UTF8

        $stage = 'Run exporter for ' + $item.Asset
        Write-Host ('Running full-season export: ' + $item.TacticName + ' trial ' + $item.Trial)
        $stdoutPath = Join-Path $logRoot ($item.Key + '.stdout.txt')
        $stderrPath = Join-Path $logRoot ($item.Key + '.stderr.txt')
        $argumentLine = '-NoLogo -NoProfile -ExecutionPolicy Bypass -File "' + $exporterPath + '" -SavePath "' + $savePath + '"'
        $proc = Start-Process -FilePath $powershellExe -ArgumentList $argumentLine -Wait -PassThru -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath

        $candidate = Get-ChildItem -LiteralPath $slotFolder -Directory -Filter 'FM27_Analysis_*' -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1

        $packageSlot = Join-Path $packageRoot $item.Key
        New-Item -ItemType Directory -Path $packageSlot -Force | Out-Null
        if ($candidate) { Copy-Item -LiteralPath $candidate.FullName -Destination (Join-Path $packageSlot 'Export') -Recurse -Force }
        Copy-Item -LiteralPath (Join-Path $slotFolder 'save-manifest.json') -Destination $packageSlot -Force

        $runnerLogFolder = Join-Path $packageSlot 'RunnerLogs'
        New-Item -ItemType Directory -Path $runnerLogFolder -Force | Out-Null
        foreach ($logFile in @($stdoutPath, $stderrPath)) {
            if (Test-Path -LiteralPath $logFile -PathType Leaf) {
                Copy-Item -LiteralPath $logFile -Destination $runnerLogFolder -Force
            }
        }

        $stage = 'Validate export for ' + $item.Asset
        $requiredOutputs = @(
            'save-info.json', 'validation.json', 'first-team-scope.json',
            'fixtures.json', 'team-match-stats.json', 'players.json',
            'player-season-stats.csv', 'player-match-report-formal-all.csv',
            'player-match-report-formal-summary.json', 'player-report-identity-audit.json'
        )
        $missingOutputs = @()
        if ($candidate) {
            foreach ($requiredName in $requiredOutputs) {
                if (-not (Test-Path -LiteralPath (Join-Path $candidate.FullName $requiredName) -PathType Leaf)) {
                    $missingOutputs += $requiredName
                }
            }
        } else { $missingOutputs = $requiredOutputs }

        $scopeCheck = $false
        $gameDate = ''
        if ($candidate -and (Test-Path -LiteralPath (Join-Path $candidate.FullName 'first-team-scope.json'))) {
            try {
                $scope = Get-Content -LiteralPath (Join-Path $candidate.FullName 'first-team-scope.json') -Raw -Encoding UTF8 | ConvertFrom-Json
                $scopeCheck = ([int]$scope.team_id -eq $teamId -and [int]$scope.club_uid -eq $clubUid)
                if (Test-Path -LiteralPath (Join-Path $candidate.FullName 'save-info.json')) {
                    $info = Get-Content -LiteralPath (Join-Path $candidate.FullName 'save-info.json') -Raw -Encoding UTF8 | ConvertFrom-Json
                    $gameDate = [string]$info.game_date
                }
            } catch { $scopeCheck = $false }
        }

        $status = if ($proc.ExitCode -eq 0 -and $missingOutputs.Count -eq 0 -and $scopeCheck) { 'exported' } else { 'partial_or_failed' }
        $packageZip = Join-Path $runRoot ('FM27_FirstTeam_' + $item.Key + '_' + $env:GITHUB_RUN_ID + '.zip')
        [System.IO.Compression.ZipFile]::CreateFromDirectory($packageSlot, $packageZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
        $uploadFiles.Add($packageZip)
        $statuses.Add([pscustomobject]@{
            tactic_name = $item.TacticName
            trial = $item.Trial
            source_asset = $item.Asset
            source_size_bytes = $item.Bytes
            source_sha256 = $item.Sha256
            game_date = $gameDate
            status = $status
            process_exit_code = [int]$proc.ExitCode
            output_directory_created = [bool]($null -ne $candidate)
            required_output_files_missing = $missingOutputs
            first_team_scope_check_passed = [bool]$scopeCheck
            report_zip_name = [System.IO.Path]::GetFileName($packageZip)
        })
    }

    $stage = 'Persist per-save player match history archives'
    Write-Host 'Persisting each trial history archive separately.'
    foreach ($item in $manifest) {
        $slotFolder = Join-Path $saveRoot $item.Key
        $slotArchivePath = Join-Path $slotFolder 'FM27_PlayerMatchHistoryArchives'
        if (Test-Path -LiteralPath $slotArchivePath -PathType Container) {
            $targetSlotCache = Join-Path $historyCacheRoot $item.Key
            New-Item -ItemType Directory -Path $targetSlotCache -Force | Out-Null
            $targetArchive = Join-Path $targetSlotCache 'FM27_PlayerMatchHistoryArchives'
            if (Test-Path -LiteralPath $targetArchive) { Remove-Item -LiteralPath $targetArchive -Recurse -Force }
            Copy-Item -LiteralPath $slotArchivePath -Destination $targetSlotCache -Recurse -Force
        }
    }

    if ((Get-ChildItem -LiteralPath $historyCacheRoot -Force -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0) {
        $historyZip = Join-Path $runRoot $historyAssetName
        [System.IO.Compression.ZipFile]::CreateFromDirectory($historyCacheRoot, $historyZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
        $uploadFiles.Add($historyZip)
    }

    $stage = 'Build cross-trial comparison analysis'
    Write-Host 'Building the six-save tactic comparison.'
    $comparisonExe = (Get-Command python -ErrorAction Stop).Source
    & $comparisonExe $comparisonScript --runs-root $saveRoot --output-dir $comparisonRoot --team-id $teamId --club-uid $clubUid
    if ($LASTEXITCODE -ne 0) { throw 'Tactic comparison analysis script failed.' }

    $comparisonZip = Join-Path $runRoot ('FM27_Tactic_Comparison_' + $env:GITHUB_RUN_ID + '.zip')
    [System.IO.Compression.ZipFile]::CreateFromDirectory($comparisonRoot, $comparisonZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
    $uploadFiles.Add($comparisonZip)

    $stage = 'Build export summary'
    $summary = [ordered]@{
        exporter_version = '1.4.5'
        parser_version = 'fmsave==0.12.4'
        run_id = $env:GITHUB_RUN_ID
        created_at_utc = [DateTime]::UtcNow.ToString('o')
        repository = $repo
        source_release = $sourceTag
        selected_save_set = $SaveSet
        test_saves = @($statuses)
        tactic_names = @($tacticNames)
        comparison_zip_name = [System.IO.Path]::GetFileName($comparisonZip)
        notes = @(
            'The -1, -2 and -3 saves are treated as three independent full-season simulation trials for each tactic.',
            'Different scores across repeat simulations are expected; comparisons use per-trial outcomes, averages and variation, not exact score equality.',
            'Selected role and live personal instructions are not reliably decoded by the current parser.',
            'The FM27 27.0.1+2494687 team-match-stats compatibility path is experimental where labelled.'
        )
    }
    $summaryPath = Join-Path $runRoot ('FM27_Tactic_Comparison_' + $env:GITHUB_RUN_ID + '_summary.json')
    $summary | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $summaryPath -Encoding UTF8
    $uploadFiles.Add($summaryPath)

    $stage = 'Upload public comparison packages'
    Write-Host 'Uploading six trial exports and comparison analysis to public Release fm27-exports.'
    $uploadArgs = @('release', 'upload', $resultsTag) + @($uploadFiles.ToArray()) + @('--repo', $repo, '--clobber')
    & $ghPath @uploadArgs *> $null
    if ($LASTEXITCODE -ne 0) { throw 'Could not upload report packages to the public results release.' }

    $failedCount = @($statuses | Where-Object status -ne 'exported').Count
    Write-Host ('Completed trial exports: ' + (@($statuses | Where-Object status -eq 'exported').Count) + '/' + $statuses.Count)
    Write-Host ('Public comparison reports: https://github.com/' + $repo + '/releases/tag/' + $resultsTag)
    if ($failedCount -gt 0) { throw 'One or more trial exports are partial or failed. Inspect the public summary and diagnostic package.' }
}
catch {
    $caughtError = $_
    $diagnosticsUploaded = $false
    try {
        $diagnosticRoot = Join-Path $runRoot 'failure-diagnostics'
        New-Item -ItemType Directory -Path $diagnosticRoot -Force | Out-Null
        if (Test-Path -LiteralPath $logRoot -PathType Container) {
            Copy-Item -LiteralPath $logRoot -Destination (Join-Path $diagnosticRoot 'RunnerLogs') -Recurse -Force
        }
        if (Test-Path -LiteralPath $packageRoot -PathType Container) {
            Copy-Item -LiteralPath $packageRoot -Destination (Join-Path $diagnosticRoot 'PartialPackages') -Recurse -Force
        }
        $failureRecord = [ordered]@{
            run_id = $env:GITHUB_RUN_ID
            failed_stage = $stage
            occurred_at_utc = [DateTime]::UtcNow.ToString('o')
            exception_message = [string]$caughtError.Exception.Message
            script_stack_trace = [string]$caughtError.ScriptStackTrace
            selected_save_set = $SaveSet
            discovered_saves = @($manifest | ForEach-Object { $_.Asset })
            note = 'Public diagnostics. Source save files are excluded from this diagnostic ZIP.'
        }
        $failureRecord | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath (Join-Path $diagnosticRoot 'failure.json') -Encoding UTF8
        $diagnosticZip = Join-Path $runRoot ('FM27_TacticComparison_Diagnostics_' + $env:GITHUB_RUN_ID + '.zip')
        [System.IO.Compression.ZipFile]::CreateFromDirectory($diagnosticRoot, $diagnosticZip, [System.IO.Compression.CompressionLevel]::Optimal, $false)
        if (-not $resultsReleaseExists) {
            & $ghPath release create $resultsTag --repo $repo --target main --title 'FM27 Tactic Comparison Results' --notes 'Public FM27 tactic comparison reports and diagnostics.' *> $null
            $resultsReleaseExists = ($LASTEXITCODE -eq 0)
        }
        if ($resultsReleaseExists) {
            & $ghPath release upload $resultsTag $diagnosticZip --repo $repo --clobber *> $null
            $diagnosticsUploaded = ($LASTEXITCODE -eq 0)
        }
    } catch { $diagnosticsUploaded = $false }

    Write-Host ('Public tactic comparison stopped at stage: ' + $stage + '.') -ForegroundColor Red
    Write-Host ('Failure detail: ' + [string]$caughtError.Exception.Message) -ForegroundColor Red
    if ($diagnosticsUploaded) { Write-Host 'Public diagnostic package uploaded to fm27-exports.' -ForegroundColor Yellow }
    else { Write-Host 'Public diagnostic package could not be uploaded.' -ForegroundColor Yellow }
    throw ('Public tactic comparison failed at stage: ' + $stage + '. ' + [string]$caughtError.Exception.Message)
}
finally {
    # The six source saves remain public Release assets; only transient working copies live here.
}
