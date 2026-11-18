# FM27 FIRST-TEAM ONLY exporter + formal-competition player match reports v1.4.5 - Windows PowerShell 5.1 compatible
# Read-only. Requires Python 3.12+ and fmsave==0.12.4 (pinned; no auto-upgrade).
# Keeps only managed first-team data: squad profiles/attributes, first-team stats, positions, tactics and fixtures.
# Opponent identity/date/venue/score stay as match context; opponent profiles and performance rows are excluded.
# Actual selected role and live PI values remain unresolved unless independently decoded.

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
$script:TeamId = 539
$script:ClubUid = 680

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
FIRST_TEAM_ID = 539


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
        if not managed:
            raise RuntimeError("the save has no managed club entry")
        managed_uid = managed[0].club_uid
        team_ids = {
            team.team_id
            for club in career.clubs()
            if club.uid == managed_uid
            for team in club.teams
        }
        if FIRST_TEAM_ID not in team_ids:
            raise RuntimeError(
                "configured first-team ID %s is not one of the managed club's team IDs: %s"
                % (FIRST_TEAM_ID, sorted(team_ids))
            )

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            table = career.team_match_stats()
            all_rows = table.to_dicts(json_ready=True)

        # Select only matches involving the explicitly configured managed first team.
        # Pair rows remain in memory for integrity checks; only our own side is written.
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

        own_rows = [row for row in relevant_rows if row.get("team_id") == FIRST_TEAM_ID]
        if len(own_rows) != len(grouped):
            raise RuntimeError(
                "first-team report row count does not match unique first-team matches (%s != %s)"
                % (len(own_rows), len(grouped))
            )
        output_path.write_text(
            json.dumps(own_rows, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        metadata = {
            "status": "EXPERIMENTAL_SCHEMA_MATCH_FALLBACK",
            "save_game": info.game,
            "save_build": info.build,
            "match_stats_cfg_schema": observed_schema,
            "layout_borrowed_from": REFERENCE_BUILD,
            "fmsave_version": getattr(fmsave, "__version__", "unknown"),
            "scope": "managed first team only; one own-side team row per match",
            "managed_club_uid": managed_uid,
            "managed_first_team_id": FIRST_TEAM_ID,
            "raw_team_rows": len(all_rows),
            "first_team_match_pair_rows_checked": len(relevant_rows),
            "first_team_own_side_rows_written": len(own_rows),
            "opponent_side_rows_excluded": len(relevant_rows) - len(own_rows),
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
            "EXPERIMENTAL FIRST-TEAM MATCH STATS: %s matches, %s own-team rows, %s rows joined to first-team fixtures."
            % (len(grouped), len(own_rows), joined_count)
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

    $filterPath = Join-Path $script:BundleRoot 'FM27_FirstTeam_Filter_v1.2.2.py'
    if (-not (Test-Path -LiteralPath $filterPath)) {
        throw ('Required companion file missing: ' + $filterPath + ' (extract the complete v1.2.2 bundle).')
    }
    $filterArgs = @()
    if ($script:PythonPrefix.Count -gt 0) { $filterArgs += $script:PythonPrefix }
    $filterArgs += @($filterPath, $script:OutDir, '--team-id', [string]$script:TeamId, '--club-uid', [string]$script:ClubUid)
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

function Invoke-PlayerPositionHistoryAudit {
    # Builds an identity-preserving position-history layer from exported named player records.
    # It deliberately does not assign identities to anonymous detailed-report rows.
    param()

    $helperPath = Join-Path $script:TempDir 'FM27_PositionHistory_Audit.py'
    $catalogPath = Join-Path $script:BundleRoot 'catalog.json'
    $permissionPath = Join-Path $script:BundleRoot 'FM27_Role_PI_Permissions.csv'
    if (-not (Test-Path -LiteralPath $catalogPath)) {
        throw ('Required companion file missing: ' + $catalogPath + ' (extract the complete v1.1 bundle).')
    }
    if (-not (Test-Path -LiteralPath $permissionPath)) {
        throw ('Required companion file missing: ' + $permissionPath + ' (extract the complete v1.1 bundle).')
    }
    $pythonHelper = @'
#!/usr/bin/env python3
"""Build identity-preserving FM27 player position history, native position-role candidates and PI permission audits.

Reads existing fmsave exports only. It does not alter the save, guess anonymous match-report
row identities, or translate unverified role codes. Position masks are retained verbatim.
"""
from __future__ import annotations
import argparse, csv, json, sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

TEAM_ID_DEFAULT = 539
CLUB_UID_DEFAULT = 680
TAC_NAME_DEFAULT = "ENGINE HARVESTER A3.2 - CLEAN PI IMPORT"


POSITION_LABELS_ZH = {
    "GK": "门将", "DR": "右后卫", "DL": "左后卫", "DC": "中后卫",
    "DCR": "右中卫", "DCL": "左中卫", "WBR": "右翼卫", "WBL": "左翼卫",
    "DMC": "防守中场", "DMR": "右后腰", "DML": "左后腰", "MR": "右边前卫",
    "ML": "左边前卫", "MC": "中前卫", "MCR": "右中前卫", "MCL": "左中前卫",
    "AMR": "右边锋", "AML": "左边锋", "AMC": "前腰", "AMCR": "右前腰",
    "AMCL": "左前腰", "ST": "中锋", "STR": "右侧前锋", "STL": "左侧前锋",
}
PHASE_LABELS = {0: "持球阶段 IP", 1: "无球阶段 OOP"}
DUTY_CODES = [0, 2097152, 4194304, 8388608, 33554432, 67108864, 17179869184]

def read_json(path: Path, required: bool = True) -> Any:
    if not path.exists():
        if required:
            raise FileNotFoundError(f"Required export file missing: {path.name}")
        return None
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)

def as_int(v: Any) -> int | None:
    try:
        if v is None or v == "": return None
        return int(v)
    except (TypeError, ValueError):
        return None

def csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def clean_text(v: Any) -> str:
    return "" if v is None else str(v)

def save_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in rows:
            cooked = {}
            for key in fields:
                value = row.get(key)
                if isinstance(value, (dict, list)):
                    value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
                cooked[key] = value
            w.writerow(cooked)

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("export_dir", type=Path)
    ap.add_argument("--team-id", type=int, default=TEAM_ID_DEFAULT)
    ap.add_argument("--club-uid", type=int, default=CLUB_UID_DEFAULT)
    ap.add_argument("--tactic-name", default=TAC_NAME_DEFAULT)
    ap.add_argument("--catalog", type=Path, default=None, help="Native catalog.json (defaults beside this script).")
    ap.add_argument("--role-permissions", type=Path, default=None, help="Workbook-derived role PI permission CSV (defaults beside this script).")
    args = ap.parse_args()
    root = args.export_dir.expanduser().resolve()
    if not root.is_dir(): raise NotADirectoryError(root)

    save_info = read_json(root / "save-info.json", required=False) or {}
    player_matches = read_json(root / "player-match-stats.json")
    fixtures = read_json(root / "fixtures.json")
    selections = read_json(root / "selections.json")
    tactics = read_json(root / "tactics.json")
    season_rows = csv_rows(root / "player-season-stats.csv")

    # Select only fixtures in which the requested first team actually played. This avoids
    # assigning a player's national-team, former-club, B-team or reserve-team history to the XI.
    team_fixtures: list[dict[str, Any]] = []
    fixture_index: dict[tuple[int, str, int], list[dict[str, Any]]] = defaultdict(list)
    for f in fixtures:
        home_id, away_id = as_int(f.get("home_team_id")), as_int(f.get("away_team_id"))
        if args.team_id not in (home_id, away_id) or not f.get("played", False):
            continue
        own_home = home_id == args.team_id
        opp_id = away_id if own_home else home_id
        comp, date = as_int(f.get("competition_id")), clean_text(f.get("date"))
        if comp is None or not date or opp_id is None:
            continue
        record = {
            "competition_id": comp, "date": date, "team_id": args.team_id,
            "opponent_team_id": opp_id, "is_home": own_home,
            "opponent_club_uid": as_int(f.get("away_club_uid" if own_home else "home_club_uid")),
            "opponent_club_name": clean_text(f.get("away_club_name" if own_home else "home_club_name")),
            "opponent_club_short_name": clean_text(f.get("away_club_short_name" if own_home else "home_club_short_name")),
            "home_goals": as_int(f.get("home_goals")), "away_goals": as_int(f.get("away_goals")),
            "stage_id": as_int(f.get("stage_id")), "round": f.get("round"),
            "competition_name": clean_text(f.get("competition_name")),
            "kick_off_time": clean_text(f.get("kick_off_time")),
        }
        gf = record["home_goals"] if own_home else record["away_goals"]
        ga = record["away_goals"] if own_home else record["home_goals"]
        record["team_goals"] = gf
        record["opponent_goals"] = ga
        record["result"] = ("W" if gf > ga else "D" if gf == ga else "L") if gf is not None and ga is not None else ""
        team_fixtures.append(record)
        fixture_index[(comp, date, opp_id)].append(record)

    # Current selection and current tactic are separate snapshots; only non-substitute selections
    # are connected to pitch slots. Bench order numbers must never be mistaken for tactical slots.
    selection_by_uid: dict[int, dict[str, Any]] = {}
    starter_by_slot: dict[int, dict[str, Any]] = {}
    for s in selections:
        if as_int(s.get("team_id")) != args.team_id: continue
        if as_int(s.get("club_uid")) not in (None, args.club_uid): continue
        uid = as_int(s.get("player_uid"))
        if uid is None: continue
        sub = bool(s.get("substitute", False))
        item = {
            "player_uid": uid, "player_name": clean_text(s.get("player_name")),
            "selection_type": "substitute" if sub else "starter",
            "selection_slot": as_int(s.get("slot")),
            "tactic_slot": None if sub else as_int(s.get("slot")),
        }
        selection_by_uid[uid] = item
        if not sub and item["tactic_slot"] is not None:
            starter_by_slot[item["tactic_slot"]] = item

    tactic = next((t for t in tactics if as_int(t.get("team_id")) == args.team_id
                   and as_int(t.get("club_uid")) in (None, args.club_uid)
                   and (not args.tactic_name or clean_text(t.get("name")) == args.tactic_name)), None)
    if tactic is None:
        # A tactic-name mismatch is not fatal; use the first tactic for the exact team.
        tactic = next((t for t in tactics if as_int(t.get("team_id")) == args.team_id), None)
    tactic_slots = {as_int(x.get("number")): x for x in (tactic or {}).get("slots", [])}

    # Exact full tactic-position masks are mapped through the user's native FM27 catalog.
    # Role bits are NOT decoded as role IDs: they are retained as evidence only.
    script_dir = Path(__file__).resolve().parent
    catalog_path = (args.catalog or (script_dir / "catalog.json")).expanduser().resolve()
    permission_path = (args.role_permissions or (script_dir / "FM27_Role_PI_Permissions.csv")).expanduser().resolve()
    catalog = read_json(catalog_path)
    permission_rows = csv_rows(permission_path)
    position_by_mask = {
        as_int(x.get("mask")): x for x in catalog.get("positions", [])
        if as_int(x.get("mask")) is not None
    }
    role_by_id = {clean_text(x.get("id")): x for x in catalog.get("roles", [])}
    eligibility = catalog.get("role_eligibility", {})
    permission_by_key: dict[tuple[str, str, str, int], dict[str, str]] = {}
    for perm in permission_rows:
        phase_label = clean_text(perm.get("阶段"))
        pos_id = clean_text(perm.get("位置槽"))
        role_id = clean_text(perm.get("角色内部ID"))
        duty_code = as_int(perm.get("原生 duty 编码"))
        if phase_label and pos_id and role_id and duty_code is not None:
            permission_by_key[(phase_label, pos_id, role_id, duty_code)] = perm
    permission_source_keys = len(permission_by_key)
    if permission_source_keys != len(permission_rows):
        raise ValueError(
            f"Role permission CSV contains {len(permission_rows)} rows but only "
            f"{permission_source_keys} unique phase/position/role/duty keys."
        )

    # Map one player's match history to one played fixture only by the three independent fields
    # stored in both records: competition, date and opponent team ID.
    joined: list[dict[str, Any]] = []
    unmatched_history: list[dict[str, Any]] = []
    for p in player_matches:
        uid, comp, opp = as_int(p.get("player_uid")), as_int(p.get("competition_id")), as_int(p.get("opponent_team_id"))
        date = clean_text(p.get("date"))
        if None in (uid, comp, opp) or not date: continue
        matches = fixture_index.get((comp, date, opp), [])
        if len(matches) != 1:
            if matches:
                unmatched_history.append({"player_uid": uid, "player_name": p.get("player_name"),
                    "date": date, "competition_id": comp, "opponent_team_id": opp,
                    "reason": "ambiguous_fixture_join", "matching_fixtures": len(matches)})
            continue
        f = matches[0]
        selection = selection_by_uid.get(uid, {})
        slot_num = selection.get("tactic_slot")
        slot = tactic_slots.get(slot_num, {}) if slot_num is not None else {}
        slot_unknown = slot.get("unknown") or {}
        ip_slot_position = position_by_mask.get(as_int(slot.get("in_possession_mask")))
        oop_slot_position = position_by_mask.get(as_int(slot.get("out_of_possession_mask")))
        ip_slot_id = clean_text(ip_slot_position.get("id")) if ip_slot_position else ""
        oop_slot_id = clean_text(oop_slot_position.get("id")) if oop_slot_position else ""
        code = as_int(p.get("position_code"))
        raw_position = clean_text(p.get("position"))
        # fmsave currently names only the goalkeeper bit. Preserve every other mask as raw data.
        official_position = "goalkeeper" if code == 1 or raw_position == "goalkeeper" else ""
        joined.append({
            "player_uid": uid,
            "player_name": clean_text(p.get("player_name")) or clean_text(selection.get("player_name")),
            "date": date, "competition_id": comp,
            "competition_name": f.get("competition_name"), "stage_id": f.get("stage_id"),
            "round": f.get("round"), "team_id": args.team_id,
            "is_home": f.get("is_home"), "opponent_team_id": opp,
            "opponent_club_uid": f.get("opponent_club_uid"),
            "opponent_club_name": f.get("opponent_club_name"),
            "opponent_club_short_name": f.get("opponent_club_short_name"),
            "team_goals": f.get("team_goals"), "opponent_goals": f.get("opponent_goals"),
            "match_result": f.get("result"),
            "has_stats": bool(p.get("has_stats")),
            "position_code": code,
            "position_mask_hex": (f"0x{code:04X}" if code is not None else ""),
            "position_label_official": official_position,
            "position_label_raw": raw_position,
            "role_code_raw": as_int((p.get("unknown") or {}).get("role_code")),
            "minutes": as_int(p.get("minutes")), "left_at_minute": as_int(p.get("left_at_minute")),
            "rating": p.get("rating"), "goals": p.get("goals"), "assists": p.get("assists"),
            "passes_attempted": p.get("passes_attempted"), "passes_completed": p.get("passes_completed"),
            "stats_in_range": p.get("stats_in_range"),
            "selection_type": selection.get("selection_type", "not_in_current_selection"),
            "current_tactic_slot": slot_num if slot_num is not None else "",
            "current_ip_position": ip_slot_id or ";".join(slot.get("in_possession_positions") or []),
            "current_ip_position_zh": POSITION_LABELS_ZH.get(ip_slot_id, ""),
            "current_ip_position_fmsave_label": ";".join(slot.get("in_possession_positions") or []),
            "current_oop_position": oop_slot_id or ";".join(slot.get("out_of_possession_positions") or []),
            "current_oop_position_zh": POSITION_LABELS_ZH.get(oop_slot_id, ""),
            "current_oop_position_fmsave_label": ";".join(slot.get("out_of_possession_positions") or []),
        })

    # Derive provisional raw-mask -> current tactic position evidence separately for
    # in-possession and out-of-possession positions. They are not assumed to be the same.
    # Only current starters with >=3 records and a stable mask (>=80%) contribute evidence.
    player_history: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in joined:
        if row["has_stats"] and row["position_code"] is not None:
            player_history[row["player_uid"]].append(row)
    evidence: dict[int, dict[str, Any]] = defaultdict(lambda: {
        "ip_positions": set(), "oop_positions": set(), "players": set(), "records": []
    })
    player_stability: dict[int, dict[str, Any]] = {}
    for uid, hist in player_history.items():
        sel = selection_by_uid.get(uid, {})
        slot_num = sel.get("tactic_slot")
        slot = tactic_slots.get(slot_num, {}) if slot_num is not None else {}
        ip_mask_position = position_by_mask.get(as_int(slot.get("in_possession_mask")))
        oop_mask_position = position_by_mask.get(as_int(slot.get("out_of_possession_mask")))
        ip = clean_text(ip_mask_position.get("id")) if ip_mask_position else ";".join(slot.get("in_possession_positions") or [])
        oop = clean_text(oop_mask_position.get("id")) if oop_mask_position else ";".join(slot.get("out_of_possession_positions") or [])
        codes = Counter(x["position_code"] for x in hist)
        dominant_code, dominant_n = codes.most_common(1)[0]
        ratio = dominant_n / len(hist)
        ip_valid = bool(ip) and ip != "unknown"
        oop_valid = bool(oop) and oop != "unknown"
        stable = (sel.get("selection_type") == "starter" and (ip_valid or oop_valid)
                  and len(hist) >= 3 and ratio >= 0.80)
        player_stability[uid] = {
            "position_code_counts": dict(codes), "dominant_code": dominant_code,
            "dominant_share": round(ratio, 4), "history_apps": len(hist),
            "stable_for_current_tactic_evidence": stable,
            "current_ip_position": ip, "current_oop_position": oop,
            "current_ip_position_zh": POSITION_LABELS_ZH.get(ip, ""),
            "current_oop_position_zh": POSITION_LABELS_ZH.get(oop, ""),
            "player_specific_alignment_status": (
                "provisional_unique_player_alignment" if stable
                else "insufficient_or_unstable_player_history"
            ),
        }
        if stable:
            e = evidence[dominant_code]
            if ip_valid: e["ip_positions"].add(ip)
            if oop_valid: e["oop_positions"].add(oop)
            e["players"].add(uid)
            e["records"].append(dominant_n)

    mask_map: dict[int, dict[str, Any]] = {}
    evidence_rows: list[dict[str, Any]] = []
    for code in sorted(set([x["position_code"] for x in joined if x["position_code"] is not None])):
        e = evidence.get(code, {"ip_positions": set(), "oop_positions": set(), "players": set(), "records": []})
        ip_positions = sorted(e["ip_positions"])
        oop_positions = sorted(e["oop_positions"])
        ip_mapped = ip_positions[0] if len(ip_positions) == 1 and len(e["players"]) >= 1 else ""
        oop_mapped = oop_positions[0] if len(oop_positions) == 1 and len(e["players"]) >= 1 else ""
        ip_status = ("provisional_unique_ip_alignment" if ip_mapped else
                     "ambiguous_ip_alignment" if ip_positions else "no_stable_starter_evidence")
        oop_status = ("provisional_unique_oop_alignment" if oop_mapped else
                      "ambiguous_oop_alignment" if oop_positions else "no_stable_starter_evidence")
        mask_map[code] = {
            "ip_position": ip_mapped, "ip_status": ip_status,
            "oop_position": oop_mapped, "oop_status": oop_status,
        }
        player_names = sorted({x["player_name"] for x in joined if x["player_uid"] in e["players"]})
        evidence_rows.append({
            "position_code": code, "position_mask_hex": f"0x{code:04X}",
            "inferred_current_ip_position": ip_mapped,
            "ip_evidence_status": ip_status,
            "inferred_current_oop_position": oop_mapped,
            "oop_evidence_status": oop_status,
            "supporting_starter_count": len(e["players"]),
            "supporting_starters": ";".join(player_names),
            "supporting_record_count": sum(e["records"]),
            "warning": "Provisional alignment to current tactic only; not an official FM position-code dictionary.",
        })

    # Decorate each row without replacing or rewriting its raw code. In-possession and
    # out-of-possession comparisons remain separate because FM27 can assign different shapes.
    for row in joined:
        code = row["position_code"]
        player_ref = player_stability.get(row["player_uid"], {})
        if (player_ref.get("stable_for_current_tactic_evidence")
                and code == player_ref.get("dominant_code")):
            m = {
                "ip_position": player_ref.get("current_ip_position", ""),
                "ip_status": "provisional_unique_player_alignment",
                "oop_position": player_ref.get("current_oop_position", ""),
                "oop_status": "provisional_unique_player_alignment",
            }
        elif player_ref.get("stable_for_current_tactic_evidence"):
            m = {
                "ip_position": "", "ip_status": "raw_mask_differs_from_player_dominant_code",
                "oop_position": "", "oop_status": "raw_mask_differs_from_player_dominant_code",
            }
        else:
            m = mask_map.get(code, {}) if code is not None else {}
        row["inferred_current_ip_position"] = m.get("ip_position", "")
        row["ip_position_inference_status"] = m.get("ip_status", "no_position_code")
        row["inferred_current_oop_position"] = m.get("oop_position", "")
        row["oop_position_inference_status"] = m.get("oop_status", "no_position_code")
        row["current_ip_comparison"] = (
            "same" if row["inferred_current_ip_position"] and row["inferred_current_ip_position"] == row["current_ip_position"]
            else "different" if row["inferred_current_ip_position"] and row["current_ip_position"]
            else "not_comparable"
        )
        row["current_oop_comparison"] = (
            "same" if row["inferred_current_oop_position"] and row["inferred_current_oop_position"] == row["current_oop_position"]
            else "different" if row["inferred_current_oop_position"] and row["current_oop_position"]
            else "not_comparable"
        )

    # Per-player history summary with exact raw masks/role codes and current tactic reference.
    name_by_uid: dict[int, str] = {}
    for x in season_rows:
        if as_int(x.get("team_id")) == args.team_id and x.get("kind") == "league":
            u = as_int(x.get("player_uid"))
            if u is not None: name_by_uid[u] = clean_text(x.get("player_name"))
    for x in selections:
        if as_int(x.get("team_id")) == args.team_id:
            u = as_int(x.get("player_uid"))
            if u is not None and x.get("player_name"): name_by_uid[u] = clean_text(x.get("player_name"))

    player_summary: list[dict[str, Any]] = []
    for uid in sorted(set(list(player_history) + list(selection_by_uid))):
        hist = player_history.get(uid, [])
        sel = selection_by_uid.get(uid, {})
        slot_num = sel.get("tactic_slot")
        slot = tactic_slots.get(slot_num, {}) if slot_num is not None else {}
        ip_position = position_by_mask.get(as_int(slot.get("in_possession_mask")))
        oop_position = position_by_mask.get(as_int(slot.get("out_of_possession_mask")))
        ip_id = clean_text(ip_position.get("id")) if ip_position else ";".join(slot.get("in_possession_positions") or [])
        oop_id = clean_text(oop_position.get("id")) if oop_position else ";".join(slot.get("out_of_possession_positions") or [])
        counts = Counter(x["position_code"] for x in hist if x["position_code"] is not None)
        roles = Counter(x["role_code_raw"] for x in hist if x["role_code_raw"] is not None)
        summary = player_stability.get(uid, {})
        player_summary.append({
            "player_uid": uid, "player_name": name_by_uid.get(uid) or sel.get("player_name") or next((x["player_name"] for x in hist if x["player_name"]), ""),
            "selection_type": sel.get("selection_type", "not_in_current_selection"),
            "current_tactic_slot": slot_num if slot_num is not None else "",
            "current_ip_position": ip_id,
            "current_ip_position_zh": POSITION_LABELS_ZH.get(ip_id, ""),
            "current_oop_position": oop_id,
            "current_oop_position_zh": POSITION_LABELS_ZH.get(oop_id, ""),
            "named_match_records": len([x for x in joined if x["player_uid"] == uid]),
            "matches_with_stats": len(hist),
            "position_code_counts": dict(counts),
            "dominant_position_code": summary.get("dominant_code", ""),
            "dominant_position_share": summary.get("dominant_share", ""),
            "role_code_counts": dict(roles),
            "stable_for_current_tactic_evidence": summary.get("stable_for_current_tactic_evidence", False),
            "player_specific_alignment_status": summary.get("player_specific_alignment_status", ""),
        })

    # Current squad mapping; preserve the slot setting bitfields as exported raw data so that
    # future role/instruction decoding has the original evidence, not only a display label.

    role_candidate_rows: list[dict[str, Any]] = []
    role_duty_permission_rows: list[dict[str, Any]] = []
    candidate_summary: list[dict[str, Any]] = []
    for uid, sel in selection_by_uid.items():
        slot_num = sel.get("tactic_slot")
        slot = tactic_slots.get(slot_num, {}) if slot_num is not None else {}
        if sel.get("selection_type") != "starter" or not slot:
            continue
        for phase_index, phase_name, mask_field, role_bits_field, trail_field in (
            (0, "IP", "in_possession_mask", "in_possession_role_bits", "in_possession_trail_bits"),
            (1, "OOP", "out_of_possession_mask", "out_of_possession_role_bits", "out_of_possession_trail_bits"),
        ):
            mask = as_int(slot.get(mask_field))
            position = position_by_mask.get(mask)
            position_id = clean_text(position.get("id")) if position else ""
            position_zh = POSITION_LABELS_ZH.get(position_id, "")
            raw_role_bits = as_int((slot.get("unknown") or {}).get(role_bits_field))
            raw_trail_bits = as_int((slot.get("unknown") or {}).get(trail_field))
            eligible_lists = eligibility.get(position_id, [[], []]) if position_id else [[], []]
            role_ids = eligible_lists[phase_index] if len(eligible_lists) > phase_index else []
            if not role_ids:
                candidate_summary.append({
                    "player_uid": uid, "player_name": sel["player_name"],
                    "tactic_slot": slot_num, "phase": phase_name,
                    "position_id": position_id, "position_zh": position_zh,
                    "candidate_role_count": 0, "candidate_roles_zh": "",
                    "selected_role_id": "", "selected_role_zh": "",
                    "selected_role_status": "no_catalog_position_or_eligibility",
                    "role_bits_raw": raw_role_bits, "trail_bits_raw": raw_trail_bits,
                })
            else:
                candidate_summary.append({
                    "player_uid": uid, "player_name": sel["player_name"],
                    "tactic_slot": slot_num, "phase": phase_name,
                    "position_id": position_id, "position_zh": position_zh,
                    "candidate_role_count": len(role_ids),
                    "candidate_roles_zh": "；".join(clean_text(role_by_id.get(r, {}).get("label")) or r for r in role_ids),
                    "selected_role_id": "", "selected_role_zh": "",
                    "selected_role_status": "unresolved_role_bits_are_not_role_ids",
                    "role_bits_raw": raw_role_bits, "trail_bits_raw": raw_trail_bits,
                })
            for role_id in role_ids:
                role_meta = role_by_id.get(role_id, {})
                candidate_label = clean_text(role_meta.get("label"))
                candidate = {
                    "player_uid": uid, "player_name": sel["player_name"],
                    "selection_type": sel["selection_type"], "tactic_slot": slot_num,
                    "phase": phase_name, "phase_catalog": phase_name,
                    "position_id": position_id, "position_zh": position_zh,
                    "position_mask_raw": mask,
                    "candidate_role_id": role_id, "candidate_role_zh": candidate_label,
                    "catalog_role_phase": role_meta.get("phase"),
                    "catalog_role_flags_raw": role_meta.get("flags"),
                    "catalog_role_defaults_raw": role_meta.get("defaults", []),
                    "role_bits_raw": raw_role_bits, "trail_bits_raw": raw_trail_bits,
                    "selected_role_id": "", "selected_role_zh": "",
                    "selected_role_status": "unresolved_role_bits_are_not_role_ids",
                    "warning": "候选角色来自原生位置菜单；不代表存档已选中该角色。",
                }
                role_candidate_rows.append(candidate)
                for duty in DUTY_CODES:
                    permission = permission_by_key.get((PHASE_LABELS[phase_index], position_id, role_id, duty), {})
                    role_duty_permission_rows.append({
                        "player_uid": uid, "player_name": sel["player_name"],
                        "tactic_slot": slot_num, "phase": phase_name,
                        "position_id": position_id, "position_zh": position_zh,
                        "candidate_role_id": role_id, "candidate_role_zh": candidate_label,
                        "duty_raw": duty,
                        "editable_context_1a080000": permission.get("可编辑项（上下文 1a080000）", ""),
                        "fixed_on": permission.get("固定开启", ""),
                        "fixed_off": permission.get("固定关闭", ""),
                        "editable_context_1b000000": permission.get("可编辑项（上下文 1b000000）", ""),
                        "context_status_differs": permission.get("状态差异", ""),
                        "unavailable_option_count": as_int(permission.get("不可用选项数")),
                        "permission_record_status": "found" if permission else "not_found_in_workbook_catalog",
                        "warning": "这是角色/职责组合的菜单权限，不是本存档当前个人指令取值。",
                    })

    slot_map_rows: list[dict[str, Any]] = []
    for uid, sel in selection_by_uid.items():
        slot_num = sel.get("tactic_slot")
        slot = tactic_slots.get(slot_num, {}) if slot_num is not None else {}
        ip_mask = as_int(slot.get("in_possession_mask"))
        oop_mask = as_int(slot.get("out_of_possession_mask"))
        ip_position = position_by_mask.get(ip_mask)
        oop_position = position_by_mask.get(oop_mask)
        ip_position_id = clean_text(ip_position.get("id")) if ip_position else ""
        oop_position_id = clean_text(oop_position.get("id")) if oop_position else ""
        ip_candidates = (eligibility.get(ip_position_id, [[], []])[0] if ip_position_id else [])
        oop_candidates = (eligibility.get(oop_position_id, [[], []])[1] if oop_position_id else [])
        unknown = slot.get("unknown") or {}
        slot_map_rows.append({
            "player_uid": uid, "player_name": sel["player_name"],
            "selection_type": sel["selection_type"], "selection_slot": sel["selection_slot"],
            "tactic_slot": slot_num if slot_num is not None else "",
            "in_possession_position_id": ip_position_id,
            "in_possession_position_zh": POSITION_LABELS_ZH.get(ip_position_id, ""),
            "in_possession_position_mask_raw": ip_mask,
            "in_possession_candidate_roles": [
                {"id": r, "label": clean_text(role_by_id.get(r, {}).get("label"))} for r in ip_candidates
            ],
            "in_possession_selected_role": "",
            "in_possession_selected_role_status": "unresolved_role_bits_are_not_role_ids" if slot else "no_pitch_slot",
            "out_of_possession_position_id": oop_position_id,
            "out_of_possession_position_zh": POSITION_LABELS_ZH.get(oop_position_id, ""),
            "out_of_possession_position_mask_raw": oop_mask,
            "out_of_possession_candidate_roles": [
                {"id": r, "label": clean_text(role_by_id.get(r, {}).get("label"))} for r in oop_candidates
            ],
            "out_of_possession_selected_role": "",
            "out_of_possession_selected_role_status": "unresolved_role_bits_are_not_role_ids" if slot else "no_pitch_slot",
            "in_possession_positions": slot.get("in_possession_positions", []),
            "out_of_possession_positions": slot.get("out_of_possession_positions", []),
            "in_possession_settings_raw": slot.get("in_possession_settings", []),
            "out_of_possession_settings_raw": slot.get("out_of_possession_settings", []),
            "in_possession_role_bits_raw": (slot.get("unknown") or {}).get("in_possession_role_bits"),
            "out_of_possession_role_bits_raw": (slot.get("unknown") or {}).get("out_of_possession_role_bits"),
            "in_possession_trail_bits_raw": (slot.get("unknown") or {}).get("in_possession_trail_bits"),
            "out_of_possession_trail_bits_raw": (slot.get("unknown") or {}).get("out_of_possession_trail_bits"),
        })
    slot_map_rows.sort(key=lambda x: (x["selection_type"] != "starter", x["selection_slot"] if x["selection_slot"] is not None else 999))

    # Unmatched named player histories within the exported date/competition scope are counted,
    # never silently assigned to this club. This lets the next audit detect parser gaps.
    fixture_keys = set(fixture_index)
    candidate_scope_rows = 0
    for p in player_matches:
        comp, date, opp = as_int(p.get("competition_id")), clean_text(p.get("date")), as_int(p.get("opponent_team_id"))
        if comp is not None and date and opp is not None and (comp, date, opp) in fixture_keys:
            candidate_scope_rows += 1

    coverage = {
        "audit_version": "1.1",
        "team_id": args.team_id, "club_uid": args.club_uid,
        "tactic_name": clean_text((tactic or {}).get("name")),
        "fmsave_version": clean_text(save_info.get("fmsave_version")),
        "game_build": clean_text(save_info.get("build")),
        "game_date": clean_text(save_info.get("game_date")),
        "played_first_team_fixtures": len(team_fixtures),
        "fixtures_with_named_player_history": len({(x["competition_id"], x["date"], x["opponent_team_id"]) for x in joined}),
        "fixtures_without_named_player_history": [],
        "candidate_player_history_rows_joined_to_first_team": candidate_scope_rows,
        "joined_player_history_rows": len(joined),
        "joined_rows_with_stats": sum(bool(x["has_stats"]) for x in joined),
        "joined_rows_with_position_code": sum(x["position_code"] is not None for x in joined),
        "joined_rows_with_role_code": sum(x["role_code_raw"] is not None for x in joined),
        "unique_players_with_history": len({x["player_uid"] for x in joined}),
        "current_selection_players": len(selection_by_uid),
        "current_starters": sum(1 for x in selection_by_uid.values() if x["selection_type"] == "starter"),
        "ambiguous_fixture_joins": len(unmatched_history),
        "provisional_ip_position_mask_mappings": sum(1 for v in mask_map.values() if v["ip_position"]),
        "provisional_oop_position_mask_mappings": sum(1 for v in mask_map.values() if v["oop_position"]),
        "position_mask_mapping_evidence": evidence_rows,
        "native_catalog": {
            "path": str(catalog_path),
            "schema_version": catalog.get("schema_version"),
            "position_mask_count": len(position_by_mask),
            "role_count": len(role_by_id),
            "role_permission_csv": str(permission_path),
            "role_permission_record_count": permission_source_keys,
            "current_starter_phase_position_rows": len(candidate_summary),
            "current_role_candidate_rows": len(role_candidate_rows),
            "current_role_duty_permission_rows": len(role_duty_permission_rows),
            "candidate_roles_are_not_selected_roles": True,
        },
        "limitations": [
            "Named match-history records are joined by competition ID, date and opponent team ID to first-team fixtures; this is not a row-level identity mapping for the anonymous detailed match report.",
            "Only goalkeeper is currently an upstream-named MatchPosition value. All other position masks are preserved raw.",
            "The provisional mask-to-current-IP/OOP-position alignments are inferred separately from stable current A3.2 starter histories, not an official game-wide position-code dictionary.",
            "role_code meanings are unknown; values are preserved exactly and are not translated into roles.",
            "Current tactic slot position masks are mapped to exact native catalog positions; current selected role remains unresolved because fmsave role_bits are not proven role identifiers.",
            "Role candidate and role-duty permission outputs list positions/roles allowed by the catalog; they do not assert which role or personal instruction is currently selected.",
            "Raw tactic setting units are preserved; their individual instruction-value decoding still requires a verified field map.",
            "Current tactic slots and setting bitfields are a snapshot; they do not prove the tactic was unchanged for every historical match.",
            "Missing named histories remain missing; this audit never fabricates names or substitutes current selection for historical appearance.",
        ],
    }
    joined_fixtures = {(x["competition_id"], x["date"], x["opponent_team_id"]) for x in joined}
    for f in team_fixtures:
        k=(f["competition_id"],f["date"],f["opponent_team_id"])
        if k not in joined_fixtures:
            coverage["fixtures_without_named_player_history"].append({"date":f["date"],"competition_id":f["competition_id"],"opponent":f["opponent_club_short_name"],"opponent_team_id":f["opponent_team_id"]})

    # Evidence frequency of opaque role codes, grouped by raw position mask.
    role_counts: dict[tuple[int | None, int | None], dict[str, Any]] = {}
    for x in joined:
        if not x["has_stats"]: continue
        key=(x["position_code"],x["role_code_raw"])
        z=role_counts.setdefault(key,{"rows":0,"players":set(),"names":set()})
        z["rows"]+=1; z["players"].add(x["player_uid"]); z["names"].add(x["player_name"])
    role_rows=[{"position_code":k[0],"position_mask_hex":f"0x{k[0]:04X}" if k[0] is not None else "",
                "role_code_raw":k[1],"records":v["rows"],"unique_players":len(v["players"]),
                "players":";".join(sorted(v["names"])),
                "meaning":"UNDECODED - preserve raw value"} for k,v in sorted(role_counts.items(),key=lambda kv:(-1 if kv[0][0] is None else kv[0][0],-1 if kv[0][1] is None else kv[0][1]))]

    hist_fields = ["player_uid","player_name","date","competition_id","competition_name","stage_id","round","team_id","is_home","opponent_team_id","opponent_club_uid","opponent_club_name","opponent_club_short_name","team_goals","opponent_goals","match_result","has_stats","position_code","position_mask_hex","position_label_official","position_label_raw","inferred_current_ip_position","ip_position_inference_status","current_ip_comparison","inferred_current_oop_position","oop_position_inference_status","current_oop_comparison","role_code_raw","minutes","left_at_minute","rating","goals","assists","passes_attempted","passes_completed","stats_in_range","selection_type","current_tactic_slot","current_ip_position","current_ip_position_zh","current_ip_position_fmsave_label","current_oop_position","current_oop_position_zh","current_oop_position_fmsave_label"]
    summary_fields = ["player_uid","player_name","selection_type","current_tactic_slot","current_ip_position","current_ip_position_zh","current_oop_position","current_oop_position_zh","named_match_records","matches_with_stats","position_code_counts","dominant_position_code","dominant_position_share","role_code_counts","stable_for_current_tactic_evidence","player_specific_alignment_status"]
    evidence_fields = ["position_code","position_mask_hex","inferred_current_ip_position","ip_evidence_status","inferred_current_oop_position","oop_evidence_status","supporting_starter_count","supporting_starters","supporting_record_count","warning"]
    role_fields = ["position_code","position_mask_hex","role_code_raw","records","unique_players","players","meaning"]
    slot_fields = ["player_uid","player_name","selection_type","selection_slot","tactic_slot","in_possession_position_id","in_possession_position_zh","in_possession_position_mask_raw","in_possession_candidate_roles","in_possession_selected_role","in_possession_selected_role_status","out_of_possession_position_id","out_of_possession_position_zh","out_of_possession_position_mask_raw","out_of_possession_candidate_roles","out_of_possession_selected_role","out_of_possession_selected_role_status","in_possession_positions","out_of_possession_positions","in_possession_settings_raw","out_of_possession_settings_raw","in_possession_role_bits_raw","out_of_possession_role_bits_raw","in_possession_trail_bits_raw","out_of_possession_trail_bits_raw"]
    candidate_fields = ["player_uid","player_name","selection_type","tactic_slot","phase","phase_catalog","position_id","position_zh","position_mask_raw","candidate_role_id","candidate_role_zh","catalog_role_phase","catalog_role_flags_raw","catalog_role_defaults_raw","role_bits_raw","trail_bits_raw","selected_role_id","selected_role_zh","selected_role_status","warning"]
    permission_fields = ["player_uid","player_name","tactic_slot","phase","position_id","position_zh","candidate_role_id","candidate_role_zh","duty_raw","editable_context_1a080000","fixed_on","fixed_off","editable_context_1b000000","context_status_differs","unavailable_option_count","permission_record_status","warning"]
    candidate_summary_fields = ["player_uid","player_name","tactic_slot","phase","position_id","position_zh","candidate_role_count","candidate_roles_zh","selected_role_id","selected_role_zh","selected_role_status","role_bits_raw","trail_bits_raw"]
    joined_sorted = sorted(joined,key=lambda x:(x["date"],x["competition_id"],x["player_name"]))
    save_csv(root/"player-position-history.csv", joined_sorted, hist_fields)
    (root/"player-position-history.json").write_text(json.dumps(joined_sorted,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    save_csv(root/"player-position-player-summary.csv", player_summary, summary_fields)
    save_csv(root/"player-position-mask-evidence.csv", evidence_rows, evidence_fields)
    save_csv(root/"player-position-role-code-audit.csv", role_rows, role_fields)
    save_csv(root/"player-current-tactic-slot-map.csv", slot_map_rows, slot_fields)
    save_csv(root/"player-current-role-candidates.csv", role_candidate_rows, candidate_fields)
    save_csv(root/"player-current-role-duty-permissions.csv", role_duty_permission_rows, permission_fields)
    save_csv(root/"player-current-role-candidate-summary.csv", candidate_summary, candidate_summary_fields)
    (root/"player-position-coverage.json").write_text(json.dumps(coverage,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    (root/"player-position-unmatched-joins.json").write_text(json.dumps(unmatched_history,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")

    print("POSITION HISTORY AUDIT COMPLETE")
    print(f"First-team fixtures: {len(team_fixtures)} | joined named records: {len(joined)} | with stats: {coverage['joined_rows_with_stats']}")
    print(f"Players with history: {coverage['unique_players_with_history']} | provisional IP/OOP alignments: {coverage['provisional_ip_position_mask_mappings']}/{coverage['provisional_oop_position_mask_mappings']}")
    print(f"Fixtures missing named history: {len(coverage['fixtures_without_named_player_history'])}")
    print(f"Native position mapping: {len(position_by_mask)} positions | role candidates: {len(role_candidate_rows)} | role-duty permission rows: {len(role_duty_permission_rows)}")
    print("Selected role and live PI values remain unresolved; raw role/settings data preserved. Anonymous detailed rows were NOT assigned names.")
    return 0

if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        print(f"POSITION AUDIT ERROR: {exc}", file=sys.stderr)
        raise
'@
    Set-Content -LiteralPath $helperPath -Value $pythonHelper -Encoding UTF8

    $helperArgs = @()
    if ($script:PythonPrefix.Count -gt 0) { $helperArgs += $script:PythonPrefix }
    $helperArgs += @(
        $helperPath,
        $script:OutDir,
        '--team-id', '539',
        '--club-uid', '680',
        '--tactic-name', 'ENGINE HARVESTER A3.2 - CLEAN PI IMPORT',
        '--catalog', $catalogPath,
        '--role-permissions', $permissionPath
    )

    Write-Host ''
    Write-Host 'Building named player position history and A3.2 alignment audit...' -ForegroundColor Cyan
    $result = Invoke-NativeCapture -FilePath $script:PythonExe -Arguments $helperArgs -Label 'player_position_history_audit'
    Add-Diagnostic -Title 'player position history audit stdout' -Text $result.StdOut
    Add-Diagnostic -Title 'player position history audit stderr' -Text $result.StdErr

    if (-not [string]::IsNullOrWhiteSpace($result.StdOut)) { Write-Host $result.StdOut.Trim() }
    if ($result.ExitCode -ne 0) {
        $script:Errors.Add('player position history audit: failed; see native-diagnostics.txt')
        if (-not [string]::IsNullOrWhiteSpace($result.StdErr)) { Write-Host $result.StdErr.Trim() -ForegroundColor Yellow }
    }
    else {
        Write-Host 'Named player position-history files created. Raw role codes and unverified masks remain preserved.' -ForegroundColor Green
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
        $reuseRequired = @('first-team-scope.json','fixtures.json','player-match-stats.json','player-season-stats.csv','team-match-stats.json')
        $reuseMissing = @($reuseRequired | Where-Object { -not (Test-Path -LiteralPath (Join-Path $script:OutDir $_) -PathType Leaf) })
        if ($reuseMissing.Count -gt 0) {
            throw ('Existing export folder is incomplete; missing: ' + ($reuseMissing -join ', '))
        }
        $scope = Get-Content -LiteralPath (Join-Path $script:OutDir 'first-team-scope.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        if ([int]$scope.team_id -ne $script:TeamId -or [int]$scope.club_uid -ne $script:ClubUid) {
            throw ('Existing folder is not the configured Manchester United first-team export (team_id=539, club_uid=680).')
        }
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
        Export-FmTable -TableName 'tactics' -ExtraArgs @('--managed-club', '--format', 'json')
        Export-FmTable -TableName 'set-pieces' -ExtraArgs @('--managed-club', '--format', 'json')
        Export-FmTable -TableName 'selections' -ExtraArgs @('--managed-club', '--format', 'json')
    
        # Add named player identity + position history without anonymous-row guesses.
        Invoke-PlayerPositionHistoryAudit
    
        # Reduce the saved bundle to first-team-only data; no opponent-side performance remains.
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
        'FM27 FIRST-TEAM ONLY analysis export bundle v1.4.5 (formal competitions)',
        'Default named player history uses a save-scoped route under FM27_PlayerMatchHistoryArchives beside the save file.',
        'Overlapping fixture or named-row conflicts automatically fork a new save-specific archive branch; conflicting histories are never merged.',
        'Parser version is pinned to fmsave==0.12.4; automatic upgrades are disabled.',
        'Save path defaults to the configured FM27 2.fm; override with -SavePath when needed.',
        'Optional -ReuseExportDir reuses an existing first-team export folder and regenerates only the detailed formal player reports.',
        '',
        'Files include first-team fixtures, first-team own-side team-match-stats, player profiles/attributes,',
        'first-team player-season-stats, first-team player-match-stats, tactics, set-pieces, selections,',
        'save-info, parser validation and first-team-scope.json.',
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
        'players.json contains only current first-team team_id 539 profiles; no reserve/youth profiles are kept.',
        'Historical reserve/youth players are retained only on individual first-team match rows where they logged minutes; their full profiles and reserve statistics are excluded.',
        'Reserve/youth match-sheet rows without minutes are removed per match, even for a guest who appeared in another match.',
        'Opponent identity, competition, date, venue and score remain as match context only.',
        'Opponent player profiles and opponent-side performance rows are excluded.',
        'Additional named-player audit outputs: player-position-history.csv/json,',
        'player-position-player-summary.csv, player-position-mask-evidence.csv,',
        'player-position-role-code-audit.csv, player-current-tactic-slot-map.csv,',
        'player-current-role-candidates.csv, player-current-role-candidate-summary.csv,',
        'player-current-role-duty-permissions.csv, player-position-coverage.json and player-position-unmatched-joins.json.',
        'The native catalog maps full current tactic masks to all 24 position IDs and lists eligible IP/OOP role candidates.',
        'The role-duty permission file contains workbook-decoded combinations with editable/fixed-on/fixed-off options.',
        'Candidate roles and permission lists are NOT the actual selected role or live personal-instruction values.',
        'The save raw role bits do not uniquely identify the selected role; they are preserved, not guessed.',
        'For FM27 27.0.1+2494687 with match_stats_cfg schema 6, fmsave 0.12.4 borrows the registered 27.0.0 schema-6 layout because 27.0.1 is not upstream-registered.',
        'The generated team-match-stats-compatibility.json records the reader status, source layout, formal-fixture coverage, team totals and raw-field cross-checks for this save only.',
        'A local compatibility pass does not change fmsave known_build and is not a claim of upstream verification for other saves/builds.',
        'Named player history is joined to first-team fixtures by competition, date and opponent team ID.',
        'Historical position and role_code values are preserved raw; provisional position alignment is checked',
        'separately from the exact current tactic position ID. Selected role and current PI values remain undecoded.',
        '',
        'IMPORTANT: FM27 builds newer than the parser registered build may be unverified.',
        'Some fields or readers may be unavailable. Check validation.json and',
        'native-diagnostics.txt before treating any exported data as complete.',
        'FM27_FirstTeam_Filter_v1.2.2.py enforces strict first-team scope and per-match guest-minute filtering.',
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
        if ($script:ReuseMode) { Write-Host 'Detailed formal player reports regenerated in the existing first-team export folder.' -ForegroundColor Green } else { Write-Host 'First-team-only export v1.4.5 formal-competition finished.' -ForegroundColor Green }
        Write-Host 'Inspect first-team-scope.json, validation.json and player-report-identity-audit.json.' -ForegroundColor Cyan
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

