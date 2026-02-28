@echo off
title TalkFlow Installer
echo.
echo  ========================================
echo       TalkFlow - Windows Installer
echo  ========================================
echo.

set "TF_DIR=%USERPROFILE%\TalkFlow"
set "SERVER=YOUR_SERVER:9876"

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

:: 3. Copy files
echo [3/5] Copying files...
set "SRC=%~dp0client"
for %%f in (client.py audio_capture.py hotkey_listener.py keystroke_injector.py gui.py) do (
    if exist "%SRC%\%%f" (
        copy /y "%SRC%\%%f" "%TF_DIR%\client\%%f" >nul
        echo   %%f
    ) else (
        echo   MISSING: %%f
        echo   Make sure 'client' folder is next to this installer.
        pause
        exit /b 1
    )
)
echo   OK
echo.

:: 4. Create venv and install deps
echo [4/5] Installing dependencies (this may take a minute)...
python -m venv "%TF_DIR%\client\.venv"
call "%TF_DIR%\client\.venv\Scripts\activate.bat"
pip install --quiet --upgrade pip
pip install --quiet "websockets>=13.0" "pynput>=1.7.6" "sounddevice>=0.4.6" "numpy>=1.26"
echo   OK
echo.

:: 5. Create launcher and config
echo [5/5] Creating launcher...

:: Default config
if not exist "%TF_DIR%\client\talkflow_config.json" (
    echo {"server":"%SERVER%","hotkey":"f9","mic_device":null,"mic_device_name":"System Default"} > "%TF_DIR%\client\talkflow_config.json"
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
echo   Hold F9 to talk, release to transcribe.
echo   Text appears wherever your cursor is.
echo.
pause
