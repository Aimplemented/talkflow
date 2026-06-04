"""
TalkFlow — Doctor (environment detection & self-check)
======================================================
One command that runs every probe this project needs and prints a ✓/⚠/✗ report
with a concrete fix for anything that's wrong.  It exists because every hard bug
in TalkFlow's bring-up was a missing detection: wrong/silent mic, churning audio
indices, a display-less (tty) shell, X11-vs-Wayland, a missing ydotoold, a
firewall blocking the helper port.  Doctor checks all of them up front.

Usage
-----
    python doctor.py                 # auto-detect role from the OS
    python doctor.py --role pc       # the PC (mic host) checks
    python doctor.py --role remote   # the AI5090 (paste helper) checks
    python doctor.py --role server   # the self-hosted STT server checks
    python doctor.py --mic-level     # also record a few seconds and meter the mic
    python doctor.py --json          # machine-readable output (for installers)

Exit code is 0 if nothing FAILed (warnings are allowed), else 1.  Installers can
call this to gate setup, and `streamdeck_daemon.py doctor` re-exports it.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import socket
import subprocess
import sys

# Status levels
OK = "ok"
WARN = "warn"
FAIL = "fail"

_MARK = {OK: "✓", WARN: "⚠", FAIL: "✗"}


class Check:
    """One diagnostic result."""

    __slots__ = ("name", "status", "detail", "fix")

    def __init__(self, name: str, status: str, detail: str = "", fix: str = ""):
        self.name = name
        self.status = status
        self.detail = detail
        self.fix = fix

    def as_dict(self) -> dict:
        return {"name": self.name, "status": self.status,
                "detail": self.detail, "fix": self.fix}


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------
def check_python() -> Check:
    v = sys.version_info
    if v < (3, 9):
        return Check("Python", FAIL, f"{platform.python_version()} is too old",
                     "Install Python 3.9+ (3.11+ recommended).")
    return Check("Python", OK, platform.python_version())


def check_python_deps(role: str) -> list[Check]:
    """Import-check the packages the given role needs."""
    needed = {
        "pc": [("sounddevice", "sounddevice>=0.4.6"),
               ("numpy", "numpy>=1.24.0"),
               ("pyperclip", "pyperclip>=1.8.2")],
        "remote": [],   # the helper needs only stdlib + an injection tool
        "server": [("faster_whisper", "faster-whisper>=1.1.0"),
                   ("fastapi", "fastapi>=0.115.0"),
                   ("uvicorn", "uvicorn[standard]>=0.34.0"),
                   ("websockets", "websockets>=13.0")],
    }.get(role, [])
    out: list[Check] = []
    for mod, pip_name in needed:
        try:
            __import__(mod)
            out.append(Check(f"dep: {mod}", OK))
        except Exception:
            out.append(Check(f"dep: {mod}", FAIL, "not importable",
                             f"pip install {pip_name}"))
    return out


def _load_daemon_config() -> dict:
    try:
        import streamdeck_daemon as sd
        return sd.load_config()
    except Exception:
        return {}


def check_groq_key(ping: bool = False) -> Check:
    cfg = _load_daemon_config()
    key = cfg.get("groq_key") or os.getenv("GROQ_API_KEY", "")
    if not key:
        return Check("Groq key", FAIL, "not configured",
                     "python streamdeck_daemon.py setup --groq-key gsk_...")
    if not ping:
        masked = key[:6] + "…" + key[-4:] if len(key) > 12 else "set"
        return Check("Groq key", OK, masked)
    # Optional live validation against the models endpoint.
    try:
        import urllib.request
        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/models",
            headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            if r.status == 200:
                return Check("Groq key", OK, "validated against Groq API")
        return Check("Groq key", WARN, f"unexpected status {r.status}")
    except Exception as exc:
        return Check("Groq key", WARN, f"could not validate: {exc}",
                     "Check the key and network; key may still be fine.")


def check_microphone(measure_level: bool = False) -> list[Check]:
    out: list[Check] = []
    try:
        import sounddevice as sd
    except Exception:
        out.append(Check("Microphone", FAIL, "sounddevice not installed",
                         "pip install sounddevice numpy"))
        return out

    cfg = _load_daemon_config()
    name = cfg.get("device_name", "")
    index = cfg.get("device")
    inputs = [(i, d) for i, d in enumerate(sd.query_devices())
              if d.get("max_input_channels", 0) >= 1]
    if not inputs:
        out.append(Check("Microphone", FAIL, "no input devices found",
                         "Plug in a mic / check OS sound settings."))
        return out
    out.append(Check("Mic devices", OK, f"{len(inputs)} input device(s) available"))

    # Resolve the configured mic the same way the daemon does.
    try:
        import streamdeck_daemon as sd_mod
        resolved = sd_mod._resolve_input_device(index, name)
        chosen = sd_mod._device_name(resolved)
    except Exception:
        resolved, chosen = index, str(index)

    if not name and index is None:
        out.append(Check("Mic selection", WARN, "using system default",
                         'Pin a mic by name: setup --device-name "G06"'))
    else:
        sel = name and f'name "{name}"' or f"index {index}"
        out.append(Check("Mic selection", OK, f"{sel} → {chosen}"))

    if measure_level:
        try:
            import streamdeck_daemon as sd_mod
            from audio_capture import AudioCapture
            import time as _t
            cap = AudioCapture(device=resolved)
            print("   …recording 3s for a level check — SPEAK NOW")
            cap.start(); _t.sleep(3); pcm = cap.stop()
            pct = sd_mod._pcm_peak(pcm) * 100 // 32767
            if pct < 2:
                out.append(Check("Mic level", FAIL, f"peak {pct}% (silent)",
                                 "Wrong/muted mic. Run: streamdeck_daemon.py devices "
                                 "then setup --device-name <name>"))
            elif pct < 10:
                out.append(Check("Mic level", WARN, f"peak {pct}% (quiet)",
                                 "Raise mic gain or move closer."))
            else:
                out.append(Check("Mic level", OK, f"peak {pct}%"))
        except Exception as exc:
            out.append(Check("Mic level", WARN, f"could not measure: {exc}"))
    return out


def detect_session() -> tuple[str, str]:
    """Return (session_type, compositor) for a Linux box."""
    session = os.environ.get("XDG_SESSION_TYPE", "").lower()
    # In a tty/SSH shell XDG_SESSION_TYPE is "tty"/empty; ask logind for the
    # active graphical session instead.
    if session in ("", "tty"):
        try:
            out = subprocess.run(["loginctl", "list-sessions", "--no-legend"],
                                 capture_output=True, text=True, timeout=5).stdout
            for line in out.splitlines():
                sid = line.split()[0] if line.split() else ""
                if not sid:
                    continue
                t = subprocess.run(["loginctl", "show-session", sid, "-p", "Type",
                                    "-p", "Active"], capture_output=True, text=True,
                                   timeout=5).stdout
                if "Active=yes" in t:
                    for ln in t.splitlines():
                        if ln.startswith("Type="):
                            session = ln.split("=", 1)[1].strip().lower() or session
        except Exception:
            pass
    compositor = ""
    try:
        procs = subprocess.run(["ps", "-e", "-o", "comm="],
                               capture_output=True, text=True, timeout=5).stdout
        for c in ("gnome-shell", "kwin_wayland", "kwin_x11", "sway", "weston",
                  "hyprland", "labwc", "mutter"):
            if c in procs:
                compositor = c
                break
    except Exception:
        pass
    return session or "unknown", compositor or "unknown"


def check_injection(role: str) -> list[Check]:
    """Remote-side: can we type into the desktop?"""
    if platform.system() != "Linux":
        return []
    out: list[Check] = []
    session, compositor = detect_session()
    out.append(Check("Graphical session", OK if session in ("x11", "wayland") else WARN,
                     f"type={session} compositor={compositor}",
                     "" if session in ("x11", "wayland")
                     else "Run the helper anyway — ydotool injects at the kernel "
                          "level and doesn't need this shell to have a display."))
    # Which injection tool will the helper pick?
    try:
        import paste_helper
        tool = paste_helper._injection_tool()
    except Exception:
        tool = "ydotool" if shutil.which("ydotool") else (
            "xdotool" if shutil.which("xdotool") else None)
    if tool is None:
        out.append(Check("Injection tool", FAIL, "none installed",
                         "Build ydotool 1.x (recommended for Wayland) or "
                         "apt install xdotool (X11)."))
        return out
    out.append(Check("Injection tool", OK, tool))

    if tool == "ydotool":
        # ydotoold socket reachable?
        sock = os.environ.get("YDOTOOL_SOCKET") or "/run/ydotoold.socket"
        if os.path.exists(sock):
            out.append(Check("ydotoold", OK, f"socket {sock}"))
        else:
            out.append(Check("ydotoold", FAIL, f"socket {sock} missing",
                             "Start it: install-ai5090-helper.sh (or "
                             "ydotoold --socket-path=/run/ydotoold.socket --socket-perm=0666)"))
        if shutil.which("ydotoold") is None:
            out.append(Check("ydotoold binary", WARN, "not on PATH",
                             "Build ydotool 1.x so ydotoold exists."))
    elif compositor in ("gnome-shell", "mutter", "kwin_wayland") and tool == "wtype":
        out.append(Check("Injection tool", WARN, "wtype on GNOME/KDE may not work",
                         "Prefer ydotool on GNOME/KDE Wayland."))
    return out


def check_helper_listening(port: int = 9879) -> Check:
    """Remote-side: is the paste helper accepting connections locally?"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=2):
            return Check("Paste helper", OK, f"listening on :{port}")
    except Exception:
        return Check("Paste helper", WARN, f"not answering on :{port}",
                     "Start it: systemctl --user start talkflow-paste-helper "
                     "(or python3 paste_helper.py)")


