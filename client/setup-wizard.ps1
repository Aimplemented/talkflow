<#
.SYNOPSIS
    Guided first-run setup for the TalkFlow Stream Deck client.

.DESCRIPTION
    Walks you through everything needed to dictate from this PC: it finds Python,
    installs the client dependencies, runs the doctor self-check, helps you pick a
    working microphone (with a live level test), collects your Groq API key and the
    optional AI5090 remote-paste target, saves it all to the daemon's config, and
    registers the background daemon as a Scheduled Task via
    install-streamdeck-service.ps1. Finally it prints exactly which files to point
    your two Stream Deck buttons at.

    The wizard is idempotent: re-running it keeps any existing saved key/mic/remote
    (just press Enter at a prompt to keep what's there). Everything is stored in
    %LOCALAPPDATA%\TalkFlow\config.json, so changing a setting later never means
    finding and re-pasting your key.

.PARAMETER GroqKey
    Groq API key (gsk_...). If omitted, the wizard prompts; pass it to run
    unattended. A key already saved in config (or GROQ_API_KEY) is reused.

.PARAMETER RemotePaste
    HOST:PORT of a paste_helper.py on the AI5090 (the active remote screen). Enables
    the second Stream Deck button (toggle-remote). Optional — leave blank to skip.

.PARAMETER NonInteractive
    Run without prompting. Uses the provided -GroqKey/-RemotePaste plus whatever is
    already saved in config / the environment. Skips the interactive mic picker
    (keeps the saved mic). Suitable for scripted/silent installs.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup-wizard.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File setup-wizard.ps1 -GroqKey gsk_xxx -RemotePaste 192.168.1.50:9879 -NonInteractive
#>

[CmdletBinding()]
param(
    [string]$GroqKey = "",
    [string]$RemotePaste = "",
    [switch]$NonInteractive
)

$ErrorActionPreference = "Stop"

# ---- Paths ----------------------------------------------------------------
$ScriptDir   = Split-Path -Parent $MyInvocation.MyCommand.Definition
$DaemonPath  = Join-Path $ScriptDir "streamdeck_daemon.py"
$ReqPath     = Join-Path $ScriptDir "requirements.txt"
$InstallPs1  = Join-Path $ScriptDir "install-streamdeck-service.ps1"
$ConfigFile  = Join-Path $env:LOCALAPPDATA "TalkFlow\config.json"
$TogglePc    = Join-Path $ScriptDir "toggle.vbs"
$ToggleRemote = Join-Path $ScriptDir "toggle-remote.vbs"

# ---- Output helpers -------------------------------------------------------
function Write-Section($Title) {
    Write-Host ""
    Write-Host "===================================================================" -ForegroundColor Cyan
    Write-Host "  $Title" -ForegroundColor Cyan
    Write-Host "===================================================================" -ForegroundColor Cyan
}
function Write-Step($Msg)  { Write-Host ">> $Msg" -ForegroundColor White }
function Write-Good($Msg)  { Write-Host "   [OK]   $Msg" -ForegroundColor Green }
function Write-Warn2($Msg) { Write-Host "   [warn] $Msg" -ForegroundColor Yellow }
function Write-Bad($Msg)   { Write-Host "   [FAIL] $Msg" -ForegroundColor Red }

Write-Section "TalkFlow Stream Deck — Setup Wizard"
Write-Host "  This sets up voice dictation from this PC." -ForegroundColor Gray
if ($NonInteractive) { Write-Host "  (running non-interactive — using existing config / passed args)" -ForegroundColor Gray }

# ---- (a) Find & verify Python ---------------------------------------------
Write-Section "Step 1/8 — Python"
$PythonExe = $null
$pyCmd = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pyCmd) { $PythonExe = $pyCmd.Source }
if (-not $PythonExe) {
    # Fall back to the launcher if python.exe isn't directly on PATH.
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) { $PythonExe = $pyLauncher.Source }
}
if (-not $PythonExe) {
    Write-Bad "Could not find python.exe on PATH."
    Write-Host ""
    Write-Host "  Install Python 3.9+ (3.11+ recommended), and during the installer" -ForegroundColor Yellow
    Write-Host "  CHECK the box 'Add python.exe to PATH'. Download it here:" -ForegroundColor Yellow
    Write-Host "      https://www.python.org/downloads/windows/" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Then re-run this wizard." -ForegroundColor Yellow
    exit 1
}
# Verify it actually runs and is new enough.
$pyVer = & $PythonExe -c "import sys; print('%d.%d.%d' % sys.version_info[:3])" 2>$null
if ($LASTEXITCODE -ne 0 -or -not $pyVer) {
    Write-Bad "Found '$PythonExe' but it did not run. Reinstall Python from:"
    Write-Host "      https://www.python.org/downloads/windows/" -ForegroundColor Cyan
    exit 1
}
$verOk = & $PythonExe -c "import sys; sys.exit(0 if sys.version_info >= (3,9) else 1)" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Bad "Python $pyVer is too old. Install 3.9+ (3.11+ recommended):"
    Write-Host "      https://www.python.org/downloads/windows/" -ForegroundColor Cyan
    exit 1
}
Write-Good "Python $pyVer  ($PythonExe)"

