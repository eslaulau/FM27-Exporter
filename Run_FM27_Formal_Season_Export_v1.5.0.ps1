# FM27 managed first-team + opponent match-stat exporter v1.5.0 - Windows PowerShell 5.1 compatible
# Read-only. Requires Python 3.12+ and fmsave==0.14.3 (pinned; no auto-upgrade).
# Keeps managed first-team player data and both home and away team statistics for direct first-team fixtures.
# Tactical configurations are intentionally not exported or inferred; user supplies match-to-tactic mapping.
# Opponent player profiles and unrelated opponent matches are excluded.

[CmdletBinding()]
param(
    [string]$SavePath = '',
    [string]$ReuseExportDir = '',
    [string]$HistoryArchiveDir = ''
)

# Resolve this bundle's own directory without relying on the caller's working directory.
$bundleRootCandidate = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($bundleRootCandidate)) {
    $invokedScriptPath = $MyInvocation.MyCommand.Path
    if (-not [string]::IsNullOrWhiteSpace($invokedScriptPath)) {
        $bundleRootCandidate = Split-Path -Parent $invokedScriptPath
    }
    else {
        $bundleRootCandidate = (Get-Location).Path
    }
}
if ([string]::IsNullOrWhiteSpace($bundleRootCandidate)) {
    throw 'Could not determine the full exporter bundle directory.'
}
$script:BundleRoot = [System.IO.Path]::GetFullPath($bundleRootCandidate)
if ([string]::IsNullOrWhiteSpace($SavePath)) {
    $defaultSavePath = Join-Path $env:USERPROFILE 'Documents\Sports Interactive\Football Manager 27\games\2.fm'
    if (Test-Path -LiteralPath $defaultSavePath -PathType Leaf) {
        $SavePath = $defaultSavePath
    }
    else {
        throw 'Pass -SavePath with the full path to the FM27 .fm save.'
    }
}
$script:SavePath = [System.IO.Path]::GetFullPath($SavePath)
$script:ReuseExportDir = $ReuseExportDir
$script:ReuseMode = -not [string]::IsNullOrWhiteSpace($ReuseExportDir)
$script:HistoryArchiveDir = $HistoryArchiveDir

$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'

# For standalone use, the standard Documents save location is tried when -SavePath is omitted.
$script:TeamId = $null
$script:ClubUid = $null
$script:ClubName = $null

function Invoke-NativeCapture {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $safeLabel = ($Label -replace '[^A-Za-z0-9_-]', '_')
    $stdoutPath = Join-Path $script:TempDir ($safeLabel + '.stdout.txt')
    $stderrPath = Join-Path $script:TempDir ($safeLabel + '.stderr.txt')

    if (Test-Path -LiteralPath $stdoutPath) { Remove-Item -LiteralPath $stdoutPath -Force }
    if (Test-Path -LiteralPath $stderrPath) { Remove-Item -LiteralPath $stderrPath -Force }

    & $FilePath @Arguments 1> $stdoutPath 2> $stderrPath
    $exitCode = $LASTEXITCODE

    $stdout = ''
    $stderr = ''
    if (Test-Path -LiteralPath $stdoutPath) {
        $stdout = [System.IO.File]::ReadAllText($stdoutPath)
    }
    if (Test-Path -LiteralPath $stderrPath) {
        $stderr = [System.IO.File]::ReadAllText($stderrPath)
    }

    return [pscustomobject]@{
        ExitCode = $exitCode
        StdOut = $stdout
        StdErr = $stderr
    }
}

function Add-Diagnostic {
    param([string]$Title, [string]$Text)
    if (-not [string]::IsNullOrWhiteSpace($Text)) {
        Add-Content -LiteralPath $script:DiagnosticPath -Value ('===== ' + $Title + ' =====') -Encoding UTF8
        Add-Content -LiteralPath $script:DiagnosticPath -Value $Text.Trim() -Encoding UTF8
        Add-Content -LiteralPath $script:DiagnosticPath -Value '' -Encoding UTF8
    }
}

