#!/usr/bin/env python3
"""
TalkFlow Cross-Platform Installer Build Script
==============================================
Bundles the TalkFlow client into a standalone executable for the current OS.

Usage:
    python build_installer.py                  # Build for current OS
    python build_installer.py --clean          # Clean build artifacts first
    python build_installer.py --debug          # Console window for debugging
    python build_installer.py --dmg            # macOS: also build a .dmg
    python build_installer.py --target macos   # Force a target (auto-detected by default)

Requirements:
    pip install pyinstaller pillow cairosvg

Output:
    Windows:  dist/TalkFlow.exe              (feed into installer.iss with Inno Setup)
    macOS:    dist/TalkFlow.app              (+ dist/TalkFlow-{version}.dmg with --dmg)
    Linux:    dist/TalkFlow                  (one-file executable)
"""

from __future__ import annotations

import argparse
import os
import platform
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

APP_NAME = "TalkFlow"
APP_VERSION = "1.0.0"
APP_BUNDLE_ID = "com.aiimplemented.talkflow"
MAIN_SCRIPT = "gui.py"
ICON_SVG = "assets/logo.svg"
ICON_ICO = "assets/logo.ico"
ICON_ICNS = "assets/logo.icns"

HIDDEN_IMPORTS_COMMON = [
    "sounddevice",
    "numpy",
    "PIL._tkinter_finder",
]
HIDDEN_IMPORTS_PER_OS = {
    "Windows": [
        "pynput.keyboard._win32",
        "pynput.mouse._win32",
        "pystray._win32",
    ],
    "Darwin": [
        "pynput.keyboard._darwin",
        "pynput.mouse._darwin",
        "pystray._darwin",
        "Quartz",
        "AppKit",
    ],
    "Linux": [
        "pynput.keyboard._xorg",
        "pynput.mouse._xorg",
        "pystray._xorg",
    ],
}

DATA_FILES = [("assets", "assets")]


def log(msg: str, level: str = "INFO") -> None:
    colors = {"INFO": "\033[94m", "SUCCESS": "\033[92m",
              "WARNING": "\033[93m", "ERROR": "\033[91m"}
    print(f"{colors.get(level, '')}[{level}]\033[0m {msg}")


def normalize_target(t: str | None) -> str:
    if t:
        m = {"win": "Windows", "windows": "Windows",
             "mac": "Darwin", "macos": "Darwin", "darwin": "Darwin",
             "linux": "Linux"}
        return m.get(t.lower(), t)
    return platform.system()


def check_dependencies() -> bool:
    log("Checking build dependencies...")
    missing = []
    try:
        import PyInstaller
        log(f"  PyInstaller: {PyInstaller.__version__}")
    except ImportError:
        missing.append("pyinstaller")
    try:
        import PIL
        log(f"  Pillow: {PIL.__version__}")
    except ImportError:
        missing.append("pillow")
    if missing:
        log(f"Missing: {', '.join(missing)} — install with: pip install {' '.join(missing)}", "ERROR")
        return False
    return True


def _render_svg_to_png_bytes(svg_path: Path, size: int) -> bytes:
    import cairosvg
    return cairosvg.svg2png(url=str(svg_path), output_width=size, output_height=size)


def _fallback_png_image(size: int):
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = size // 8
    draw.ellipse([margin, margin, size - margin, size - margin], fill=(8, 145, 178, 255))
    c = size // 4
    draw.ellipse([c, c, size - c, size - c], fill=(255, 255, 255, 230))
    return img


def convert_svg_to_ico(svg_path: Path, ico_path: Path) -> bool:
    """Multi-resolution .ico for Windows."""
    log(f"Generating {ico_path.name}...")
    try:
        from PIL import Image
        import io
        sizes = [16, 32, 48, 64, 128, 256]
        images = []
        try:
            for s in sizes:
                images.append(Image.open(io.BytesIO(_render_svg_to_png_bytes(svg_path, s))).convert("RGBA"))
        except ImportError:
            log("  cairosvg missing, using fallback icon", "WARNING")
            images = [_fallback_png_image(s) for s in sizes]
        images[0].save(ico_path, format="ICO",
                       sizes=[(s, s) for s in sizes],
                       append_images=images[1:])
        log(f"  Wrote {ico_path}", "SUCCESS")
        return True
    except Exception as e:
        log(f"Icon conversion failed: {e}", "ERROR")
        return False


