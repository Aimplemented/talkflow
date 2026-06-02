@echo off
title TalkFlow Installer
echo.
echo  ========================================
echo       TalkFlow - Windows Installer
echo  ========================================
echo.

set "TF_DIR=%USERPROFILE%\TalkFlow"
if defined TALKFLOW_SERVER (
    set "SERVER=%TALKFLOW_SERVER%"
) else (
    set "SERVER=YOUR_SERVER:9876"
)

:: 1. Check Python
echo [1/5] Checking Python...
python --version >nul 2>&1
if errorlevel 1 (
    echo   ERROR: Python not found!
    echo   Download: https://www.python.org/downloads/
    echo   CHECK "Add python.exe to PATH" during install!
    pause
    exit /b 1
)
python --version
echo   OK
echo.

:: 2. Create directories
echo [2/5] Creating %TF_DIR% ...
if not exist "%TF_DIR%\client" mkdir "%TF_DIR%\client"
echo   OK
echo.

:: 3. Copy files (all client modules so new files are picked up automatically)
echo [3/5] Copying files...
set "SRC=%~dp0client"
if not exist "%SRC%" (
    echo   ERROR: 'client' folder not found next to this installer.
    pause
    exit /b 1
)
copy /y "%SRC%\*.py" "%TF_DIR%\client\" >nul
if exist "%SRC%\requirements.txt" copy /y "%SRC%\requirements.txt" "%TF_DIR%\client\" >nul
if exist "%SRC%\assets" (
    if not exist "%TF_DIR%\client\assets" mkdir "%TF_DIR%\client\assets"
    xcopy /y /q "%SRC%\assets\*" "%TF_DIR%\client\assets\" >nul 2>&1
    echo   assets copied
)
if not exist "%TF_DIR%\client\clipboard_injector.py" (
    echo   ERROR: clipboard_injector.py missing - source tree is incomplete.
    pause
    exit /b 1
)
echo   OK
echo.

:: 4. Create venv and install deps from requirements.txt
echo [4/5] Installing dependencies (this may take a minute)...
python -m venv "%TF_DIR%\client\.venv"
call "%TF_DIR%\client\.venv\Scripts\activate.bat"
pip install --quiet --upgrade pip
if exist "%TF_DIR%\client\requirements.txt" (
    pip install --quiet -r "%TF_DIR%\client\requirements.txt"
) else (
    pip install --quiet "websockets>=13.0" "pynput>=1.7.6" "sounddevice>=0.4.6" "numpy>=1.26" "pyperclip>=1.8.2" "pystray>=0.19" "Pillow>=10.0"
)
echo   OK
echo.

:: 5. Create launcher and config
echo [5/5] Creating launcher...

:: Default config (DeskFlow paste delivery by default)
if not exist "%TF_DIR%\client\config.json" (
    >"%TF_DIR%\client\config.json" echo {"backend":"groq","groq_api_key":"","server":"%SERVER%","hotkey":"f9","mic_device":null,"mic_device_name":"System Default","delivery_mode":"deskflow_paste","paste_sync_delay_ms":250,"paste_restore_delay_ms":700,"minimize_to_tray":true,"play_sounds":true,"auto_start_on_launch":false}
    echo   config.json ^(delivery_mode = deskflow_paste^)
)

:: GUI launcher
(
echo @echo off
echo call "%TF_DIR%\client\.venv\Scripts\activate.bat"
echo cd /d "%TF_DIR%\client"
echo pythonw gui.py
) > "%TF_DIR%\TalkFlow.bat"

:: Desktop shortcut via VBScript
echo Set ws = CreateObject("WScript.Shell") > "%TEMP%\talkflow_shortcut.vbs"
echo Set sc = ws.CreateShortcut(ws.SpecialFolders("Desktop") ^& "\TalkFlow.lnk") >> "%TEMP%\talkflow_shortcut.vbs"
echo sc.TargetPath = "%TF_DIR%\TalkFlow.bat" >> "%TEMP%\talkflow_shortcut.vbs"
echo sc.WorkingDirectory = "%TF_DIR%" >> "%TEMP%\talkflow_shortcut.vbs"
echo sc.Description = "TalkFlow - Push-to-Talk Voice Dictation" >> "%TEMP%\talkflow_shortcut.vbs"
echo sc.Save >> "%TEMP%\talkflow_shortcut.vbs"
cscript //nologo "%TEMP%\talkflow_shortcut.vbs"
del "%TEMP%\talkflow_shortcut.vbs"

echo   OK
echo.
echo  ========================================
echo       Installation Complete!
echo  ========================================
echo.
echo   Double-click TalkFlow on your Desktop
echo.
echo   Delivery is set to "DeskFlow" - text pastes to whichever
echo   screen your cursor is on. Hold F9, speak, release.
echo.
echo   Run TalkFlow only on this machine (the DeskFlow primary),
echo   keep DeskFlow clipboard sharing ON, and for a Mac client
echo   enable DeskFlow's Cmd/Ctrl mapping for that screen.
echo.
pause