function Resolve-ManagedClubIdentity {
    param()
    $helperPath = Join-Path $script:TempDir 'resolve_managed_club.py'
    $helper = @'
import json, sys
import fmsave
with fmsave.open(sys.argv[1]) as career:
    managed = career.managed_clubs()
    if len(managed) != 1:
        raise RuntimeError("Expected exactly one managed club; refusing to guess.")
    selected = managed[0]
    uid = int(selected.club_uid)
    clubs = [c for c in career.clubs() if int(c.uid) == uid]
    if len(clubs) != 1:
        raise RuntimeError("Managed club UID did not resolve to exactly one club.")
    club = clubs[0]
    first = [t for t in club.teams if int(t.club_uid) == uid and int(t.slot) == 0]
    if len(first) != 1:
        raise RuntimeError("Expected exactly one owned team at team slot 0; refusing to guess.")
    print(json.dumps({
        "club_uid": uid,
        "club_name": str(selected.club_name or club.name),
        "club_short_name": str(selected.club_short_name or club.short_name),
        "team_id": int(first[0].team_id),
        "team_slot": int(first[0].slot),
        "resolution": "managed_clubs UID + owned team slot 0"
    }, ensure_ascii=False))
'@
    Set-Content -LiteralPath $helperPath -Value $helper -Encoding UTF8
    $args = @()
    if ($script:PythonPrefix.Count -gt 0) { $args += $script:PythonPrefix }
    $args += @($helperPath, $script:SavePath)
    $result = Invoke-NativeCapture -FilePath $script:PythonExe -Arguments $args -Label 'resolve_managed_club'
    Add-Diagnostic -Title 'managed club identity resolution stderr' -Text $result.StdErr
    if ($result.ExitCode -ne 0 -or [string]::IsNullOrWhiteSpace($result.StdOut)) {
        throw ('Could not resolve managed club/first team from save: ' + $result.StdErr)
    }
    $identity = $result.StdOut.Trim() | ConvertFrom-Json
    if ([int]$identity.team_slot -ne 0 -or [int]$identity.club_uid -le 0 -or [int]$identity.team_id -le 0) {
        throw 'Managed club resolver returned invalid identity values.'
    }
    $script:ClubUid = [int]$identity.club_uid
    $script:ClubName = [string]$identity.club_name
    $script:TeamId = [int]$identity.team_id
    Set-Content -LiteralPath (Join-Path $script:OutDir 'managed-club.json') -Value ($identity | ConvertTo-Json -Depth 5) -Encoding UTF8
    Write-Host ("Managed club resolved: {0} | UID {1} | first-team ID {2}" -f $script:ClubName, $script:ClubUid, $script:TeamId) -ForegroundColor Green
}

function Invoke-FirstTeamDataFilter {
    param()

    $filterPath = Join-Path $script:BundleRoot 'FM27_FirstTeam_Filter_v1.3.0.py'
    if (-not (Test-Path -LiteralPath $filterPath)) {
        throw ('Required companion file missing: ' + $filterPath + ' (extract the complete v1.3.0 bundle).')
    }
    $filterArgs = @()
    if ($script:PythonPrefix.Count -gt 0) { $filterArgs += $script:PythonPrefix }
    $filterArgs += @($filterPath, $script:OutDir, '--team-id', [string]$script:TeamId, '--club-uid', [string]$script:ClubUid, '--club-name', [string]$script:ClubName)
    $filterResult = Invoke-NativeCapture -FilePath $script:PythonExe -Arguments $filterArgs -Label 'first_team_data_filter'
    if (-not [string]::IsNullOrWhiteSpace($filterResult.StdOut)) { Write-Host $filterResult.StdOut.Trim() }
    if (-not [string]::IsNullOrWhiteSpace($filterResult.StdErr)) { Write-Host $filterResult.StdErr.Trim() -ForegroundColor DarkYellow }
    if ($filterResult.ExitCode -ne 0) {
        Add-Diagnostic -Title 'first-team filter stderr' -Text $filterResult.StdErr
        throw ('First-team data filtering failed; exit code ' + $filterResult.ExitCode)
    }
}