def check_remote_reachable() -> Check | None:
    """PC-side: can we reach the AI5090 helper named in config?"""
    cfg = _load_daemon_config()
    target = cfg.get("remote_paste", "")
    if not target:
        return Check("AI5090 target", WARN, "not configured",
                     "Set it to enable the second button: "
                     "setup --remote-paste HOST:9879")
    host, _, port_s = target.partition(":")
    port = int(port_s) if port_s.isdigit() else 9879
    try:
        with socket.create_connection((host, port), timeout=3):
            return Check("AI5090 reachable", OK, f"{host}:{port}")
    except Exception as exc:
        return Check("AI5090 reachable", FAIL, f"{host}:{port} — {exc}",
                     "Is the helper running and the port open? On the AI5090: "
                     "sudo ufw allow 9879/tcp (if ufw is active).")


def check_gpu() -> Check:
    """Server-side: is an NVIDIA GPU available for faster-whisper (CUDA)?"""
    if shutil.which("nvidia-smi") is None:
        return Check("GPU/CUDA", WARN, "no GPU — server will run on CPU, slower",
                     "For best speed install an NVIDIA GPU + driver, then run the "
                     "server with WHISPER_DEVICE=cuda. CPU works with "
                     "WHISPER_DEVICE=cpu WHISPER_COMPUTE=int8.")
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=8)
        name = (out.stdout.strip().splitlines() or [""])[0].strip()
        if out.returncode == 0 and name:
            return Check("GPU/CUDA", OK, name)
        return Check("GPU/CUDA", WARN, "no GPU — server will run on CPU, slower",
                     "nvidia-smi ran but reported no GPU. CPU works with "
                     "WHISPER_DEVICE=cpu WHISPER_COMPUTE=int8.")
    except Exception as exc:
        return Check("GPU/CUDA", WARN,
                     f"no GPU — server will run on CPU, slower ({exc})",
                     "CPU works with WHISPER_DEVICE=cpu WHISPER_COMPUTE=int8.")


