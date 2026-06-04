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
    Write-Host "  CHECK 'Add python.exe to PATH' during install!" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# 2. Create directory
Write-Host "[2/5] Setting up $TF_DIR ..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $TF_DIR | Out-Null
New-Item -ItemType Directory -Force -Path "$TF_DIR\client" | Out-Null
Write-Host "  OK" -ForegroundColor Green

# 3. Copy files (all client modules + requirements + assets)
Write-Host "[3/5] Copying files..." -ForegroundColor Yellow
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$srcClient = Join-Path $scriptDir "client"
if (-not (Test-Path $srcClient)) {
    Write-Host "  ERROR: 'client' folder not found next to this installer." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
# If the installer is already running from the target location (e.g. you cloned
# into ~\talkflow and the install dir is ~\TalkFlow, which is the SAME folder on
# case-insensitive Windows), there is nothing to copy.
$destClient = Join-Path $TF_DIR "client"
$srcFull = ([System.IO.Path]::GetFullPath($srcClient)).TrimEnd('\')
$destFull = ([System.IO.Path]::GetFullPath($destClient)).TrimEnd('\')
if ($srcFull -ieq $destFull) {
    Write-Host "  Already in the install location - skipping copy." -ForegroundColor Gray
} else {
    # Copy every Python module so new files are picked up automatically.
    Copy-Item "$srcClient\*.py" "$destClient\" -Force
    foreach ($f in (Get-ChildItem "$srcClient\*.py" | Select-Object -ExpandProperty Name)) {
        Write-Host "  $f" -ForegroundColor Gray
    }
    if (Test-Path "$srcClient\requirements.txt") {
        Copy-Item "$srcClient\requirements.txt" "$destClient\" -Force
    }
    if (Test-Path "$srcClient\assets") {
        Copy-Item "$srcClient\assets" "$destClient\" -Recurse -Force
        Write-Host "  assets" -ForegroundColor Gray
    }
}
# Sanity check: the DeskFlow delivery module must be present.
if (-not (Test-Path "$TF_DIR\client\clipboard_injector.py")) {
    Write-Host "  ERROR: clipboard_injector.py missing - source tree is incomplete." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "  OK" -ForegroundColor Green

# 4. Venv + deps (from requirements.txt so the list never drifts)
Write-Host "[4/5] Installing dependencies (this may take a minute)..." -ForegroundColor Yellow
python -m venv "$TF_DIR\client\.venv"
$pip = "$TF_DIR\client\.venv\Scripts\pip.exe"
& $pip install --quiet --upgrade pip
if (Test-Path "$TF_DIR\client\requirements.txt") {
    & $pip install --quiet -r "$TF_DIR\client\requirements.txt"
} else {
    & $pip install --quiet "websockets>=13.0" "pynput>=1.7.6" "sounddevice>=0.4.6" `
        "numpy>=1.26" "pyperclip>=1.8.2" "pystray>=0.19" "Pillow>=10.0"
}
Write-Host "  OK" -ForegroundColor Green

# 5. Launchers + config
Write-Host "[5/5] Creating launchers..." -ForegroundColor Yellow

# Default config (only if not already present). Defaults to DeskFlow paste
# delivery, since TalkFlow is built to pair with DeskFlow.
if (-not (Test-Path "$TF_DIR\client\config.json")) {
    $cfg = [ordered]@{
        backend                = "groq"
        groq_api_key           = ""
        server                 = $SERVER
        hotkey                 = "f9"
        mic_device             = $null
        mic_device_name        = "System Default"
        delivery_mode          = "deskflow_paste"
        paste_sync_delay_ms    = 250
        paste_restore_delay_ms = 700
        minimize_to_tray       = $true
        play_sounds            = $true
        auto_start_on_launch   = $false
    } | ConvertTo-Json
    [System.IO.File]::WriteAllText("$TF_DIR\client\config.json", $cfg)
    Write-Host "  config.json (delivery_mode = deskflow_paste)" -ForegroundColor Gray
}

# GUI launcher bat
$lines = @(
    "@echo off",
    "call ""$TF_DIR\client\.venv\Scripts\activate.bat""",
    "cd /d ""$TF_DIR\client""",
    "pythonw gui.py"
)
[System.IO.File]::WriteAllLines("$TF_DIR\TalkFlow.bat", $lines)

# Desktop shortcut (use the real Desktop folder, which may be redirected to OneDrive)
try {
    $WshShell = New-Object -ComObject WScript.Shell
    $desktop = [Environment]::GetFolderPath("Desktop")
    $Shortcut = $WshShell.CreateShortcut("$desktop\TalkFlow.lnk")
    $Shortcut.TargetPath = "$TF_DIR\TalkFlow.bat"
    $Shortcut.WorkingDirectory = "$TF_DIR"
    $Shortcut.Description = "TalkFlow - Push-to-Talk Voice Dictation"
    if (Test-Path "$TF_DIR\client\assets\logo.ico") {
        $Shortcut.IconLocation = "$TF_DIR\client\assets\logo.ico"
    }
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
Write-Host "  First run:" -ForegroundColor Cyan
Write-Host "    1. Pick your transcription backend (Groq key or self-hosted server)" -ForegroundColor White
Write-Host "    2. Choose your microphone and test it" -ForegroundColor White
Write-Host "    3. Keep the hotkey on F9 (a bare function key won't leak to remotes)" -ForegroundColor White
Write-Host "    4. Delivery is set to 'DeskFlow' - pastes to whichever screen has the cursor" -ForegroundColor White
Write-Host "    5. Click Start, hold F9, speak, release" -ForegroundColor White
Write-Host ""
Write-Host "  DeskFlow reminders:" -ForegroundColor Cyan
Write-Host "    - Run TalkFlow only on this machine (the DeskFlow primary)" -ForegroundColor White
Write-Host "    - Keep DeskFlow clipboard sharing ON" -ForegroundColor White
Write-Host "    - For a Mac client, enable DeskFlow's Cmd/Ctrl mapping for that screen" -ForegroundColor White
Write-Host ""
Read-Host "Press Enter to exit"
