@echo off
rem ===========================================================================================
rem  Install-Python-for-AgentParcel.bat  (AgentParcel @@ZS_VERSION@@)
rem  Gets a real Python 3.15 for the AgentParcel MCP server - per user, no admin needed.
rem    1. uses an existing Python 3.15 if there is one (ignores the WindowsApps Store shortcut)
rem    2. else:  winget install -e --id Python.Python.3.15 --scope user
rem    3. else:  downloads the official python.org installer, checks its SHA-256 and its
rem              Python Software Foundation signature, and installs it silently for this user
rem    4. checks  python --version
rem    5. smoke-tests agentparcel_mcp.py (initialize + tools/list only, nothing is split)
rem    6. prints the MCP config snippets with the real python.exe path and saves them to
rem       MCP-config-snippets.txt next to this file. It never edits any agent config file.
rem  Options:  /nopause  (do not wait for a key at the end)    /nowinget  (skip step 2)
rem  Exit code 0 = ready, anything else = something failed (the message says what).
rem ===========================================================================================
setlocal EnableExtensions DisableDelayedExpansion
set "ZS_SELF=%~f0"
set "ZS_HERE=%~dp0"
set "ZS_PS=%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe"
if not exist "%ZS_PS%" set "ZS_PS=powershell.exe"
set "ZS_PYVER=3.15.1"
set "PYEXE="
set "RC=0"
set "NOPAUSE="
set "NOWINGET="
:args
if "%~1"=="" goto :argsdone
if /i "%~1"=="/nopause" set "NOPAUSE=1"
if /i "%~1"=="/nowinget" set "NOWINGET=1"
shift
goto :args
:argsdone

echo.
echo ==== AgentParcel: Python 3.15 setup (per user, no admin) ====
echo.
echo [1/6] Looking for an existing Python 3.15 ...
call :detect
if defined PYEXE (
    echo       found: "%PYEXE%"
    goto :haveversion
)
echo       none found.

if defined NOWINGET goto :download
echo.
echo [2/6] Trying winget (Python.Python.3.15, user scope) ...
where winget >nul 2>&1
if errorlevel 1 (
    echo       winget is not available on this PC - skipping.
    goto :download
)
winget install -e --id Python.Python.3.15 --scope user --silent --accept-package-agreements --accept-source-agreements
if errorlevel 1 echo       winget did not install it ^(exit code %errorlevel%^) - will use the python.org installer.
call :detect
if defined PYEXE (
    echo       installed by winget: "%PYEXE%"
    goto :haveversion
)

:download
echo.
echo [3/6] Downloading the official Python %ZS_PYVER% installer from python.org ...
set "ZS_MODE=install"
"%ZS_PS%" -NoProfile -ExecutionPolicy Bypass -Command "$t=[IO.File]::ReadAllText($env:ZS_SELF); $m=[char]10+'#==PS-'+'BLOCK=='; $i=$t.IndexOf($m); if($i -lt 0){ Write-Host 'ERROR: PowerShell part missing'; exit 90 }; & ([ScriptBlock]::Create($t.Substring($i))); exit $global:ZsRc"
if errorlevel 1 (
    echo.
    echo ERROR: the python.org install did not complete ^(see above^).
    set "RC=3"
    goto :end
)
call :detect
if not defined PYEXE (
    echo.
    echo ERROR: the installer finished but no Python 3.15 python.exe was found.
    echo        Expected: "%LOCALAPPDATA%\Programs\Python\Python315\python.exe"
    set "RC=3"
    goto :end
)
echo       installed: "%PYEXE%"

:haveversion
echo.
echo [4/6] Checking python --version ...
"%PYEXE%" --version
if errorlevel 1 (
    echo ERROR: "%PYEXE%" does not run.
    set "RC=4"
    goto :end
)