# ---- (b) Install client dependencies --------------------------------------
Write-Section "Step 2/8 — Dependencies"
if (-not (Test-Path $ReqPath)) {
    Write-Bad "requirements.txt not found next to this script ($ReqPath)."
    exit 1
}
Write-Step "pip install -r requirements.txt"
& $PythonExe -m pip install -r $ReqPath
if ($LASTEXITCODE -ne 0) {
    Write-Bad "pip install failed (exit $LASTEXITCODE). Fix the error above and re-run."
    exit 1
}
Write-Good "Dependencies installed."

# ---- (c) Doctor self-check ------------------------------------------------
Write-Section "Step 3/8 — Environment self-check (doctor)"
Write-Step "python streamdeck_daemon.py doctor --role pc --json"
$docRaw = & $PythonExe $DaemonPath doctor --role pc --json 2>$null
$docExit = $LASTEXITCODE
$doc = $null
try { $doc = $docRaw | ConvertFrom-Json } catch { $doc = $null }
if ($doc -and $doc.checks) {
    foreach ($c in $doc.checks) {
        switch ($c.status) {
            "ok"   { Write-Good ("{0}: {1}" -f $c.name, $c.detail) }
            "warn" { Write-Warn2 ("{0}: {1}" -f $c.name, $c.detail)
                     if ($c.fix) { Write-Host "          -> $($c.fix)" -ForegroundColor DarkYellow } }
            "fail" { Write-Bad ("{0}: {1}" -f $c.name, $c.detail)
                     if ($c.fix) { Write-Host "          -> $($c.fix)" -ForegroundColor DarkYellow } }
            default { Write-Host "   [$($c.status)] $($c.name): $($c.detail)" }
        }
    }
    if ($doc.ok) {
        Write-Good "Doctor: no hard failures."
    } else {
        # Don't hard-fail: many of the fail items (no key/mic yet) are exactly what
        # this wizard is about to fix. Just warn and keep going.
        Write-Warn2 "Doctor reported failures above — the wizard will help fix the key/mic ones next."
    }
} else {
    Write-Warn2 "Could not parse doctor JSON (exit $docExit). Continuing anyway."
    if ($docRaw) { Write-Host $docRaw -ForegroundColor DarkGray }
}

