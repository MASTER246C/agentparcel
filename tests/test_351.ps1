# Regression checks for the Windows 3.4.0/3.5.0 bugs. Run with pwsh (or Windows PowerShell 5.1).
param(
    [string]$WorkDir,
    [ValidateSet('Self', 'VerifyDir', 'RebuildDir')]
    [string]$Action = 'Self',
    [string]$InputPath
)

$ErrorActionPreference = 'Stop'
$failures = New-Object System.Collections.Generic.List[string]
function Check([string]$Name, [bool]$Cond, [string]$Detail) {
    if ($Cond) { Write-Output ("PASS " + $Name) }
    else {
        Write-Output ("FAIL " + $Name + " " + $Detail)
        $script:failures.Add($Name)
    }
}

$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
$srcPs1 = Join-Path $root 'src/AgentParcel.core.ps1'
$srcRebuild = Join-Path $root 'src/agentparcel/rebuild.py'
if (-not $WorkDir) { $WorkDir = Join-Path ([System.IO.Path]::GetTempPath()) ('ap351-' + [guid]::NewGuid().ToString('N')) }
New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null
$lib = Join-Path $WorkDir 'lib'
New-Item -ItemType Directory -Force -Path $lib | Out-Null
Copy-Item -LiteralPath $srcPs1 -Destination (Join-Path $lib 'AgentParcel.core.ps1') -Force
Copy-Item -LiteralPath $srcRebuild -Destination (Join-Path $lib 'rebuild.py') -Force
$env:AGENTPARCEL_LIBRARY = '1'
. (Join-Path $lib 'AgentParcel.core.ps1')

if ($Action -eq 'VerifyDir') {
    $report = Invoke-ZsVerify -InputPaths @($InputPath) -OnProgress { param($pct, $msg) }
    if (-not $report.Ok) { Write-Output $report.Message; exit 1 }
    Write-Output 'VERIFY_OK'
    exit 0
}
if ($Action -eq 'RebuildDir') {
    $rebuilt = Join-Path $WorkDir 'from-ps'
    $result = Invoke-Rebuild -InputPaths @($InputPath) -OutputDir $rebuilt -OnProgress { param($pct, $msg) }
    Write-Output $result.OutputPath
    exit 0
}

# The log helper must turn LF into CRLF so the Windows text box shows one part per line.
$joined = Format-ZsLogError ("Corrupt part 1 (a): SHA-256 or size does not match the manifest`nCorrupt part 2 (b): SHA-256 or size does not match the manifest")
Check 'log errors are separate lines' ($joined -eq "Corrupt part 1 (a): SHA-256 or size does not match the manifest`r`nCorrupt part 2 (b): SHA-256 or size does not match the manifest") $joined

# Wrapping New-Object List[object] in @() is the zip-split crash. ::new() must stay safe,
# and the split path must not use @() on that list.
$list = New-Object System.Collections.Generic.List[object]
$threw = $false
try { $null = @($list) } catch { $threw = ($_.Exception.Message -eq 'Argument types do not match') }
Check 'New-Object List[object] still throws under @()' $threw $_.Exception.Message

$exe = Join-Path $WorkDir 'sample.exe'
$bytes = New-Object byte[] 250000
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$rng.GetBytes($bytes)
[System.IO.File]::WriteAllBytes($exe, $bytes)
$rng.Dispose()

$byteOut = Join-Path $WorkDir 'bytes'
$split = Invoke-ByteSplit -SourcePath $exe -OutputDir $byteOut -LimitBytes 80000 -IncludeApps $false -OnProgress { param($pct, $msg) }
$one = Join-Path $byteOut 'sample.exe_part01'
$report = Invoke-ZsVerify -InputPaths @($one) -OnProgress { param($pct, $msg) }
Check 'ps byte verify accepts its own parts' ([bool]$report.Ok) $report.Message
$rebuiltDir = Join-Path $WorkDir 'rebuilt'
$rb = Invoke-Rebuild -InputPaths @($one) -OutputDir $rebuiltDir -OnProgress { param($pct, $msg) }
$origHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $exe).Hash.ToLowerInvariant()
$newHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $rb.OutputPath).Hash.ToLowerInvariant()
Check 'ps rebuild matches original' ($origHash -eq $newHash) $newHash
Write-Output ("BYTEDIR " + $byteOut)

# Zip split with both boxes on: unpack inner zips, and include the apps bundle.
$innerPath = Join-Path $WorkDir 'inner.zip'
Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$fs = New-Object System.IO.FileStream($innerPath, [System.IO.FileMode]::CreateNew)
$zip = New-Object System.IO.Compression.ZipArchive($fs, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    $entry = $zip.CreateEntry('readme.txt')
    $w = New-Object System.IO.StreamWriter($entry.Open())
    try { $w.Write('inner file') } finally { $w.Dispose() }
} finally { $zip.Dispose(); $fs.Dispose() }
$outerPath = Join-Path $WorkDir 'Doom-sample.zip'
$fs = New-Object System.IO.FileStream($outerPath, [System.IO.FileMode]::CreateNew)
$zip = New-Object System.IO.Compression.ZipArchive($fs, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    $entry = $zip.CreateEntry('notes.txt')
    $w = New-Object System.IO.StreamWriter($entry.Open())
    try { $w.Write('outer') } finally { $w.Dispose() }
    $entry = $zip.CreateEntry('packs/inner.zip')
    $dst = $entry.Open()
    $src = [System.IO.File]::OpenRead($innerPath)
    try { $src.CopyTo($dst) } finally { $src.Dispose(); $dst.Dispose() }
} finally { $zip.Dispose(); $fs.Dispose() }

$zipOut = Join-Path $WorkDir 'zipout'
$zs = Invoke-ZipSplit -SourcePath $outerPath -OutputDir $zipOut -LimitBytes 1MB -UnpackInner $true -IncludeApps $true -OnProgress { param($pct, $msg) }
$partFiles = @(Get-ChildItem -LiteralPath $zipOut -File | Where-Object { $_.Name -like '*_part*.zip' })
Check 'zip split keeps parts' ($partFiles.Count -ge 1) ([string]$partFiles.Count)
Check 'zip set manifest written' (Test-Path -LiteralPath (Join-Path $zipOut '_agentparcel_zipset.json')) ''
Check 'unpack found the inner zip' (@($zs.UnpackedZips).Count -ge 1) ''
$zipReport = Invoke-ZsVerify -InputPaths @($partFiles[0].FullName) -OnProgress { param($pct, $msg) }
Check 'ps zip verify accepts the new set' ([bool]$zipReport.Ok) $zipReport.Message
Write-Output ("ZIPDIR " + $zipOut)

if ($failures.Count -gt 0) { Write-Output ("FAILED " + $failures.Count); exit 1 }
Write-Output 'PS ALL PASSED'
exit 0