echo.
echo [5/6] Smoke-testing the AgentParcel MCP server ...
set "ZS_MCP="
if exist "%ZS_HERE%agentparcel_mcp.py" set "ZS_MCP=%ZS_HERE%agentparcel_mcp.py"
if not defined ZS_MCP if exist "%ZS_HERE%mcp\agentparcel_mcp.py" set "ZS_MCP=%ZS_HERE%mcp\agentparcel_mcp.py"
if not defined ZS_MCP if exist "%ZS_HERE%..\mcp\agentparcel_mcp.py" set "ZS_MCP=%ZS_HERE%..\mcp\agentparcel_mcp.py"
if not defined ZS_MCP (
    echo ERROR: agentparcel_mcp.py not found next to this file, in mcp\ or in ..\mcp\
    echo        Python itself is ready: "%PYEXE%"
    set "RC=5"
    goto :end
)
for %%F in ("%ZS_MCP%") do set "ZS_MCP=%%~fF"
echo       server: "%ZS_MCP%"
set "ZS_PY=%PYEXE%"
set "ZS_MODE=verify"
"%ZS_PS%" -NoProfile -ExecutionPolicy Bypass -Command "$t=[IO.File]::ReadAllText($env:ZS_SELF); $m=[char]10+'#==PS-'+'BLOCK=='; $i=$t.IndexOf($m); if($i -lt 0){ Write-Host 'ERROR: PowerShell part missing'; exit 90 }; & ([ScriptBlock]::Create($t.Substring($i))); exit $global:ZsRc"
if errorlevel 1 (
    set "RC=6"
    goto :end
)
echo.
echo ==== Ready. Python: "%PYEXE%" ====
echo Open a NEW terminal for "python" / "py" to be on PATH. Agent configs were NOT changed -
echo paste a snippet from MCP-config-snippets.txt yourself, then restart that app.

:end
echo.
if not "%RC%"=="0" echo FAILED with exit code %RC%.
if not defined NOPAUSE pause
exit /b %RC%

rem ------------------------------------------------------------------------------------------
rem :detect  sets PYEXE to the first real Python 3.15 python.exe it finds
rem ------------------------------------------------------------------------------------------
:detect
set "PYEXE="
call :try "%LOCALAPPDATA%\Programs\Python\Python315\python.exe"
call :try "%LOCALAPPDATA%\Python\pythoncore-3.15-64\python.exe"
call :try "%ProgramFiles%\Python315\python.exe"
if defined PYEXE exit /b 0
where py >nul 2>&1
if errorlevel 1 goto :detectpath
for /f "usebackq delims=" %%P in (`py -3.15 -c "import sys;print(sys.executable)" 2^>nul ^<nul`) do call :try "%%P"
if defined PYEXE exit /b 0
:detectpath
for /f "delims=" %%P in ('where python 2^>nul') do call :try "%%P"
exit /b 0

:try
if defined PYEXE exit /b 0
set "ZS_C=%~1"
if "%ZS_C%"=="" exit /b 0
rem the WindowsApps python.exe is only a Microsoft Store shortcut, never use it
if /i not "%ZS_C:\WindowsApps\=%"=="%ZS_C%" exit /b 0
if not exist "%ZS_C%" exit /b 0
"%ZS_C%" -c "import sys;sys.exit(0 if sys.version_info[:2]==(3,15) else 1)" >nul 2>&1 <nul
if errorlevel 1 exit /b 0
set "PYEXE=%ZS_C%"
exit /b 0

rem ==========================================================================================
rem  Everything below is PowerShell (Windows PowerShell 5.1+). cmd never runs it; the lines
rem  above load it from this file with ZS_MODE=install or ZS_MODE=verify.
rem ==========================================================================================
#==PS-BLOCK==
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$global:ZsRc = 1

# python.org Python 3.15.1 (released 2026-10-21), SHA-256 from
# https://www.python.org/downloads/release/python-3151/
$ZsPyVersion = '3.15.1'
$ZsInstallers = @{
    'AMD64' = @('https://www.python.org/ftp/python/3.15.1/python-3.15.1-amd64.exe', '8b23839c6b2f3076fdff44c78d219a5393c7205f666cd95bd0c9a562bf8ea5db')
    'ARM64' = @('https://www.python.org/ftp/python/3.15.1/python-3.15.1-arm64.exe', 'f335b7fabe85d9c1fa0fa9c591a3e5aaaf9bba818a0f15f1fad0c7d813ee6003')
    'x86'   = @('https://www.python.org/ftp/python/3.15.1/python-3.15.1.exe', '477dbb986b66a1ffd3e4f3bdab08f5f3d5855bb5c72f20a4adde767801cfd533')
}

