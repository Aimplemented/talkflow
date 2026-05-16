"""
OS-standard paths for TalkFlow config + logs.

Windows: %APPDATA%\\TalkFlow
macOS:   ~/Library/Application Support/TalkFlow
Linux:   $XDG_CONFIG_HOME/talkflow  (or ~/.config/talkflow)

We also auto-migrate config.json out of the install directory on first run
so installed copies (PyInstaller/.app/.exe) don't try to write next to the
read-only binary.
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path

APP_NAME = "TalkFlow"


def app_data_dir() -> Path:
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        d = Path(base) / APP_NAME
    elif system == "Darwin":
        d = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
        d = Path(base) / APP_NAME.lower()
    d.mkdir(parents=True, exist_ok=True)
    return d


def log_dir() -> Path:
    system = platform.system()
    if system == "Darwin":
        d = Path.home() / "Library" / "Logs" / APP_NAME
    elif system == "Windows":
        d = app_data_dir() / "logs"
    else:
        base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
        d = Path(base) / APP_NAME.lower() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def config_path() -> Path:
    return app_data_dir() / "config.json"


def log_path() -> Path:
    return log_dir() / "talkflow.log"


def migrate_legacy_config_if_needed(script_dir: Path) -> None:
    """Move config.json from the install dir to the user app-data dir.

    Older builds stored config next to the script. After install, that
    location is read-only (and is wiped on upgrade), so move it.
    """
    target = config_path()
    if target.exists():
        return
    for name in ("config.json", "talkflow_config.json"):
        legacy = script_dir / name
        if legacy.exists() and legacy.is_file():
            try:
                shutil.copy2(legacy, target)
                return
            except Exception:
                pass
