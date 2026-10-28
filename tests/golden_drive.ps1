# Load AgentParcel.core.ps1 and split, verify, or rebuild one part set.
# Used by tests/test_golden.py. Windows PowerShell 5.1 and PowerShell 7.
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('SplitBytes', 'SplitZip', 'Verify', 'Rebuild')]
    [string]$Action,
    [Parameter(Mandatory = $true)]
    [string]$InputPath,
    [string]$OutputDir,
    [long]$Limit = 0
)

$ErrorActionPreference = 'Stop'
# AgentParcel.core.ps1 has its own param($OutputDir). Dot-sourcing it runs in this scope and
# resets that variable, so keep the caller's values under other names first.
$DoAction = $Action
$DoInput = $InputPath
$DoOutput = $OutputDir
$DoLimit = $Limit
$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$lib = Join-Path ([System.IO.Path]::GetTempPath()) ('ap-golden-lib-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $lib | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'src/AgentParcel.core.ps1') -Destination (Join-Path $lib 'AgentParcel.core.ps1') -Force
Copy-Item -LiteralPath (Join-Path $root 'src/agentparcel/rebuild.py') -Destination (Join-Path $lib 'rebuild.py') -Force
$env:AGENTPARCEL_LIBRARY = '1'
. (Join-Path $lib 'AgentParcel.core.ps1')

$progress = { param($pct, $msg) }
if ($DoAction -eq 'SplitBytes') {
    if ($DoLimit -lt 1) { throw 'SplitBytes needs -Limit' }
    if (-not $DoOutput) { throw 'SplitBytes needs -OutputDir' }
    $split = Invoke-ByteSplit -SourcePath $DoInput -OutputDir $DoOutput -LimitBytes $DoLimit -IncludeApps $false -OnProgress $progress
    Write-Output ('SPLIT ' + $split.OutputDir)
    exit 0
}
if ($DoAction -eq 'SplitZip') {
    if ($DoLimit -lt 1) { throw 'SplitZip needs -Limit' }
    if (-not $DoOutput) { throw 'SplitZip needs -OutputDir' }
    $split = Invoke-ZipSplit -SourcePath $DoInput -OutputDir $DoOutput -LimitBytes $DoLimit -UnpackInner $false -IncludeApps $false -OnProgress $progress
    Write-Output ('SPLIT ' + $split.OutputDir)
    exit 0
}
if ($DoAction -eq 'Verify') {
    $report = Invoke-ZsVerify -InputPaths @($DoInput) -OnProgress $progress
    if (-not $report.Ok) {
        Write-Output $report.Message
        exit 1
    }
    Write-Output 'VERIFY_OK'
    exit 0
}
if ($DoAction -eq 'Rebuild') {
    if (-not $DoOutput) { throw 'Rebuild needs -OutputDir' }
    $rebuilt = Invoke-Rebuild -InputPaths @($DoInput) -OutputDir $DoOutput -OnProgress $progress
    Write-Output ('REBUILD ' + $rebuilt.OutputPath)
    exit 0
}
throw ('Unknown action ' + $DoAction)