function Invoke-ZsInstall {
    $arch = $env:PROCESSOR_ARCHITEW6432
    if (-not $arch) { $arch = $env:PROCESSOR_ARCHITECTURE }
    if (-not $ZsInstallers.ContainsKey($arch)) { $arch = 'AMD64' }
    $url = $ZsInstallers[$arch][0]
    $want = $ZsInstallers[$arch][1]
    $name = [IO.Path]::GetFileName($url)
    $dst = Join-Path $env:TEMP ('zs-' + [Guid]::NewGuid().ToString('N').Substring(0, 8) + '-' + $name)
    Write-Host ('      ' + $url)
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch { }
    $curl = Join-Path $env:SystemRoot 'System32\curl.exe'
    $ok = $false
    if (Test-Path -LiteralPath $curl) {
        & $curl -fsSL --retry 3 -o $dst $url
        $ok = ($LASTEXITCODE -eq 0) -and (Test-Path -LiteralPath $dst)
    }
    if (-not $ok) {
        try {
            Invoke-WebRequest -Uri $url -OutFile $dst -UseBasicParsing
            $ok = Test-Path -LiteralPath $dst
        } catch {
            Write-Host ('ERROR: download failed: ' + $_.Exception.Message)
            return 31
        }
    }
    try {
        $mb = [Math]::Round((Get-Item -LiteralPath $dst).Length / 1MB, 1)
        Write-Host ('      downloaded ' + $mb + ' MB, checking it ...')
        $hash = (Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne $want) {
            Write-Host ('ERROR: SHA-256 mismatch - expected ' + $want + ', got ' + $hash + '. Not installing.')
            return 32
        }
        Write-Host '      SHA-256 matches python.org'
        $sig = Get-AuthenticodeSignature -LiteralPath $dst
        $subj = ''
        if ($sig.SignerCertificate) { $subj = $sig.SignerCertificate.Subject }
        if ($sig.Status -ne 'Valid' -or $subj -notmatch 'O=Python Software Foundation') {
            Write-Host ('ERROR: signature check failed (' + $sig.Status + ', ' + $subj + '). Not installing.')
            return 33
        }
        Write-Host '      signature valid: Python Software Foundation'
        Write-Host ('[3/6] Installing Python ' + $ZsPyVersion + ' for this user only (takes a minute) ...')
        $log = Join-Path $env:TEMP ('python-' + $ZsPyVersion + '-install.log')
        $argList = @('/quiet', 'InstallAllUsers=0', 'InstallLauncherAllUsers=0', 'PrependPath=1',
                     'Include_launcher=1', 'Include_test=0', '/log', ('"' + $log + '"'))
        $p = Start-Process -FilePath $dst -ArgumentList $argList -Wait -PassThru
        if ($p.ExitCode -ne 0 -and $p.ExitCode -ne 3010) {
            Write-Host ('ERROR: the installer returned ' + $p.ExitCode + '. Log: ' + $log)
            return 34
        }
        Write-Host '      installer finished'
        return 0
    } finally {
        Remove-Item -LiteralPath $dst -Force -ErrorAction SilentlyContinue
    }
}

