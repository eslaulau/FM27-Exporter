# FM27 managed first-team + opponent match-stat exporter v1.5.0 - Windows PowerShell 5.1 compatible
# Read-only. Requires Python 3.12+ and fmsave==0.12.4 (pinned; no auto-upgrade).
# Keeps managed first-team player data and BOTH teams' match statistics for direct first-team fixtures.
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

function Invoke-TeamMatchStatsSchemaFallback {
    param([Parameter(Mandatory = $true)][string]$OutputPath)

    # Experimental compatibility path for FM27 27.0.1+2494687 only.
    # The match_stats_cfg section must still report schema 6. This borrows the
    # registered 27.0.0 schema-6 layout and then runs fmsave's own reader checks.
    # It is NOT an upstream-verified 27.0.1 layout; metadata is written beside the JSON.
    $helperPath = Join-Path $script:TempDir 'team_match_stats_schema_fallback.py'
    $compatPath = Join-Path $script:OutDir 'team-match-stats-compatibility.json'

    $pythonHelper = @'
import collections
import datetime
import json
import pathlib
import sys
import traceback
import warnings

EXPECTED_BUILD = "27.0.1+2494687"
REFERENCE_BUILD = "27.0.0+2486695"
EXPECTED_SCHEMA = 6
FIRST_TEAM_ID = None


def key_of(row):
    return (
        row.get("competition_id"),
        row.get("home_team_id"),
        row.get("away_team_id"),
        str(row.get("date")),
    )


def main():
    if len(sys.argv) != 5:
        raise RuntimeError("internal helper arguments are incomplete")

    save_path = pathlib.Path(sys.argv[1])
    output_path = pathlib.Path(sys.argv[2])
    fixtures_path = pathlib.Path(sys.argv[3])
    compatibility_path = pathlib.Path(sys.argv[4])

    import fmsave
    import fmsave._save as save_module
    from fmsave._layouts import MatchReportLayout, find_layout
    from fmsave.readers._common import MATCH_REPORTS_SECTION

    original_resolver = save_module.find_match_report_layout

    def schema_matched_resolver(game, schema, build, *, known_build):
        if (
            game == "FM27"
            and build == EXPECTED_BUILD
            and schema == EXPECTED_SCHEMA
            and not known_build
        ):
            # Resolve only the exact schema-6 report layout registered for 27.0.0.
            # The check in this helper is intentionally narrower than a generic override.
            match = find_layout(
                MatchReportLayout,
                MATCH_REPORTS_SECTION,
                EXPECTED_SCHEMA,
                REFERENCE_BUILD,
            )
            if not match.exact:
                raise RuntimeError("reference match-report layout was not an exact registered match")
            return match.layout
        return original_resolver(game, schema, build, known_build=known_build)

    save_module.find_match_report_layout = schema_matched_resolver

    with fmsave.open(str(save_path)) as career:
        info = career.info
        observed_schema = info.section_schemas.get(MATCH_REPORTS_SECTION)
        if info.game != "FM27":
            raise RuntimeError("compatibility path is only for FM27 saves")
        if info.build != EXPECTED_BUILD:
            raise RuntimeError(
                "compatibility path is restricted to build %s; save is %s" % (EXPECTED_BUILD, info.build)
            )
        if observed_schema != EXPECTED_SCHEMA:
            raise RuntimeError(
                "match_stats_cfg schema mismatch: expected %s, found %s" % (EXPECTED_SCHEMA, observed_schema)
            )

        managed = career.managed_clubs()
        if len(managed) != 1:
            raise RuntimeError("expected exactly one managed club entry; refusing to guess")
        managed_uid = managed[0].club_uid
        managed_club_name = managed[0].club_name
        managed_clubs = [club for club in career.clubs() if club.uid == managed_uid]
        if len(managed_clubs) != 1:
            raise RuntimeError("managed club UID did not resolve to exactly one club")
        first_teams = [team for team in managed_clubs[0].teams if team.club_uid == managed_uid and team.slot == 0]
        if len(first_teams) != 1:
            raise RuntimeError("managed club does not have exactly one owned team at slot 0")
        FIRST_TEAM_ID = first_teams[0].team_id
        team_ids = {team.team_id for team in managed_clubs[0].teams}
        if FIRST_TEAM_ID not in team_ids:
            raise RuntimeError("resolved first-team ID is not present in managed club team list")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            table = career.team_match_stats()
            all_rows = table.to_dicts(json_ready=True)

        # Select only matches involving the explicitly configured managed first team.
        # Keep both home and away rows after pair integrity checks.
        relevant_rows = [
            row for row in all_rows
            if row.get("home_team_id") == FIRST_TEAM_ID or row.get("away_team_id") == FIRST_TEAM_ID
        ]
        if not relevant_rows:
            raise RuntimeError(
                "the schema-matched reader returned zero first-team rows for team_id=%s; refusing to create an empty success file"
                % FIRST_TEAM_ID
            )

        grouped = collections.defaultdict(list)
        for row in relevant_rows:
            grouped[key_of(row)].append(row)

        malformed = []
        for key, pair in grouped.items():
            homes = [row for row in pair if row.get("is_home") is True]
            aways = [row for row in pair if row.get("is_home") is False]
            if len(pair) != 2 or len(homes) != 1 or len(aways) != 1:
                malformed.append({"match": key, "rows": len(pair)})
                continue
            if homes[0].get("team_id") != key[1] or aways[0].get("team_id") != key[2]:
                malformed.append({"match": key, "reason": "home/away team IDs disagree"})
        if malformed:
            raise RuntimeError(
                "structural match-pair checks failed for %s report(s); refusing to export" % len(malformed)
            )

        fixture_count = None
        joined_count = None
        unmatched_report_matches = None
        if fixtures_path.is_file():
            fixtures = json.loads(fixtures_path.read_text(encoding="utf-8-sig"))
            first_team_fixtures = [
                row for row in fixtures
                if FIRST_TEAM_ID in (row.get("home_team_id"), row.get("away_team_id"))
            ]
            fixture_keys = {key_of(row) for row in first_team_fixtures}
            report_keys = set(grouped)
            fixture_count = len(first_team_fixtures)
            joined_count = len(report_keys & fixture_keys)
            unmatched_report_matches = len(report_keys - fixture_keys)
            if report_keys and joined_count == 0:
                raise RuntimeError(
                    "none of the first-team report keys join to first-team fixtures.json; refusing to export potentially misaligned rows"
                )

        output_path.write_text(
            json.dumps(relevant_rows, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        metadata = {
            "status": "EXPERIMENTAL_SCHEMA_MATCH_FALLBACK",
            "save_game": info.game,
            "save_build": info.build,
            "match_stats_cfg_schema": observed_schema,
            "layout_borrowed_from": REFERENCE_BUILD,
            "fmsave_version": getattr(fmsave, "__version__", "unknown"),
            "scope": "managed first-team fixtures; both home and away team rows per match",
            "managed_club_uid": managed_uid,
            "managed_club_name": managed_club_name,
            "managed_first_team_id": FIRST_TEAM_ID,
            "raw_team_rows": len(all_rows),
            "first_team_match_pair_rows_checked": len(relevant_rows),
            "first_team_and_opponent_rows_written": len(relevant_rows),
            "opponent_side_rows_retained": sum(1 for row in relevant_rows if row.get("team_id") != FIRST_TEAM_ID),
            "first_team_matches_with_reports": len(grouped),
            "first_team_fixtures_in_scope": fixture_count,
            "report_matches_joined_to_first_team_fixtures": joined_count,
            "report_matches_without_fixture_join": unmatched_report_matches,
            "reader_warnings": [str(item.message) for item in caught],
            "limitations": [
                "The upstream fmsave package does not register the team-match-stats layout for this exact build.",
                "This fallback borrows the FM27 27.0.0 layout only because match_stats_cfg schema is exactly 6.",
                "Structural pair and fixture-join checks passed, but that does not prove every decoded field matches the in-game screen.",
                "Treat the output as experimental until compared with at least one in-game match report."
            ],
        }
        compatibility_path.write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        print(
            "EXPERIMENTAL TWO-SIDED MATCH STATS: %s matches, %s home+away rows, %s rows joined to first-team fixtures."
            % (len(grouped), len(relevant_rows), joined_count)
        )
        print("Compatibility notes: %s" % compatibility_path)
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise SystemExit(2)
'@

    Set-Content -LiteralPath $helperPath -Value $pythonHelper -Encoding UTF8

    $helperArgs = @()
    if ($script:PythonPrefix.Count -gt 0) { $helperArgs += $script:PythonPrefix }
    $helperArgs += @(
        $helperPath,
        $script:SavePath,
        $OutputPath,
        (Join-Path $script:OutDir 'fixtures.json'),
        $compatPath
    )

    return Invoke-NativeCapture -FilePath $script:PythonExe -Arguments $helperArgs -Label 'team_match_stats_schema_fallback'
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
    $cachePath = Join-Path $script:BundleRoot 'FM27_PlayerIdentityCache_Formal_v1.1.json'
    if (-not (Test-Path -LiteralPath $helperPath) -or -not (Test-Path -LiteralPath $cachePath)) {
        $script:Errors.Add('formal per-player match report recovery helper or identity cache missing')
        Write-Host 'WARNING: formal detailed-report helper/cache is missing; base first-team export will still be kept.' -ForegroundColor Yellow
        return
    }

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
        '--competition-id', '0'
    )
    $existingProbePath = Join-Path $script:OutDir 'player-report-probe.json'
    if ($script:ReuseMode -and (Test-Path -LiteralPath $existingProbePath -PathType Leaf)) {
        $helperArgs += '--reuse-probe'
        Write-Host 'Using cached player-report-probe.json; this run will repair identities without reopening 2.fm.' -ForegroundColor Green
    }

    Write-Host ''
    Write-Host 'Recovering player detailed match reports across all formal competitions (7, 637, 661, 662; excluding pre-season 131)...' -ForegroundColor Cyan
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
        $fallbackSucceeded = $false
        if (
            $TableName -eq 'team-match-stats' -and
            $result.StdErr -match 'team match stats have no supported layout for FM27 build 27\.0\.1\+2494687'
        ) {
            Write-Host 'Trying experimental same-schema team-match-stats compatibility path...' -ForegroundColor Yellow
            if (Test-Path -LiteralPath $outputPath) { Remove-Item -LiteralPath $outputPath -Force }
            $compatibilityPath = Join-Path $script:OutDir 'team-match-stats-compatibility.json'
            if (Test-Path -LiteralPath $compatibilityPath) { Remove-Item -LiteralPath $compatibilityPath -Force }
            $fallbackResult = Invoke-TeamMatchStatsSchemaFallback -OutputPath $outputPath
            Add-Diagnostic -Title 'team-match-stats schema fallback stdout' -Text $fallbackResult.StdOut
            Add-Diagnostic -Title 'team-match-stats schema fallback stderr' -Text $fallbackResult.StdErr
            if (
                $fallbackResult.ExitCode -eq 0 -and
                (Test-Path -LiteralPath $outputPath) -and
                (Test-Path -LiteralPath (Join-Path $script:OutDir 'team-match-stats-compatibility.json'))
            ) {
                $fallbackSucceeded = $true
                Write-Host 'Experimental team-match-stats export succeeded. Verify team-match-stats-compatibility.json against an in-game match report.' -ForegroundColor Yellow
            }
            else {
                $script:Errors.Add('team-match-stats: standard export unsupported and experimental schema fallback failed; see native-diagnostics.txt')
                Write-Host 'WARNING: experimental team-match-stats fallback failed. See native-diagnostics.txt.' -ForegroundColor Yellow
            }
        }
        if (-not $fallbackSucceeded) {
            if ($TableName -ne 'team-match-stats' -or $result.StdErr -notmatch 'team match stats have no supported layout for FM27 build 27\.0\.1\+2494687') {
                $script:Errors.Add($TableName + ': export failed; exit code ' + $result.ExitCode)
                Write-Host ('WARNING: ' + $TableName + ' export failed. Continuing.') -ForegroundColor Yellow
            }
        }
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
Write-Host 'FM27 27.0.1 team-match-stats may use a clearly labelled experimental schema fallback.' -ForegroundColor Yellow
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
    $script:FmsavePinnedVersion = '0.12.4'
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
        'Parser version is pinned to fmsave==0.12.4; automatic upgrades are disabled.',
        'Save path defaults to the configured FM27 2.fm; override with -SavePath when needed.',
        'Optional -ReuseExportDir reuses an existing first-team export folder and regenerates only the detailed formal player reports.',
        '',
        'Files include managed first-team fixtures, BOTH teams' match statistics for those fixtures, and first-team player profiles/attributes,',
        'first-team player-season-stats, first-team player-match-stats and first-team selections,',
        'managed-club.json, save-info, parser validation and first-team-scope.json.',
        'Per-player detailed match-report outputs: player-report-probe.json, player-match-report-identified.csv/json, player-match-report-unresolved.csv, player-match-report-formal-all.csv and player-match-report-formal-summary.json.',
        'These detailed reports cover formal competitions 7, 637, 661 and 662; pre-season/non-competitive competition 131 is excluded.',
        'The match-report helper performs a targeted read-only pass over match_stats_cfg with fmsave==0.12.4.',
        'Identities use a persisted four-byte signature cache seeded from the validated full-season league report; cross-competition transfer limitations are recorded in the identity audit.',
        'Unmapped player rows remain anonymous and are written to player-match-report-unresolved.csv.',
        'Verified raw player-record offsets decode goals, assists, substitute entry/exit clocks, passes attempted and passes completed even when rolling named history is missing.',
        'fmsave 0.12.4 adds PlayerMatchStats.entered_at_minute to named match history and PlayerSeasonStats.minutes_since_last_goal to overall club season stats.',
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
        'For FM27 27.0.1+2494687 with match_stats_cfg schema 6, fmsave 0.12.4 borrows the registered 27.0.0 schema-6 layout because 27.0.1 is not upstream-registered.',
        'The generated team-match-stats-compatibility.json records the reader status, source layout, formal-fixture coverage, team totals and raw-field cross-checks for this save only.',
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