def check_deskflow() -> Check:
    name = {"Windows": "deskflow", "Darwin": "deskflow"}.get(platform.system(), "deskflow")
    found = False
    try:
        if platform.system() == "Windows":
            out = subprocess.run(["tasklist"], capture_output=True, text=True,
                                 timeout=5).stdout.lower()
            found = "deskflow" in out or "synergy" in out
        else:
            out = subprocess.run(["ps", "-e", "-o", "comm="], capture_output=True,
                                 text=True, timeout=5).stdout.lower()
            found = "deskflow" in out or "synergy" in out
    except Exception:
        pass
    if found:
        return Check("DeskFlow", OK, "running")
    return Check("DeskFlow", WARN, "not detected",
                 "Start DeskFlow/Synergy so dictation can reach the other screen.")


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def detect_role() -> str:
    return "remote" if platform.system() == "Linux" else "pc"


def run_checks(role: str, mic_level: bool = False, ping_key: bool = False) -> list[Check]:
    checks: list[Check] = [check_python()]
    checks += check_python_deps(role)
    if role == "pc":
        checks.append(check_groq_key(ping=ping_key))
        checks += check_microphone(measure_level=mic_level)
        checks.append(check_deskflow())
        r = check_remote_reachable()
        if r:
            checks.append(r)
    elif role == "remote":
        checks += check_injection(role)
        checks.append(check_helper_listening())
    elif role == "server":
        checks.append(check_gpu())
        checks.append(check_groq_key(ping=ping_key))
    return checks


def print_report(role: str, checks: list[Check]) -> int:
    print(f"\n  TalkFlow doctor — role: {role}\n  {'-' * 46}")
    worst_fail = False
    for c in checks:
        mark = _MARK.get(c.status, "?")
        line = f"  {mark}  {c.name}"
        if c.detail:
            line += f": {c.detail}"
        print(line)
        if c.status != OK and c.fix:
            print(f"        → {c.fix}")
        if c.status == FAIL:
            worst_fail = True
    fails = sum(1 for c in checks if c.status == FAIL)
    warns = sum(1 for c in checks if c.status == WARN)
    print(f"  {'-' * 46}")
    if worst_fail:
        print(f"  {fails} problem(s), {warns} warning(s) — fix the ✗ items above.\n")
    elif warns:
        print(f"  OK with {warns} warning(s).\n")
    else:
        print("  All checks passed. ✓\n")
    return 1 if worst_fail else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="TalkFlow environment self-check.")
    p.add_argument("--role", choices=["pc", "remote", "server", "auto"], default="auto")
    p.add_argument("--mic-level", action="store_true",
                   help="Record a few seconds and meter the mic (pc role)")
    p.add_argument("--ping-key", action="store_true",
                   help="Validate the Groq key against the API")
    p.add_argument("--json", action="store_true", help="Machine-readable output")
    args = p.parse_args(argv)

    role = detect_role() if args.role == "auto" else args.role
    checks = run_checks(role, mic_level=args.mic_level, ping_key=args.ping_key)

    if args.json:
        fails = sum(1 for c in checks if c.status == FAIL)
        print(json.dumps({"role": role, "ok": fails == 0,
                          "checks": [c.as_dict() for c in checks]}, indent=2))
        return 1 if fails else 0
    return print_report(role, checks)


if __name__ == "__main__":
    sys.exit(main())