function ConvertTo-ZsJsonText([string]$s) {
    return $s.Replace('\', '\\').Replace('"', '\"')
}

function ConvertTo-ZsToml([string]$s) {
    if ($s.Contains("'")) { return '"' + $s.Replace('\', '\\').Replace('"', '\"') + '"' }
    return "'" + $s + "'"
}

function Invoke-ZsVerify {
    $py = $env:ZS_PY
    $mcp = $env:ZS_MCP
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $py
    $psi.Arguments = '"' + $mcp + '"'
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $psi.EnvironmentVariables['PYTHONUTF8'] = '1'
    $psi.EnvironmentVariables['PYTHONDONTWRITEBYTECODE'] = '1'
    $proc = [System.Diagnostics.Process]::Start($psi)
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    $errTask = $proc.StandardError.ReadToEndAsync()
    $msgs = @(
        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"agentparcel-setup","version":"1"}}}',
        '{"jsonrpc":"2.0","method":"notifications/initialized"}',
        '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
    )
    foreach ($m in $msgs) { $proc.StandardInput.Write($m + "`n") }
    $proc.StandardInput.Close()
    if (-not $proc.WaitForExit(60000)) {
        try { $proc.Kill() } catch { }
        Write-Host 'ERROR: the MCP server did not answer within 60 seconds.'
        return 51
    }
    $out = $outTask.Result
    $err = $errTask.Result
    $init = $null
    $tools = $null
    foreach ($line in ($out -split "`n")) {
        $l = $line.Trim()
        if (-not $l) { continue }
        try { $o = ConvertFrom-Json -InputObject $l } catch {
            Write-Host ('ERROR: the server wrote a non-JSON line to stdout: ' + $l)
            return 52
        }
        if ($o.id -eq 1) { $init = $o }
        if ($o.id -eq 2) { $tools = $o }
    }
    if (-not $init -or -not $init.result -or -not $tools -or -not $tools.result) {
        Write-Host 'ERROR: no valid initialize / tools/list answer. Server log:'
        Write-Host $err
        return 53
    }
    $names = @($tools.result.tools | ForEach-Object { $_.name })
    $need = @('inspect', 'split_zip', 'split_any_file', 'split_files', 'verify', 'rebuild', 'make_apps_bundle')
    $missing = @($need | Where-Object { $names -notcontains $_ })
    if ($missing.Count -gt 0) {
        Write-Host ('ERROR: tools missing: ' + ($missing -join ', '))
        return 54
    }
    Write-Host ('      OK: ' + $init.result.serverInfo.name + ' ' + $init.result.serverInfo.version +
                ', protocol ' + $init.result.protocolVersion + ', tools: ' + ($names -join ', '))

    Write-Host ''
    Write-Host '[6/6] MCP config snippets (copy the one for your app):'
    $root = $env:USERPROFILE
    if (-not $root) { $root = [Environment]::GetFolderPath('UserProfile') }
    $pyJ = ConvertTo-ZsJsonText $py
    $mcpJ = ConvertTo-ZsJsonText $mcp
    $rootJ = ConvertTo-ZsJsonText $root
    $json = @(
        '{',
        '  "mcpServers": {',
        '    "agentparcel": {',
        ('      "command": "' + $pyJ + '",'),
        ('      "args": ["' + $mcpJ + '"],'),
        ('      "env": { "AGENTPARCEL_MCP_ROOTS": "' + $rootJ + '" }'),
        '    }',
        '  }',
        '}'
    )
    $lines = @(
        ('AgentParcel MCP server - config snippets for this PC (written ' + (Get-Date -Format 'yyyy-MM-dd HH:mm') + ')'),
        ('python : ' + $py),
        ('server : ' + $mcp),
        ('sandbox: AGENTPARCEL_MCP_ROOTS = ' + $root + '   (remove the env part to allow every folder)'),
        'Nothing was changed in any app. Paste the snippet yourself, then restart that app.',
        '',
        '--- Claude Desktop: %APPDATA%\Claude\claude_desktop_config.json (Settings > Developer > Edit Config),',
        '    merge into "mcpServers":'
    ) + $json + @(
        '',
        '--- Cursor: %USERPROFILE%\.cursor\mcp.json (merge into "mcpServers"):'
    ) + $json + @(
        '',
        '--- Claude Code (run once in a terminal):',
        ('claude mcp add agentparcel --scope user --env AGENTPARCEL_MCP_ROOTS="' + $root + '" -- "' + $py + '" "' + $mcp + '"'),
        '    (for long jobs set MCP_TOOL_TIMEOUT=1800000 before starting claude)',
        '',
        '--- Codex CLI: %USERPROFILE%\.codex\config.toml',
        '[mcp_servers.agentparcel]',
        ('command = ' + (ConvertTo-ZsToml $py)),
        ('args = [' + (ConvertTo-ZsToml $mcp) + ']'),
        ('env = { AGENTPARCEL_MCP_ROOTS = ' + (ConvertTo-ZsToml $root) + ' }'),
        'startup_timeout_sec = 20',
        'tool_timeout_sec = 1800'
    )
    foreach ($l in $lines) { Write-Host $l }
    $file = Join-Path $env:ZS_HERE 'MCP-config-snippets.txt'
    try {
        [IO.File]::WriteAllText($file, (($lines -join "`r`n") + "`r`n"), (New-Object System.Text.UTF8Encoding($false)))
        Write-Host ''
        Write-Host ('Saved: ' + $file)
    } catch {
        Write-Host ('(could not save ' + $file + ': ' + $_.Exception.Message + ')')
    }
    return 0
}

try {
    if ($env:ZS_MODE -eq 'install') { $global:ZsRc = [int](Invoke-ZsInstall) }
    elseif ($env:ZS_MODE -eq 'verify') { $global:ZsRc = [int](Invoke-ZsVerify) }
    else { Write-Host ('ERROR: unknown ZS_MODE ' + $env:ZS_MODE); $global:ZsRc = 2 }
} catch {
    Write-Host ('ERROR: ' + $_.Exception.Message)
    $global:ZsRc = 1
}
