# ============================================================
#  TalkFlow - Windows Installer
#  Run: powershell -ExecutionPolicy Bypass -File .\TalkFlow-Install.ps1
# ============================================================

$ErrorActionPreference = "Stop"
$TF_DIR = "$env:USERPROFILE\TalkFlow"
$SERVER = if ($env:TALKFLOW_SERVER) { $env:TALKFLOW_SERVER } else { "YOUR_SERVER:9876" }

Write-Host ""
Write-Host "  ========================================" -ForegroundColor Cyan
Write-Host "       TalkFlow - Windows Installer" -ForegroundColor Cyan
Write-Host "  ========================================" -ForegroundColor Cyan
Write-Host ""

# 1. Check Python
Write-Host "[1/5] Checking Python..." -ForegroundColor Yellow
try {
    $pyVer = python --version 2>&1
    Write-Host "  OK: $pyVer" -ForegroundColor Green
} catch {
    Write-Host "  ERROR: Python not found!" -ForegroundColor Red
    Write-Host "  Download: https://www.python.org/downloads/" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# 2. Create directory
Write-Host "[2/5] Setting up $TF_DIR ..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $TF_DIR | Out-Null
New-Item -ItemType Directory -Force -Path "$TF_DIR\client" | Out-Null
Write-Host "  OK" -ForegroundColor Green

# 3. Copy files
Write-Host "[3/5] Copying files..." -ForegroundColor Yellow
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$files = @("client.py", "audio_capture.py", "hotkey_listener.py",
           "keystroke_injector.py", "gui.py")
foreach ($f in $files) {
    $src = Join-Path $scriptDir "client\$f"
    if (Test-Path $src) {
        Copy-Item $src "$TF_DIR\client\" -Force
        Write-Host "  $f" -ForegroundColor Gray
    } else {
        Write-Host "  MISSING: $f" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
}
Write-Host "  OK" -ForegroundColor Green

# 4. Venv + deps
Write-Host "[4/5] Installing dependencies..." -ForegroundColor Yellow
python -m venv "$TF_DIR\client\.venv"
& "$TF_DIR\client\.venv\Scripts\pip.exe" install --quiet --upgrade pip
& "$TF_DIR\client\.venv\Scripts\pip.exe" install --quiet "websockets>=13.0" "pynput>=1.7.6" "sounddevice>=0.4.6" "numpy>=1.26"
Write-Host "  OK" -ForegroundColor Green

# 5. Launchers
Write-Host "[5/5] Creating launchers..." -ForegroundColor Yellow

# Default config (only if not already present)
if (-not (Test-Path "$TF_DIR\client\talkflow_config.json")) {
    $cfg = '{"server":"' + $SERVER + '","hotkey":"f9","mic_device":null,"mic_device_name":"System Default"}'
    [System.IO.File]::WriteAllText("$TF_DIR\client\talkflow_config.json", $cfg)
}

# GUI launcher bat
$lines = @(
    "@echo off",
    "call ""$TF_DIR\client\.venv\Scripts\activate.bat""",
    "cd /d ""$TF_DIR\client""",
    "pythonw gui.py"
)
[System.IO.File]::WriteAllLines("$TF_DIR\TalkFlow.bat", $lines)

# Desktop shortcut
try {
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut("$env:USERPROFILE\Desktop\TalkFlow.lnk")
    $Shortcut.TargetPath = "$TF_DIR\TalkFlow.bat"
    $Shortcut.WorkingDirectory = "$TF_DIR"
    $Shortcut.Description = "TalkFlow - Push-to-Talk Voice Dictation"
    $Shortcut.Save()
    Write-Host "  Desktop shortcut created" -ForegroundColor Green
} catch {
    Write-Host "  Could not create shortcut (non-critical)" -ForegroundColor Yellow
}

Write-Host "  OK" -ForegroundColor Green

Write-Host ""
Write-Host "  ========================================" -ForegroundColor Green
Write-Host "       Installation Complete!" -ForegroundColor Green
Write-Host "  ========================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Double-click TalkFlow on your Desktop" -ForegroundColor White
Write-Host ""
Write-Host "  How it works:" -ForegroundColor Cyan
Write-Host "    1. Open TalkFlow" -ForegroundColor White
Write-Host "    2. Pick your mic, test connection" -ForegroundColor White
Write-Host "    3. Click Start" -ForegroundColor White
Write-Host "    4. Hold F9 while you talk" -ForegroundColor White
Write-Host "    5. Release - text appears at your cursor" -ForegroundColor White
Write-Host ""
Read-Host "Press Enter to exit"
