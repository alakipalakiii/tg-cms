param(
    [ValidateSet('Start', 'Setup', 'Verify')]
    [string]$Mode = 'Start'
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONUTF8 = '1'
$root = Split-Path -Parent $PSScriptRoot
$site = Join-Path $root 'website\dreary-disk'
$output = Join-Path $root 'local-output'

function Run-Checked([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "LOCAL_COMMAND_FAILED: $Program (exit $LASTEXITCODE)" }
}

try {
    Set-Location -LiteralPath $root
    foreach ($tool in @('git', 'node', 'npm.cmd', 'python')) {
        if (!(Get-Command $tool -ErrorAction SilentlyContinue)) { throw "MISSING_TOOL: $tool. Read MAHOON-TRANSFER-GUIDE-FA.md" }
    }
    $nodeVersion = [version](& node -p 'process.versions.node')
    if ($LASTEXITCODE -ne 0 -or $nodeVersion.Major -notin @(22, 24) -or ($nodeVersion.Major -eq 22 -and $nodeVersion.Minor -lt 12)) { throw 'Use Node.js 22 (22.12+) or 24; CI uses Node22.' }
    Run-Checked python @('-c', 'import sys; assert sys.version_info[:2] in [(3,12),(3,13)], "Use Python3.12 or3.13"')
    Run-Checked git @('rev-parse', '--show-toplevel')
    if (!(Test-Path -LiteralPath (Join-Path $root '.git\objects'))) { throw 'NOT_SELF_CONTAINED_GIT: copy the complete folder including .git.' }
    if (Test-Path -LiteralPath (Join-Path $root '.git\objects\info\alternates')) { throw 'EXTERNAL_GIT_OBJECTS: this copy requires reconciliation.' }
    if (!(Test-Path -LiteralPath (Join-Path $site 'package-lock.json'))) { throw 'LOCKFILE_MISSING' }
    Write-Host "MAHOON root: $root"
    Run-Checked git @('status', '--short')
    if ($Mode -eq 'Setup') {
        # npm verifies package integrity against the committed lockfile.
        Run-Checked npm.cmd @('ci', '--prefix', $site, '--no-audit', '--no-fund')
        Write-Host 'SUCCESS | LOCAL_DEPENDENCIES_INSTALLED; production unchanged.'
    } elseif ($Mode -eq 'Verify') {
        if (!(Test-Path -LiteralPath (Join-Path $site 'node_modules\astro'))) { throw 'DEPENDENCIES_MISSING: run MAHOON-SETUP.cmd first.' }
        New-Item -ItemType Directory -Path $output -Force | Out-Null
        $localTemp = Join-Path $output 'temp'
        New-Item -ItemType Directory -Path $localTemp -Force | Out-Null
        $env:TEMP = $localTemp
        $env:TMP = $localTemp
        $env:PUBLIC_MAHOON_SNAPSHOT_BINDING = '1'
        $env:ASTRO_TELEMETRY_DISABLED = '1'
        $env:MAHOON_RUN_BROWSER_TESTS = '0'
        $env:PYTHONPATH = (Join-Path $root 'tools\publisher') + ';' + (Join-Path $root 'tools') + ';' + $root
        Run-Checked npm.cmd @('run', 'build', '--prefix', $site)
        Run-Checked python @('-m', 'unittest', 'test_scheduled_a6_path', 'test_scheduled_circuit_breaker', 'test_artifact_contract')
        Run-Checked node @('tools/publisher/test_telegram_boundary.mjs')
        Run-Checked python @('local-tools/test_portability.py')
        Write-Host 'SUCCESS | LOCAL_BUILD_PUBLISHER_AND_TELEGRAM_BOUNDARY; no production operations.'
    } else {
        Write-Host 'Ready. Open this folder in Codex. SETUP installs pinned dependencies; VERIFY runs offline local checks.'
        Write-Host 'Transfer instructions: MAHOON-TRANSFER-GUIDE-FA.md'
        if ($env:MAHOON_NONINTERACTIVE -ne '1') { Start-Process explorer.exe -ArgumentList ('"' + $root + '"') }
    }
    exit 0
} catch {
    Write-Host ('STOPPED | ' + $_.Exception.Message)
    exit 1
}