# ---- (d) Microphone selection + live level test ---------------------------
Write-Section "Step 4/8 — Microphone"
$ChosenDeviceName = ""
if ($NonInteractive) {
    Write-Warn2 "Non-interactive: keeping the microphone already saved in config (if any)."
    Write-Host "   (change it later with: python streamdeck_daemon.py setup --device-name `"NAME`")" -ForegroundColor DarkGray
} else {
    Write-Step "Available input devices:"
    & $PythonExe $DaemonPath devices
    Write-Host ""
    Write-Host "  Pick your mic by a piece of its NAME (recommended — names survive reboots;" -ForegroundColor Gray
    Write-Host "  indices change). For example, type  G06  to match 'Microphone (G06 ...)'." -ForegroundColor Gray

    $micConfirmed = $false
    while (-not $micConfirmed) {
        $name = Read-Host "  Mic name substring (Enter to re-list, blank twice to skip)"
        if (-not $name) {
            $again = Read-Host "  Skip mic selection and use the system default? (y/N)"
            if ($again -match '^(y|yes)$') {
                Write-Warn2 "Skipping mic pin — daemon will use the system default input."
                break
            }
            Write-Step "Available input devices:"
            & $PythonExe $DaemonPath devices
            continue
        }
        Write-Step "Testing mic matching `"$name`" (speak for ~4 seconds when prompted)..."
        & $PythonExe $DaemonPath mictest --device-name "$name"
        $testExit = $LASTEXITCODE
        Write-Host ""
        $ans = Read-Host "  Keep this mic? (y = yes / r = retry test / n = pick a different name)"
        switch -Regex ($ans) {
            '^(y|yes)$' { $ChosenDeviceName = $name; $micConfirmed = $true; Write-Good "Using mic name `"$name`"." }
            '^(r)$'     { }  # loop and re-test the same name
            default     {
                # Re-test the same name unless they want a different one.
                $diff = Read-Host "  Type a new name substring, or Enter to re-test `"$name`""
                if ($diff) { $name = $diff }
                Write-Step "Testing mic matching `"$name`"..."
                & $PythonExe $DaemonPath mictest --device-name "$name"
                $ans2 = Read-Host "  Keep this mic? (y/N)"
                if ($ans2 -match '^(y|yes)$') { $ChosenDeviceName = $name; $micConfirmed = $true; Write-Good "Using mic name `"$name`"." }
            }
        }
    }
}

# ---- (e) Groq API key -----------------------------------------------------
Write-Section "Step 5/8 — Groq API key"
# Detect an existing saved key (setup --show masks it but prints groq_key if set).
$HasSavedKey = $false
$showOut = & $PythonExe $DaemonPath setup --show 2>$null
if ($showOut -match '"groq_key"') { $HasSavedKey = $true }
if (-not $HasSavedKey -and $env:GROQ_API_KEY) { $HasSavedKey = $true }

$EffectiveKey = $GroqKey
if (-not $EffectiveKey -and -not $NonInteractive) {
    if ($HasSavedKey) {
        Write-Good "A Groq key is already saved. Press Enter to keep it."
        $entered = Read-Host "  Groq API key (gsk_...) [Enter = keep existing]"
        if ($entered) { $EffectiveKey = $entered }
    } else {
        Write-Host "  Get a free key at https://console.groq.com/keys" -ForegroundColor Gray
        while (-not $EffectiveKey) {
            $entered = Read-Host "  Groq API key (gsk_...)"
            if ($entered) { $EffectiveKey = $entered }
            else { Write-Warn2 "A Groq key is required for transcription." }
        }
    }
}
if ($EffectiveKey) {
    Write-Good "Groq key captured (will be saved to config)."
} elseif ($HasSavedKey) {
    Write-Good "Keeping the existing saved Groq key."
} else {
    Write-Warn2 "No Groq key provided or saved — transcription will fail until you set one:"
    Write-Host "      python streamdeck_daemon.py setup --groq-key gsk_..." -ForegroundColor DarkYellow
}

# ---- (f) Optional AI5090 remote-paste target ------------------------------
Write-Section "Step 6/8 — AI5090 remote target (optional)"
$EffectiveRemote = $RemotePaste
if (-not $EffectiveRemote -and -not $NonInteractive) {
    Write-Host "  If you dictate onto a second machine (the AI5090) via a paste helper," -ForegroundColor Gray
    Write-Host "  enter its HOST:PORT here to enable the second Stream Deck button." -ForegroundColor Gray
    Write-Host "  Leave blank to skip (you can add it later)." -ForegroundColor Gray
    $entered = Read-Host "  AI5090 remote-paste target (HOST:9879) [Enter = skip]"
    if ($entered) { $EffectiveRemote = $entered }
}
if ($EffectiveRemote) {
    if ($EffectiveRemote -notmatch ':') { $EffectiveRemote = "${EffectiveRemote}:9879" }
    Write-Good "Remote target: $EffectiveRemote"
} else {
    Write-Warn2 "No remote target — the second button (toggle-remote) stays inactive until set."
}

# ---- (g) Save config + register the daemon service ------------------------
Write-Section "Step 7/8 — Save config and register the daemon"

