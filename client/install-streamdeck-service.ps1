<#
.SYNOPSIS
    Install/remove the TalkFlow Stream Deck daemon as a hidden auto-start task.

.DESCRIPTION
    Registers a Scheduled Task that launches streamdeck_daemon.py at logon using
    pythonw.exe (no console window), so the daemon is always running when you sit
    down. Your Stream Deck button just runs `python streamdeck_daemon.py toggle`
    against it.

    Logs go to %LOCALAPPDATA%\TalkFlow\daemon.log (rotated).

.PARAMETER GroqKey
    Groq API key (gsk_...). Stored as a per-user environment variable, not baked
    into the task arguments. Required for -Backend groq (the default).

.PARAMETER Backend
    "groq" (default) or "server".

.PARAMETER Server
    HOST:PORT of a self-hosted transcription server (required for -Backend server).

.PARAMETER Port
    Local control port the daemon listens on (default 9878). Match your Stream
    Deck trigger if you change it.

.PARAMETER RemotePaste
    HOST:PORT of a paste_helper.py running on the active remote screen (the
    AI5090). When set, transcripts are typed directly on that machine instead of
    relying on DeskFlow clipboard/keystroke forwarding (falls back to local
    clipboard paste if unreachable). Port defaults to 9879.

.PARAMETER Uninstall
    Remove the scheduled task.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install-streamdeck-service.ps1 -GroqKey gsk_xxx

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install-streamdeck-service.ps1 -Uninstall
#>

[CmdletBinding()]
param(
    [string]$GroqKey = "",
    [ValidateSet("groq", "server")]
    [string]$Backend = "groq",
    [string]$Server = "",
    [int]$Port = 9878,
    [int]$Device = -1,
    [string]$RemotePaste = "",
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$TaskName   = "TalkFlow Stream Deck Daemon"
$ScriptDir  = Split-Path -Parent $MyInvocation.MyCommand.Definition
$DaemonPath = Join-Path $ScriptDir "streamdeck_daemon.py"
$LogDir     = Join-Path $env:LOCALAPPDATA "TalkFlow"
$LogFile    = Join-Path $LogDir "daemon.log"

# ---- Uninstall ------------------------------------------------------------
if ($Uninstall) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask  -TaskName $TaskName -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task: $TaskName" -ForegroundColor Green
    } else {
        Write-Host "No scheduled task named '$TaskName' found." -ForegroundColor Yellow
    }
    return
}

# ---- Locate python.exe / pythonw.exe --------------------------------------
# pythonw.exe runs the daemon with no console flash; python.exe is used for the
# one-shot `setup` call (so we can see its output).
$PythonExe = $null
$PythonW   = $null
$pyCmd = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pyCmd) {
    $PythonExe = $pyCmd.Source
    $candidate = Join-Path (Split-Path $pyCmd.Source) "pythonw.exe"
    if (Test-Path $candidate) { $PythonW = $candidate }
}
$pywCmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if (-not $PythonW -and $pywCmd) { $PythonW = $pywCmd.Source }
if (-not $PythonExe -and $pywCmd) {
    $candidate = Join-Path (Split-Path $pywCmd.Source) "python.exe"
    if (Test-Path $candidate) { $PythonExe = $candidate }
}
if (-not $PythonW)   { $PythonW = $PythonExe }   # fall back to console python
if (-not $PythonExe) { $PythonExe = $PythonW }
if (-not $PythonW) {
    throw "Could not find python.exe/pythonw.exe on PATH. Install Python (with 'Add to PATH') and retry."
}

if (-not (Test-Path $DaemonPath)) {
    throw "streamdeck_daemon.py not found next to this script ($DaemonPath)."
}

