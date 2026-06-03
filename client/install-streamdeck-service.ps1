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

# ---- Locate pythonw.exe ---------------------------------------------------
$PythonW = $null
$pyCmd = Get-Command pythonw.exe -ErrorAction SilentlyContinue
if ($pyCmd) {
    $PythonW = $pyCmd.Source
} else {
    # Fall back to deriving pythonw from python on PATH
    $py = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($py) {
        $candidate = Join-Path (Split-Path $py.Source) "pythonw.exe"
        if (Test-Path $candidate) { $PythonW = $candidate }
    }
}
if (-not $PythonW) {
    throw "Could not find pythonw.exe on PATH. Install Python (with 'Add to PATH') and retry."
}

if (-not (Test-Path $DaemonPath)) {
    throw "streamdeck_daemon.py not found next to this script ($DaemonPath)."
}

# ---- Validate backend args ------------------------------------------------
if ($Backend -eq "groq" -and -not $GroqKey -and -not $env:GROQ_API_KEY) {
    throw "-GroqKey is required for -Backend groq (or set GROQ_API_KEY beforehand)."
}
if ($Backend -eq "server" -and -not $Server) {
    throw "-Server HOST:PORT is required for -Backend server."
}

# Persist the key as a user env var (the daemon reads GROQ_API_KEY).
if ($GroqKey) {
    [Environment]::SetEnvironmentVariable("GROQ_API_KEY", $GroqKey, "User")
    $env:GROQ_API_KEY = $GroqKey
    Write-Host "Stored GROQ_API_KEY as a per-user environment variable." -ForegroundColor Green
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

# ---- Build the task action ------------------------------------------------
# Resolve the key we'll actually use (param wins, else existing env var).
$EffectiveKey = if ($GroqKey) { $GroqKey } else { $env:GROQ_API_KEY }

$argList = @(
    "`"$DaemonPath`"", "daemon",
    "--backend", $Backend,
    "--port", "$Port",
    "--log-file", "`"$LogFile`""
)
if ($Backend -eq "server") { $argList += @("--server", $Server) }
# Pass the key directly: Task Scheduler does not reliably inherit a freshly-set
# user environment variable, so relying on GROQ_API_KEY alone can 401.
if ($Backend -eq "groq" -and $EffectiveKey) { $argList += @("--groq-key", $EffectiveKey) }
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

Write-Host ""
Write-Host "Stream Deck button -> System: Open ->" -ForegroundColor Cyan
Write-Host "  pythonw `"$DaemonPath`" toggle --port $Port"
Write-Host ""
Write-Host "To remove: powershell -ExecutionPolicy Bypass -File install-streamdeck-service.ps1 -Uninstall"