def convert_svg_to_icns(svg_path: Path, icns_path: Path) -> bool:
    """Generate macOS .icns by building an iconset and invoking iconutil."""
    log(f"Generating {icns_path.name}...")
    iconset = icns_path.with_suffix(".iconset")
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)

    # Apple's required iconset sizes: 16, 32, 128, 256, 512 (and @2x of each)
    pairs = [
        (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
    ]
    try:
        from PIL import Image
        import io
        try:
            renders = {s: Image.open(io.BytesIO(_render_svg_to_png_bytes(svg_path, s))).convert("RGBA")
                       for s in {p[0] for p in pairs}}
        except ImportError:
            log("  cairosvg missing, using fallback icon", "WARNING")
            renders = {s: _fallback_png_image(s) for s in {p[0] for p in pairs}}

        for size, name in pairs:
            renders[size].save(iconset / name, format="PNG")

        if shutil.which("iconutil"):
            subprocess.check_call(
                ["iconutil", "--convert", "icns", str(iconset), "--output", str(icns_path)])
            log(f"  Wrote {icns_path}", "SUCCESS")
            shutil.rmtree(iconset, ignore_errors=True)
            return True

        # Fallback: PIL can write .icns directly (lower quality but works off-macOS)
        log("  iconutil not available, using PIL fallback", "WARNING")
        largest = renders[max(renders)]
        largest.save(icns_path, format="ICNS")
        shutil.rmtree(iconset, ignore_errors=True)
        return True
    except Exception as e:
        log(f"icns generation failed: {e}", "ERROR")
        return False


def clean_build_artifacts(project_dir: Path) -> None:
    log("Cleaning build artifacts...")
    for d in ("build", "dist", "__pycache__"):
        p = project_dir / d
        if p.exists():
            shutil.rmtree(p)
            log(f"  Removed {d}/")
    for f in (f"{APP_NAME}.spec",):
        p = project_dir / f
        if p.exists():
            p.unlink()
            log(f"  Removed {f}")


def build_executable(project_dir: Path, target: str, debug: bool) -> bool:
    """PyInstaller invocation tailored to target OS."""
    log(f"Building for {target}...")
    main_script = project_dir / MAIN_SCRIPT
    if not main_script.exists():
        log(f"Missing entry script: {main_script}", "ERROR")
        return False

    cmd = ["pyinstaller", "--name", APP_NAME, "--clean", "--noconfirm"]

    if target == "Windows":
        cmd += ["--onefile", "--windowed" if not debug else "--console"]
        icon = project_dir / ICON_ICO
        if icon.exists():
            cmd += ["--icon", str(icon)]
    elif target == "Darwin":
        # PyInstaller creates a .app when --windowed is set on macOS
        cmd += ["--onedir", "--windowed" if not debug else "--console",
                "--osx-bundle-identifier", APP_BUNDLE_ID]
        icon = project_dir / ICON_ICNS
        if icon.exists():
            cmd += ["--icon", str(icon)]
    elif target == "Linux":
        cmd += ["--onefile", "--windowed" if not debug else "--console"]
        # Linux PyInstaller doesn't use icons in the binary itself
    else:
        log(f"Unsupported target: {target}", "ERROR")
        return False

    for imp in HIDDEN_IMPORTS_COMMON + HIDDEN_IMPORTS_PER_OS.get(target, []):
        cmd += ["--hidden-import", imp]

    for src, dst in DATA_FILES:
        sp = project_dir / src
        if sp.exists():
            cmd += ["--add-data", f"{sp}{os.pathsep}{dst}"]

    cmd.append(str(main_script))
    log(f"  $ {' '.join(cmd[:6])} ... ({len(cmd)} args)")
    result = subprocess.run(cmd, cwd=project_dir)
    if result.returncode != 0:
        log("PyInstaller failed", "ERROR")
        return False

    dist = project_dir / "dist"
    if target == "Windows":
        out = dist / f"{APP_NAME}.exe"
    elif target == "Darwin":
        out = dist / f"{APP_NAME}.app"
    else:
        out = dist / APP_NAME

    if not out.exists():
        log(f"Expected output not found: {out}", "ERROR")
        return False

    log(f"Built: {out}", "SUCCESS")
    return True


def write_macos_info_plist(project_dir: Path) -> None:
    """Patch the bundled Info.plist with mic usage + LSUIElement etc.

    PyInstaller creates a minimal Info.plist; we add the keys the OS needs
    so the user gets a real mic permission prompt instead of silent failure.
    """
    app = project_dir / "dist" / f"{APP_NAME}.app"
    plist_path = app / "Contents" / "Info.plist"
    if not plist_path.exists():
        log(f"Info.plist not found at {plist_path}", "WARNING")
        return

    with open(plist_path, "rb") as f:
        plist = plistlib.load(f)

    plist["CFBundleIdentifier"] = APP_BUNDLE_ID
    plist["CFBundleShortVersionString"] = APP_VERSION
    plist["CFBundleVersion"] = APP_VERSION
    plist["NSMicrophoneUsageDescription"] = (
        "TalkFlow needs microphone access to capture your voice for dictation.")
    plist["NSAppleEventsUsageDescription"] = (
        "TalkFlow uses Apple Events to type transcribed text into the focused app.")
    # Keep it visible in the Dock — users want to find the settings window.
    plist["LSMinimumSystemVersion"] = "11.0"
    plist["NSHighResolutionCapable"] = True

    with open(plist_path, "wb") as f:
        plistlib.dump(plist, f)
    log(f"Patched {plist_path.name} (mic + bundle metadata)", "SUCCESS")


def build_macos_dmg(project_dir: Path) -> bool:
    """Wrap the .app into a .dmg. Requires `create-dmg` or falls back to hdiutil."""
    app = project_dir / "dist" / f"{APP_NAME}.app"
    if not app.exists():
        log("No .app to package into DMG", "ERROR")
        return False

    dmg_path = project_dir / "dist" / f"{APP_NAME}-{APP_VERSION}.dmg"
    if dmg_path.exists():
        dmg_path.unlink()

    if shutil.which("create-dmg"):
        log("Building DMG with create-dmg...")
        cmd = ["create-dmg",
               "--volname", f"{APP_NAME} {APP_VERSION}",
               "--window-size", "540", "360",
               "--icon-size", "100",
               "--icon", f"{APP_NAME}.app", "140", "180",
               "--app-drop-link", "400", "180",
               str(dmg_path), str(app)]
        result = subprocess.run(cmd)
        if result.returncode == 0:
            log(f"DMG: {dmg_path}", "SUCCESS")
            return True
        log("create-dmg failed, falling back to hdiutil", "WARNING")

    if shutil.which("hdiutil"):
        log("Building DMG with hdiutil...")
        result = subprocess.run([
            "hdiutil", "create", "-volname", f"{APP_NAME} {APP_VERSION}",
            "-srcfolder", str(app), "-ov", "-format", "UDZO",
            str(dmg_path)])
        if result.returncode == 0:
            log(f"DMG: {dmg_path}", "SUCCESS")
            return True

    log("No DMG tool found (install `create-dmg` via Homebrew, or run on macOS for hdiutil)", "ERROR")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Build TalkFlow installer for current OS")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--skip-icon", action="store_true")
    parser.add_argument("--dmg", action="store_true", help="macOS: also build a .dmg")
    parser.add_argument("--target", default=None,
                        help="windows|macos|linux (auto-detect by default)")
    args = parser.parse_args()

    target = normalize_target(args.target)
    host = platform.system()
    project_dir = Path(__file__).parent.resolve()
    log(f"Target: {target}   Host: {host}   Project: {project_dir}")

    if target != host:
        log(f"PyInstaller cannot cross-build: host is {host} but target is {target}.\n"
            f"Run this script on a {target} machine (or in a {target} CI job).", "ERROR")
        return 2

    if not check_dependencies():
        return 1
    if args.clean:
        clean_build_artifacts(project_dir)

    if not args.skip_icon:
        svg = project_dir / ICON_SVG
        if svg.exists():
            if target == "Windows":
                ico = project_dir / ICON_ICO
                if not ico.exists() and not convert_svg_to_ico(svg, ico):
                    log("Continuing without icon", "WARNING")
            elif target == "Darwin":
                icns = project_dir / ICON_ICNS
                if not icns.exists() and not convert_svg_to_icns(svg, icns):
                    log("Continuing without icon", "WARNING")

    if not build_executable(project_dir, target, debug=args.debug):
        return 1

    if target == "Darwin":
        write_macos_info_plist(project_dir)
        if args.dmg and not build_macos_dmg(project_dir):
            return 1

    log("=" * 50)
    log("Build complete!", "SUCCESS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