# ---- Validate backend args ------------------------------------------------
# A key already saved in config.json counts — so a reinstall never forces you
# to find and re-paste the key.
$ConfigFile = Join-Path $LogDir "config.json"
$HasConfigKey = $false
if (Test-Path $ConfigFile) {
    try { $HasConfigKey = [bool]((Get-Content $ConfigFile -Raw | ConvertFrom-Json).groq_key) } catch {}
}
if ($Backend -eq "groq" -and -not $GroqKey -and -not $env:GROQ_API_KEY -and -not $HasConfigKey) {
    throw "-GroqKey is required for -Backend groq (or set GROQ_API_KEY, or save it once with: python streamdeck_daemon.py setup --groq-key gsk_...)."
}
if ($Backend -eq "server" -and -not $Server) {
    throw "-Server HOST:PORT is required for -Backend server."
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# ---- Persist settings into the daemon's config (set ONCE) -----------------
# The daemon reads %LOCALAPPDATA%\TalkFlow\config.json on startup, so we store
# the key/mic/remote target there instead of baking them into the task command.
# This means changing the key later is just another `setup` call — no reinstall,
# and you never have to find and paste the key again.
$EffectiveKey = if ($GroqKey) { $GroqKey } else { $env:GROQ_API_KEY }
$setupArgs = @($DaemonPath, "setup", "--backend", $Backend)
if ($Backend -eq "server") { $setupArgs += @("--server", $Server) }
if ($Device -ge 0)         { $setupArgs += @("--device", "$Device") }
if ($RemotePaste)          { $setupArgs += @("--remote-paste", $RemotePaste) }
if ($EffectiveKey)         { $setupArgs += @("--groq-key", $EffectiveKey) }
$setupArgs += @("--port", "$Port")
& $PythonExe @setupArgs
if ($LASTEXITCODE -ne 0) { throw "Failed to write TalkFlow config (setup exited $LASTEXITCODE)." }

# ---- Build the task action ------------------------------------------------
# Only operational flags here; everything else comes from config.json.
$argList = @(
    "`"$DaemonPath`"", "daemon",
    "--log-file", "`"$LogFile`""
)
$Arguments = $argList -join " "

$action  = New-ScheduledTaskAction -Execute $PythonW -Argument $Arguments -WorkingDirectory $ScriptDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Kill any already-running daemon so it releases the port; otherwise a stale
# process (e.g. one started with an old key) keeps answering and the new one
# can't bind, leaving you talking to the wrong daemon.
Get-CimInstance Win32_Process -Filter "Name='pythonw.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*streamdeck_daemon.py*daemon*" } |
    ForEach-Object {
        Write-Host "Stopping stale daemon (PID $($_.ProcessId))..." -ForegroundColor Yellow
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Milliseconds 500

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description "Runs the TalkFlow voice-dictation daemon for the Stream Deck trigger." | Out-Null

Write-Host "Registered scheduled task: $TaskName" -ForegroundColor Green
Write-Host "  Python : $PythonW"
Write-Host "  Args   : $Arguments"
Write-Host "  Log    : $LogFile"
Write-Host "  Config : $(Join-Path $LogDir 'config.json')  (key/mic/remote live here)"
Write-Host "  Tip    : change settings later without reinstalling, e.g.:"
Write-Host "           python streamdeck_daemon.py setup --device 5"
Write-Host "           python streamdeck_daemon.py setup --show"

# ---- Start it now ---------------------------------------------------------
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2
Write-Host ""
if ((Test-NetConnection -ComputerName 127.0.0.1 -Port $Port -InformationLevel Quiet -WarningAction SilentlyContinue)) {
    Write-Host "Daemon is running and listening on 127.0.0.1:$Port." -ForegroundColor Green
} else {
    Write-Host "Task registered, but the daemon isn't answering yet. Check the log:" -ForegroundColor Yellow
    Write-Host "  $LogFile"
}

$VbsPath = Join-Path $ScriptDir "toggle.vbs"
Write-Host ""
Write-Host "Stream Deck button: add a 'System > Open' action and set App/File to:" -ForegroundColor Cyan
Write-Host "  $VbsPath"
Write-Host "(This runs the toggle silently via pythonw. The Open action cannot take"
Write-Host " arguments, so point it at the .vbs - not at streamdeck_daemon.py.)"
Write-Host ""
Write-Host "To remove: powershell -ExecutionPolicy Bypass -File install-streamdeck-service.ps1 -Uninstall"