# Save key / mic / remote via the daemon's own setup so resolution stays identical.
$setupArgs = @($DaemonPath, "setup", "--backend", "groq")
if ($EffectiveKey)       { $setupArgs += @("--groq-key", $EffectiveKey) }
if ($ChosenDeviceName)   { $setupArgs += @("--device-name", $ChosenDeviceName) }
if ($EffectiveRemote)    { $setupArgs += @("--remote-paste", $EffectiveRemote) }
if ($setupArgs.Count -gt 4) {
    Write-Step "Saving config (python streamdeck_daemon.py setup ...)"
    & $PythonExe @setupArgs
    if ($LASTEXITCODE -ne 0) { Write-Bad "Failed to save config (setup exited $LASTEXITCODE)."; exit 1 }
    Write-Good "Config saved to $ConfigFile"
} else {
    Write-Warn2 "Nothing new to save — keeping the existing config."
}

# Register (or refresh) the background daemon as a Scheduled Task. We pass the
# key/remote through too so a first-ever install populates config even if the
# steps above had nothing new; -Device is intentionally omitted because we pin
# the mic by NAME (more robust than a churning index).
if (-not (Test-Path $InstallPs1)) {
    Write-Bad "install-streamdeck-service.ps1 not found ($InstallPs1)."
    exit 1
}
Write-Step "Registering the daemon service (install-streamdeck-service.ps1)"
# Run it in a child PowerShell so a throw/exit inside it can't abort this wizard.
# Build an explicit argument ARRAY (array splatting to a native exe is well
# defined; hashtable splatting to powershell.exe is not).
$installArgs = @("-ExecutionPolicy", "Bypass", "-File", $InstallPs1)
if ($EffectiveKey)    { $installArgs += @("-GroqKey", $EffectiveKey) }
if ($EffectiveRemote) { $installArgs += @("-RemotePaste", $EffectiveRemote) }
& powershell.exe @installArgs
if ($LASTEXITCODE -ne 0) {
    Write-Bad "Service registration failed (exit $LASTEXITCODE). See the error above."
    exit 1
}
Write-Good "Daemon registered and started."

# ---- (h) Re-run doctor + final Stream Deck instructions -------------------
Write-Section "Step 8/8 — Verify"
Write-Step "Re-running doctor to confirm..."
& $PythonExe $DaemonPath doctor --role pc
# doctor exits non-zero on FAIL; report but don't abort — config is already saved.
if ($LASTEXITCODE -ne 0) {
    Write-Warn2 "Doctor still reports issues above. Setup is saved; fix the marked items and re-run doctor."
} else {
    Write-Good "All doctor checks passed."
}

Write-Section "Done — set up your two Stream Deck buttons"
Write-Host "  In the Stream Deck app, add a 'System > Open' action per button and set" -ForegroundColor White
Write-Host "  App/File to the FULL PATH below (the Open action can't take arguments," -ForegroundColor White
Write-Host "  so point it at the .vbs launcher, not at streamdeck_daemon.py):" -ForegroundColor White
Write-Host ""
Write-Host "  Button 1  — dictate on THIS PC (local):" -ForegroundColor Cyan
Write-Host "      $TogglePc" -ForegroundColor Green
Write-Host ""
Write-Host "  Button 2  — dictate on the AI5090 (remote):" -ForegroundColor Cyan
Write-Host "      $ToggleRemote" -ForegroundColor Green
if (-not $EffectiveRemote) {
    Write-Host "      (set a remote target first to make button 2 work:" -ForegroundColor DarkYellow
    Write-Host "       python streamdeck_daemon.py setup --remote-paste HOST:9879)" -ForegroundColor DarkYellow
}
Write-Host ""
Write-Host "  Config lives at: $ConfigFile" -ForegroundColor Gray
Write-Host "  Change a setting later without reinstalling, e.g.:" -ForegroundColor Gray
Write-Host "      python streamdeck_daemon.py setup --device-name `"NAME`"" -ForegroundColor Gray
Write-Host "      python streamdeck_daemon.py setup --show" -ForegroundColor Gray
Write-Host ""
Write-Good "TalkFlow setup complete."