function Invoke-PlayerMatchReportRecovery {
    param()

    $helperPath = Join-Path $script:BundleRoot 'FM27_PlayerMatchReport_Recovery_v1.9_Formal.py'
    if (-not (Test-Path -LiteralPath $helperPath)) {
        throw ('Required companion file missing: ' + $helperPath)
    }

    # Identity caches are scoped to BOTH the dynamically resolved club UID and first-team ID.
    # Never load the repository-wide historical cache as a generic seed.
    $cachePath = Join-Path $script:TempDir ('FM27_PlayerIdentityCache_Formal_v1.1_team-{0}_club-{1}.json' -f $script:TeamId, $script:ClubUid)
    $cacheObject = [ordered]@{
        cache_version = '1.2-managed-club-scoped'
        game = 'FM27'
        team_id = [int]$script:TeamId
        club_uid = [int]$script:ClubUid
        competition_id = 0
        scope = 'single save run; exact managed club UID and owned first-team ID; no cross-club seed mappings'
        seed_source = $null
        mappings = @{}
        rejected_mappings = @()
    }
    if ($script:ReuseMode) {
        $priorCachePath = Join-Path $script:OutDir 'FM27_PlayerIdentityCache_Formal_v1.1_learned.json'
        if (Test-Path -LiteralPath $priorCachePath -PathType Leaf) {
            $priorCache = Get-Content -LiteralPath $priorCachePath -Raw -Encoding UTF8 | ConvertFrom-Json
            if ([int]$priorCache.team_id -ne $script:TeamId -or [int]$priorCache.club_uid -ne $script:ClubUid) {
                throw ('Refusing identity cache reuse: cached club/team {0}/{1}, current club/team {2}/{3}.' -f $priorCache.club_uid, $priorCache.team_id, $script:ClubUid, $script:TeamId)
            }
            $cacheObject = $priorCache
        }
    }
    $cacheObject | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $cachePath -Encoding UTF8

    if ($script:ReuseMode) {
        $priorReportFiles = @(
            'player-match-report-identified.csv',
            'player-match-report-identified.json',
            'player-match-report-unresolved.csv',
            'player-report-identity-audit.json',
            'player-match-report-formal-all.csv',
            'player-match-report-formal-summary.json',
            'FM27_PlayerIdentityCache_Formal_v1.1_learned.json'
        )
        $archiveDir = Join-Path $script:OutDir ('previous-player-report-attempt_' + (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
        foreach ($priorName in $priorReportFiles) {
            $priorPath = Join-Path $script:OutDir $priorName
            if (Test-Path -LiteralPath $priorPath -PathType Leaf) {
                if (-not (Test-Path -LiteralPath $archiveDir)) {
                    New-Item -ItemType Directory -Path $archiveDir -Force | Out-Null
                }
                Move-Item -LiteralPath $priorPath -Destination (Join-Path $archiveDir $priorName) -Force
            }
        }
    }

    $helperArgs = @()
    if ($script:PythonPrefix.Count -gt 0) { $helperArgs += $script:PythonPrefix }
    $helperArgs += @(
        $helperPath,
        $script:SavePath,
        $script:OutDir,
        '--cache-file', $cachePath,
        '--team-id', [string]$script:TeamId,
        '--club-uid', [string]$script:ClubUid,
        '--competition-id', '0'
    )
    $existingProbePath = Join-Path $script:OutDir 'player-report-probe.json'
    if ($script:ReuseMode -and (Test-Path -LiteralPath $existingProbePath -PathType Leaf)) {
        $helperArgs += '--reuse-probe'
        Write-Host 'Using cached player-report-probe.json; this run will repair identities without reopening 2.fm.' -ForegroundColor Green
    }

    Write-Host ''
    Write-Host 'Recovering player detailed match reports across competitions discovered from this save (friendly/pre-season rules excluded)...' -ForegroundColor Cyan
    $result = Invoke-NativeCapture -FilePath $script:PythonExe -Arguments $helperArgs -Label 'player_match_report_recovery_formal'
    Add-Diagnostic -Title 'player match report recovery stdout' -Text $result.StdOut
    Add-Diagnostic -Title 'player match report recovery stderr' -Text $result.StdErr

    if (-not [string]::IsNullOrWhiteSpace($result.StdOut)) { Write-Host $result.StdOut.Trim() }
    if (-not [string]::IsNullOrWhiteSpace($result.StdErr)) { Write-Host $result.StdErr.Trim() -ForegroundColor DarkYellow }

    $requiredOutputs = @(
        'player-report-probe.json',
        'player-match-report-identified.csv',
        'player-match-report-identified.json',
        'player-match-report-unresolved.csv',
        'player-report-identity-audit.json',
        'player-match-report-formal-all.csv',
        'player-match-report-formal-summary.json',
        'FM27_PlayerIdentityCache_Formal_v1.1_learned.json'
    )
    $missingOutputs = @($requiredOutputs | Where-Object { -not (Test-Path -LiteralPath (Join-Path $script:OutDir $_)) })
    if ($result.ExitCode -ne 0) {
        $script:Errors.Add('formal detailed player-report helper exited non-zero; inspect native-diagnostics.txt')
    }

    if ($missingOutputs.Count -gt 0) {
        $script:Errors.Add('formal per-player detailed match report has unresolved identities or incomplete validation; inspect player-report-identity-audit.json')
        Add-Diagnostic -Title 'player match report recovery missing outputs' -Text ($missingOutputs -join "`r`n")
        if ($result.ExitCode -ne 0) {
            Add-Diagnostic -Title 'player match report recovery nonzero exit' -Text ('ExitCode=' + $result.ExitCode + "`r`n" + $result.StdErr)
        }
        Write-Host 'WARNING: detailed player report outputs are incomplete; inspect native-diagnostics.txt.' -ForegroundColor Yellow
        return
    }

    try {
        $audit = Get-Content -LiteralPath (Join-Path $script:OutDir 'player-report-identity-audit.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $identified = [int]$audit.scope.identified_appearance_rows
        $unresolved = [int]$audit.scope.unresolved_appearance_rows
        $checksPassed = [int]$audit.validation.team_total_checks.matches
        $checksTotal = [int]$audit.validation.team_total_checks.comparisons
        $checksMissing = [int]$audit.validation.team_total_checks.missing
        $checksMismatch = [int]$audit.validation.team_total_checks.mismatches
        $historyPassed = [int]$audit.validation.named_history_matches_passed
        $historyTotal = [int]$audit.validation.named_history_match_count
        Write-Host ("Detailed player rows identified: {0}; unresolved: {1}" -f $identified, $unresolved) -ForegroundColor Cyan
        Write-Host ("Team-stat reconciliation: {0}/{1}; named-history cross-check: {2}/{3}" -f $checksPassed, $checksTotal, $historyPassed, $historyTotal) -ForegroundColor Cyan
        if ($unresolved -gt 0 -or $checksPassed -ne $checksTotal -or $checksMismatch -gt 0 -or $checksMissing -gt 0 -or $historyPassed -ne $historyTotal -or -not $audit.validation.fixture_coverage.complete) {
            $script:Errors.Add('per-player report created with unresolved identities or incomplete validation; inspect player-report-identity-audit.json before analysis')
            Write-Host 'WARNING: recovery output is partial or has checks to review; unresolved rows were not guessed.' -ForegroundColor Yellow
        }
        else {
            Write-Host 'Named per-player detailed match report recovery passed its internal checks.' -ForegroundColor Green
        }
    }
    catch {
        $script:Errors.Add('could not read player-report-identity-audit.json summary; inspect the JSON and native-diagnostics.txt')
        Write-Host 'WARNING: could not summarize player-report-identity-audit.json.' -ForegroundColor Yellow
    }
}

function Export-FmTable {
    param(
        [Parameter(Mandatory = $true)][string]$TableName,
        [Parameter(Mandatory = $true)][string[]]$ExtraArgs
    )

    $format = 'json'
    $extension = '.json'
    if ($ExtraArgs -contains 'csv') {
        $format = 'csv'
        $extension = '.csv'
    }
    $outputPath = Join-Path $script:OutDir ($TableName + $extension)
    $argsList = @('export', $script:SavePath, $TableName) + $ExtraArgs + @('-o', $outputPath)

    Write-Host ('Exporting: ' + $TableName)
    $result = Invoke-NativeCapture -FilePath $script:FmsaveExe -Arguments $argsList -Label ('export_' + $TableName)
    Add-Diagnostic -Title ('export ' + $TableName + ' stderr') -Text $result.StdErr

    if ($result.ExitCode -ne 0) {
        $script:Errors.Add($TableName + ': export failed; exit code ' + $result.ExitCode)
        Write-Host ('WARNING: ' + $TableName + ' export failed. Continuing.') -ForegroundColor Yellow
    }
    elseif (-not [string]::IsNullOrWhiteSpace($result.StdErr)) {
        Write-Host ('Note: ' + $TableName + ' produced parser warnings; see native-diagnostics.txt.') -ForegroundColor Yellow
    }
    elseif (-not (Test-Path -LiteralPath $outputPath)) {
        $script:Errors.Add($TableName + ': command returned success but output file was not created')
    }
}

Write-Host ''
Write-Host 'FM27 Save Batch Exporter' -ForegroundColor Cyan
Write-Host 'Read-only: the save file will not be modified.' -ForegroundColor Green
Write-Host 'fmsave 0.14.3 can try a shared FM27 schema-matched layout for unregistered builds; review validation and compatibility audit.' -ForegroundColor Yellow
Write-Host ''

$script:TempDir = Join-Path $env:TEMP ('FM27_Fmsave_' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $script:TempDir -Force | Out-Null

try {
    # Find a working Python 3.12+ executable. Prefer python.exe, then the py launcher.
    $script:PythonExe = $null
    $script:PythonPrefix = @()
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue

    if ($pythonCommand) {
        $versionResult = Invoke-NativeCapture -FilePath $pythonCommand.Source -Arguments @('--version') -Label 'python_version'
        $versionText = ($versionResult.StdOut + ' ' + $versionResult.StdErr).Trim()
        $versionMatch = [regex]::Match($versionText, 'Python\s+(\d+)\.(\d+)')
        if ($versionResult.ExitCode -eq 0 -and $versionMatch.Success) {
            $major = [int]$versionMatch.Groups[1].Value
            $minor = [int]$versionMatch.Groups[2].Value
            if (($major -gt 3) -or (($major -eq 3) -and ($minor -ge 12))) {
                $script:PythonExe = $pythonCommand.Source
                Write-Host ('Python detected: ' + $versionText) -ForegroundColor Green
            }
        }
    }

    if (-not $script:PythonExe) {
        $pyCommand = Get-Command py -ErrorAction SilentlyContinue
        if ($pyCommand) {
            $versionResult = Invoke-NativeCapture -FilePath $pyCommand.Source -Arguments @('-3', '--version') -Label 'py_version'
            $versionText = ($versionResult.StdOut + ' ' + $versionResult.StdErr).Trim()
            $versionMatch = [regex]::Match($versionText, 'Python\s+(\d+)\.(\d+)')
            if ($versionResult.ExitCode -eq 0 -and $versionMatch.Success) {
                $major = [int]$versionMatch.Groups[1].Value
                $minor = [int]$versionMatch.Groups[2].Value
                if (($major -gt 3) -or (($major -eq 3) -and ($minor -ge 12))) {
                    $script:PythonExe = $pyCommand.Source
                    $script:PythonPrefix = @('-3')
                    Write-Host ('Python detected: ' + $versionText) -ForegroundColor Green
                }
            }
        }
    }

    if (-not $script:PythonExe) {
        throw 'Python 3.12 or newer was not found. Run: python --version'
    }

    if ($script:ReuseMode) {
        Write-Host 'Reuse mode: replaying the existing probe; the .fm save is not opened or required.' -ForegroundColor Green
    }
    else {
        Write-Host ('Using FM27 save: ' + $script:SavePath) -ForegroundColor Cyan
        if (-not (Test-Path -LiteralPath $script:SavePath -PathType Leaf)) {
            throw ('FM27 save file was not found at the supplied path: ' + $script:SavePath)
        }
    }

    $saveFolder = Split-Path -Parent $script:SavePath
    if ($script:ReuseMode) {
        $reuseResolved = Resolve-Path -LiteralPath $script:ReuseExportDir -ErrorAction Stop
        $script:OutDir = $reuseResolved.Path
        if (-not (Test-Path -LiteralPath $script:OutDir -PathType Container)) {
            throw ('ReuseExportDir is not a folder: ' + $script:OutDir)
        }
        $reuseRequired = @('managed-club.json','first-team-scope.json','fixtures.json','player-match-stats.json','player-season-stats.csv','team-match-stats.json')
        $reuseMissing = @($reuseRequired | Where-Object { -not (Test-Path -LiteralPath (Join-Path $script:OutDir $_) -PathType Leaf) })
        if ($reuseMissing.Count -gt 0) {
            throw ('Existing export folder is incomplete; missing: ' + ($reuseMissing -join ', '))
        }
        $scope = Get-Content -LiteralPath (Join-Path $script:OutDir 'first-team-scope.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([string]$scope.scope_version -ne '1.3.0-managed-first-team-match-opponents') {
            throw 'ReuseExportDir must be a v1.5.0 export with paired home/away team-match statistics.'
        }
        if ([int]$scope.team_id -le 0 -or [int]$scope.club_uid -le 0) {
            throw 'Existing folder does not contain valid managed-club identity metadata.'
        }
        $script:TeamId = [int]$scope.team_id
        $script:ClubUid = [int]$scope.club_uid
        $script:ClubName = [string]$scope.club_name
        Write-Host ('Reusing existing first-team export: ' + $script:OutDir) -ForegroundColor Cyan
        Write-Host 'The base season tables will not be exported again; only detailed formal player match reports will be regenerated.' -ForegroundColor Green
    }
    else {
        $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        $script:OutDir = Join-Path $saveFolder ('FM27_Analysis_' + $stamp)
        New-Item -ItemType Directory -Path $script:OutDir -Force | Out-Null
    }
    $script:DiagnosticPath = Join-Path $script:OutDir 'native-diagnostics.txt'
    $script:Errors = New-Object 'System.Collections.Generic.List[string]'

    # Pin the parser to the last known-good version from the original workflow.
    # Never use --upgrade here: pip must install exactly this version, even if a
    # newer release is already present in the selected Python environment.
    $script:FmsavePinnedVersion = '0.14.3'
    Write-Host ''
    Write-Host ('Installing/checking pinned fmsave ' + $script:FmsavePinnedVersion + ' (automatic upgrades disabled)...') -ForegroundColor Cyan
    $pipArgs = @()
    if ($script:PythonPrefix.Count -gt 0) { $pipArgs += $script:PythonPrefix }
    $pipArgs += @('-m', 'pip', 'install', '--disable-pip-version-check', ('fmsave==' + $script:FmsavePinnedVersion))
    $pipResult = Invoke-NativeCapture -FilePath $script:PythonExe -Arguments $pipArgs -Label 'pip_install_pinned'
    if (-not [string]::IsNullOrWhiteSpace($pipResult.StdOut)) { Write-Host $pipResult.StdOut.Trim() }
    if (-not [string]::IsNullOrWhiteSpace($pipResult.StdErr)) { Write-Host $pipResult.StdErr.Trim() -ForegroundColor DarkYellow }
    if ($pipResult.ExitCode -ne 0) {
        Add-Diagnostic -Title 'pinned fmsave install stderr' -Text $pipResult.StdErr
        throw ('Could not install/check fmsave==' + $script:FmsavePinnedVersion + '; exit code ' + $pipResult.ExitCode)
    }

    # Verify the imported Python package version before invoking its CLI.
    $fmsaveVersionArgs = @()
    if ($script:PythonPrefix.Count -gt 0) { $fmsaveVersionArgs += $script:PythonPrefix }
    $fmsaveVersionArgs += @('-c', "import fmsave; print(getattr(fmsave, '__version__', 'unknown'))")
    $fmsaveVersionResult = Invoke-NativeCapture -FilePath $script:PythonExe -Arguments $fmsaveVersionArgs -Label 'fmsave_version_check'
    if ($fmsaveVersionResult.ExitCode -ne 0) {
        Add-Diagnostic -Title 'fmsave version check stderr' -Text $fmsaveVersionResult.StdErr
        throw 'Could not verify the installed fmsave version.'
    }
    $actualFmsaveVersion = $fmsaveVersionResult.StdOut.Trim()
    if ($actualFmsaveVersion -ne $script:FmsavePinnedVersion) {
        throw ('fmsave version mismatch: expected ' + $script:FmsavePinnedVersion + ', found ' + $actualFmsaveVersion + '. Refusing to continue.')
    }
    Write-Host ('Confirmed fmsave ' + $actualFmsaveVersion + '; automatic upgrades are disabled.') -ForegroundColor Green

    $scriptsArgs = @()
    if ($script:PythonPrefix.Count -gt 0) { $scriptsArgs += $script:PythonPrefix }
    $scriptsArgs += @('-c', "import sysconfig; print(sysconfig.get_path('scripts'))")
    $scriptsResult = Invoke-NativeCapture -FilePath $script:PythonExe -Arguments $scriptsArgs -Label 'python_scripts_path'
    if ($scriptsResult.ExitCode -ne 0) { throw 'Could not locate the Python Scripts folder.' }
    $scriptsDir = $scriptsResult.StdOut.Trim()
    $script:FmsaveExe = Join-Path $scriptsDir 'fmsave.exe'

    if (-not (Test-Path -LiteralPath $script:FmsaveExe)) {
        $fmsaveCommand = Get-Command fmsave -ErrorAction SilentlyContinue
        if ($fmsaveCommand) { $script:FmsaveExe = $fmsaveCommand.Source }
    }
    if (-not (Test-Path -LiteralPath $script:FmsaveExe)) {
        throw ('fmsave.exe was not found in: ' + $scriptsDir)
    }

    if (-not $script:ReuseMode) {
        Resolve-ManagedClubIdentity
        Write-Host ''
        Write-Host 'Reading save metadata...' -ForegroundColor Cyan
        $infoResult = Invoke-NativeCapture -FilePath $script:FmsaveExe -Arguments @('info', $script:SavePath, '--json') -Label 'info'
        Add-Diagnostic -Title 'info stderr' -Text $infoResult.StdErr
        if (-not [string]::IsNullOrWhiteSpace($infoResult.StdOut)) {
            Set-Content -LiteralPath (Join-Path $script:OutDir 'save-info.json') -Value $infoResult.StdOut -Encoding UTF8
        }
        if ($infoResult.ExitCode -ne 0) { $script:Errors.Add('info: command failed; exit code ' + $infoResult.ExitCode) }
    
        Write-Host 'Validating readable sections...' -ForegroundColor Cyan
        $validationResult = Invoke-NativeCapture -FilePath $script:FmsaveExe -Arguments @('validate', $script:SavePath, '--json') -Label 'validate'
        Add-Diagnostic -Title 'validate stderr' -Text $validationResult.StdErr
        if (-not [string]::IsNullOrWhiteSpace($validationResult.StdOut)) {
            Set-Content -LiteralPath (Join-Path $script:OutDir 'validation.json') -Value $validationResult.StdOut -Encoding UTF8
        }
        if ($validationResult.ExitCode -ne 0) {
            $failedReaders = @()
            try {
                if (-not [string]::IsNullOrWhiteSpace($validationResult.StdOut)) {
                    $validationObject = $validationResult.StdOut | ConvertFrom-Json
                    $failedReaders = @($validationObject.readers | Where-Object { $_.status -ne 'ok' } | ForEach-Object { $_.reader })
                }
            }
            catch { $failedReaders = @() }
            if ($failedReaders.Count -gt 0) {
                $script:Errors.Add(('validate returned exit code {0}; readers not OK: {1}. Inspect validation.json. This is a parser-coverage warning; required exports continue. Review team-match-stats-compatibility.json for the local team-match-stats schema audit; upstream build registration is unchanged.' -f $validationResult.ExitCode, ($failedReaders -join ', ')))
            }
            else {
                $script:Errors.Add('validate returned non-zero exit code ' + $validationResult.ExitCode + '; inspect validation.json and native-diagnostics.txt. Required first-team exports continue.')
            }
        }
    
        # Export only data relevant to the managed club and its competition.
        Export-FmTable -TableName 'fixtures' -ExtraArgs @('--managed-club', '--format', 'json')
        Export-FmTable -TableName 'team-match-stats' -ExtraArgs @('--managed-club', '--format', 'json')
        Export-FmTable -TableName 'players' -ExtraArgs @('--managed-club', '--format', 'json')
        Export-FmTable -TableName 'player-season-stats' -ExtraArgs @('--managed-club', '--format', 'csv')
        Export-FmTable -TableName 'player-match-stats' -ExtraArgs @('--managed-club', '--format', 'json')
        Export-FmTable -TableName 'selections' -ExtraArgs @('--managed-club', '--format', 'json')
    
        # Keep first-team player data and both sides of direct first-team match statistics.
        Invoke-FirstTeamDataFilter
    }
    else {
        Write-Host 'Skipping base table export and first-team filtering; existing verified first-team JSON/CSV files will be reused.' -ForegroundColor Green
    }

        # Save-scoped player match history archive; conflicts are isolated, not merged.
    $historyArchiveScript = Join-Path $script:BundleRoot 'FM27_PlayerMatchHistory_Archive_v1.0.py'
    $routerScript = Join-Path $script:BundleRoot 'FM27_PlayerMatchHistory_Archive_Router_v1.0.py'
    if (-not (Test-Path -LiteralPath $historyArchiveScript -PathType Leaf)) {
        throw ('Required history archive helper missing: ' + $historyArchiveScript)
    }

    $archiveArgs = @()
    if ($script:PythonPrefix.Count -gt 0) { $archiveArgs += $script:PythonPrefix }
    if ([string]::IsNullOrWhiteSpace($script:HistoryArchiveDir)) {
        if (-not (Test-Path -LiteralPath $routerScript -PathType Leaf)) {
            throw ('Required save-scoped history archive router missing: ' + $routerScript)
        }
        $archiveRoot = Join-Path $saveFolder 'FM27_PlayerMatchHistoryArchives'
        $archiveArgs += @(
            $routerScript,
            '--archive-script', $historyArchiveScript,
            '--export-dir', $script:OutDir,
            '--save-path', $script:SavePath,
            '--archive-root', $archiveRoot,
            '--team-id', [string]$script:TeamId,
            '--club-uid', [string]$script:ClubUid
        )
        Write-Host ('Using save-scoped named match-history archives: ' + $archiveRoot) -ForegroundColor Cyan
    }
    else {
        # An explicit override is treated as an intentional request to use that exact archive.
        $script:HistoryArchiveDir = [System.IO.Path]::GetFullPath($script:HistoryArchiveDir)
        New-Item -ItemType Directory -Path $script:HistoryArchiveDir -Force | Out-Null
        $archiveArgs += @(
            $historyArchiveScript,
            '--export-dir', $script:OutDir,
            '--archive-dir', $script:HistoryArchiveDir,
            '--team-id', [string]$script:TeamId,
            '--club-uid', [string]$script:ClubUid
        )
        Write-Host ('Using explicitly selected named match-history archive: ' + $script:HistoryArchiveDir) -ForegroundColor Cyan
    }

    Write-Host ''
    $archiveResult = Invoke-NativeCapture -FilePath $script:PythonExe -Arguments $archiveArgs -Label 'player_match_history_archive'
    Add-Diagnostic -Title 'player match history archive stdout' -Text $archiveResult.StdOut
    Add-Diagnostic -Title 'player match history archive stderr' -Text $archiveResult.StdErr
    if (-not [string]::IsNullOrWhiteSpace($archiveResult.StdOut)) { Write-Host $archiveResult.StdOut.Trim() }
    if (-not [string]::IsNullOrWhiteSpace($archiveResult.StdErr)) { Write-Host $archiveResult.StdErr.Trim() -ForegroundColor DarkYellow }
    if ($archiveResult.ExitCode -ne 0) {
        throw ('Player match-history archive failed; no detailed report was regenerated. See native-diagnostics.txt. Exit code: ' + $archiveResult.ExitCode)
    }

    # Full export: read detailed match_stats_cfg rows. ReuseExportDir: restore signatures
    # from the existing raw probe and regenerate identities without opening the .fm save.
    # Named match history now comes from the persistent archive when available.
    Invoke-PlayerMatchReportRecovery

    $readmeLines = @(
        'FM27 managed first-team + opponent match-stat export bundle v1.5.0 (formal competitions)',
        'Default named player history uses a save-scoped route under FM27_PlayerMatchHistoryArchives beside the save file.',
        'Overlapping fixture or named-row conflicts automatically fork a new save-specific archive branch; conflicting histories are never merged.',
        'Parser version is pinned to fmsave==0.14.3; automatic upgrades are disabled.',
        'Save path defaults to the configured FM27 2.fm; override with -SavePath when needed.',
        'Optional -ReuseExportDir reuses an existing first-team export folder and regenerates only the detailed formal player reports.',
        '',
        'Files include managed first-team fixtures, both home and away team statistics for those fixtures, and first-team player profiles/attributes,',
        'first-team player-season-stats, first-team player-match-stats and first-team selections,',
        'managed-club.json, save-info, parser validation and first-team-scope.json.',
        'Per-player detailed match-report outputs: player-report-probe.json, player-match-report-identified.csv/json, player-match-report-unresolved.csv, player-match-report-formal-all.csv and player-match-report-formal-summary.json.',
        'Formal competitions are discovered dynamically from this save because competition IDs are save-local; friendly/pre-season match-rule family 1 is excluded.',
        'The match-report helper performs a targeted read-only pass over match_stats_cfg with fmsave==0.14.3.',
        'Identities use a persisted four-byte signature cache seeded from the validated full-season league report; cross-competition transfer limitations are recorded in the identity audit.',
        'Unmapped player rows remain anonymous and are written to player-match-report-unresolved.csv.',
        'Verified raw player-record offsets decode goals, assists, substitute entry/exit clocks, passes attempted and passes completed even when rolling named history is missing.',
        'The pinned fmsave version exposes PlayerMatchStats.entered_at_minute and PlayerSeasonStats.minutes_since_last_goal for named match history and overall club season stats.',
        'Minutes are decoded from raw entry/exit clocks when match duration is verified by named-history votes, a unique exact season-category solution, or regular-time competition/stage rules.',
        'Match ratings use the locally cross-validated uint16 little-endian field at raw-window +136 (statistics_anchor +36): hundredths divided by 100, rounded half-up to one decimal. Enable only after at least 25 exact same-match history checks pass with zero mismatches.',
        'Rows with a confirmed 0-minute appearance are omitted from player-level match reports; team-total checks still use the full raw match report.',
        'FM27 named match history is rolling (~20 rows per player/team spell across all competitions); preserve it by exporting regularly and keeping FM27_PlayerMatchHistoryArchive.',
        'Managed club and first-team ID are resolved from the save at runtime; no club/team ID is hardcoded.',
        'players.json contains only current managed first-team profiles; no reserve/youth or opponent profiles are kept.',
        'Historical reserve/youth players are retained only on individual first-team match rows where they logged minutes; their full profiles and reserve statistics are excluded.',
        'Reserve/youth match-sheet rows without minutes are removed per match, even for a guest who appeared in another match.',
        'Opponent identity, competition, date, venue and score remain as match context; opponent team-level statistics are retained for direct matches.',
        'Opponent player profiles and unrelated opponent matches are excluded; opponent-side team statistics for direct matches are retained.',
        'Tactical configurations, set-piece configurations, current tactic slots and historical tactic inference are deliberately not exported.',
        'For FM27 27.0.1+2494687 with match_stats_cfg schema 6, fmsave 0.14.3 uses an available registered FM27 schema-6 match-report layout; the exact 27.0.1 build remains unregistered and the decoded fields are not thereby in-game verified.',
        'The generated team-match-stats-compatibility.json records the reader status, borrowed layout, formal-fixture coverage, team totals and raw-field cross-checks for this save only.',
        'A local compatibility pass does not change fmsave known_build and is not a claim of upstream verification for other saves/builds.',
        'Named player history is joined to first-team fixtures by competition, date and opponent team ID.',
        'Tactical configurations and inferred historical formations are not exported. User supplies the tactic used for each match.',
        '',
        'IMPORTANT: FM27 builds newer than the parser registered build may be unverified.',
        'Some fields or readers may be unavailable. Check validation.json and',
        'native-diagnostics.txt before treating any exported data as complete.',
        'FM27_FirstTeam_Filter_v1.3.0.py enforces dynamic managed first-team scope and paired home/away match statistics.',
        'FM27_PlayerMatchReport_Recovery_v1.9_Formal.py reads each player signature at the statistics anchor minus 100 bytes and retains the full variable-length player record.',
        'Raw verified offsets from the stored player-record window: goals +20, assists +56, left-at minute +67, entered-at minute +71, passes attempted +86 and passes completed +87.',
        'Raw rating field: uint16 little-endian at raw-window +136 (statistics anchor +36), stored in hundredths and rounded half-up to one decimal after same-match history cross-validation.',
        'Raw field extraction is cross-checked against named same-match history; duration solving uses exact season-category reconciliation only as a validation of fixture length, never to fill individual match statistics.',
        'ReuseExportDir replays the existing raw player-report-probe.json and does not open the save for match_stats_cfg.',
        'Cross-competition signature-cache transfer and same-match-history singleton inference are distinguished in player-report-identity-audit.json; conflicting candidates remain unresolved.',
        'Individual goals, assists and pass totals are read from raw match records. Individual minutes are calculated from raw entry/exit clocks. Season aggregates only verify duration; they are never apportioned to players or matches.',
        'A rating is not derived from the raw match-report schema in this build. The tool keeps any exact named-history rating and leaves missing ratings empty.',
        'This tool reads the save only and never modifies it.'
    )
    Set-Content -LiteralPath (Join-Path $script:OutDir 'README.txt') -Value $readmeLines -Encoding UTF8

    if ($script:Errors.Count -gt 0) {
        Set-Content -LiteralPath (Join-Path $script:OutDir 'export-warnings.txt') -Value $script:Errors -Encoding UTF8
    }

    $zipPath = $script:OutDir + '.zip'
    if (Test-Path -LiteralPath $zipPath) { Remove-Item -LiteralPath $zipPath -Force }
    Compress-Archive -Path (Join-Path $script:OutDir '*') -DestinationPath $zipPath -Force

    Write-Host ''
    if ($script:Errors.Count -eq 0) {
        if ($script:ReuseMode) { Write-Host 'Detailed formal player reports regenerated in the existing first-team export folder.' -ForegroundColor Green } else { Write-Host 'Managed first-team + opponent match-stat export v1.5.0 finished.' -ForegroundColor Green }
        Write-Host 'Inspect managed-club.json, first-team-scope.json, validation.json and player-report-identity-audit.json.' -ForegroundColor Cyan
    }
    else {
        Write-Host 'Export bundle created with warnings. See export-warnings.txt.' -ForegroundColor Yellow
    }
    Write-Host ('Output folder: ' + $script:OutDir)
    Write-Host ('ZIP file: ' + $zipPath) -ForegroundColor Yellow
    try { Start-Process explorer.exe -ArgumentList ('"' + $script:OutDir + '"') } catch { }
}
finally {
    if (Test-Path -LiteralPath $script:TempDir) {
        Remove-Item -LiteralPath $script:TempDir -Recurse -Force -ErrorAction SilentlyContinue
    }
}

