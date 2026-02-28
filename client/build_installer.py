#!/usr/bin/env python3
"""
TalkFlow Windows Installer Build Script
=======================================
Uses PyInstaller to bundle the TalkFlow client into a standalone Windows executable.

Usage:
    python build_installer.py          # Build the executable
    python build_installer.py --clean  # Clean build artifacts first
    python build_installer.py --debug  # Build with console window for debugging

Requirements:
    pip install pyinstaller pillow cairosvg

Output:
    dist/TalkFlow.exe           - Standalone executable
    dist/TalkFlow/              - One-folder distribution (if --onedir)
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Build configuration
APP_NAME = "TalkFlow"
APP_VERSION = "1.0.0"
MAIN_SCRIPT = "gui.py"
ICON_SVG = "assets/logo.svg"
ICON_ICO = "assets/logo.ico"

# PyInstaller options
PYINSTALLER_OPTS = [
    "--name", APP_NAME,
    "--windowed",           # No console window (use --console for debug)
    "--onefile",            # Single executable
    "--clean",              # Clean cache before building
    "--noconfirm",          # Overwrite without asking
]

# Hidden imports that PyInstaller might miss
HIDDEN_IMPORTS = [
    "pynput.keyboard._win32",
    "pynput.mouse._win32",
    "sounddevice",
    "numpy",
    "PIL._tkinter_finder",
    "pystray._win32",
]

# Data files to include
DATA_FILES = [
    ("assets", "assets"),   # Include assets folder
]


def log(msg: str, level: str = "INFO") -> None:
    """Print a formatted log message."""
    colors = {
        "INFO": "\033[94m",
        "SUCCESS": "\033[92m",
        "WARNING": "\033[93m",
        "ERROR": "\033[91m",
    }
    reset = "\033[0m"
    color = colors.get(level, "")
    print(f"{color}[{level}]{reset} {msg}")


def check_dependencies() -> bool:
    """Check that required build tools are installed."""
    log("Checking build dependencies...")

    missing = []

    # Check PyInstaller
    try:
        import PyInstaller
        log(f"  PyInstaller: {PyInstaller.__version__}")
    except ImportError:
        missing.append("pyinstaller")

    # Check Pillow (for icon conversion)
    try:
        import PIL
        log(f"  Pillow: {PIL.__version__}")
    except ImportError:
        missing.append("pillow")

    if missing:
        log(f"Missing dependencies: {', '.join(missing)}", "ERROR")
        log(f"Install with: pip install {' '.join(missing)}", "INFO")
        return False

    return True


def convert_svg_to_ico(svg_path: Path, ico_path: Path) -> bool:
    """Convert SVG logo to ICO format for Windows."""
    log(f"Converting {svg_path.name} to ICO format...")

    try:
        from PIL import Image
        import io

        # Try using cairosvg for high-quality SVG rendering
        try:
            import cairosvg

            # Render SVG at multiple sizes for ICO
            sizes = [16, 32, 48, 64, 128, 256]
            images = []

            for size in sizes:
                png_data = cairosvg.svg2png(
                    url=str(svg_path),
                    output_width=size,
                    output_height=size,
                )
                img = Image.open(io.BytesIO(png_data))
                # Convert to RGBA if needed
                if img.mode != "RGBA":
                    img = img.convert("RGBA")
                images.append(img)

            # Save as multi-resolution ICO
            images[0].save(
                ico_path,
                format="ICO",
                sizes=[(s, s) for s in sizes],
                append_images=images[1:],
            )
            log(f"  Created {ico_path} with {len(sizes)} resolutions", "SUCCESS")
            return True

        except ImportError:
            log("  cairosvg not available, creating simple icon", "WARNING")

            # Fallback: Create a simple colored icon
            sizes = [16, 32, 48, 64, 128, 256]
            images = []

            for size in sizes:
                # Create a teal/cyan gradient-like icon
                img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

                # Draw a simple microphone-like shape
                from PIL import ImageDraw
                draw = ImageDraw.Draw(img)

                # Background circle
                margin = size // 8
                draw.ellipse(
                    [margin, margin, size - margin, size - margin],
                    fill=(8, 145, 178, 255)  # Teal color
                )

                # White center (simplified waveform representation)
                center_margin = size // 4
                draw.ellipse(
                    [center_margin, center_margin, size - center_margin, size - center_margin],
                    fill=(255, 255, 255, 230)
                )

                images.append(img)

            # Save as ICO
            images[0].save(
                ico_path,
                format="ICO",
                sizes=[(s, s) for s in sizes],
                append_images=images[1:],
            )
            log(f"  Created fallback {ico_path}", "SUCCESS")
            return True

    except Exception as e:
        log(f"Failed to convert icon: {e}", "ERROR")
        return False


def clean_build_artifacts(project_dir: Path) -> None:
    """Remove previous build artifacts."""
    log("Cleaning build artifacts...")

    dirs_to_clean = ["build", "dist", "__pycache__"]
    files_to_clean = [f"{APP_NAME}.spec"]

    for dir_name in dirs_to_clean:
        dir_path = project_dir / dir_name
        if dir_path.exists():
            shutil.rmtree(dir_path)
            log(f"  Removed {dir_name}/")

    for file_name in files_to_clean:
        file_path = project_dir / file_name
        if file_path.exists():
            file_path.unlink()
            log(f"  Removed {file_name}")


def build_executable(project_dir: Path, debug: bool = False) -> bool:
    """Build the executable using PyInstaller."""
    log("Building executable with PyInstaller...")

    main_script = project_dir / MAIN_SCRIPT
    icon_file = project_dir / ICON_ICO

    if not main_script.exists():
        log(f"Main script not found: {main_script}", "ERROR")
        return False

    # Build PyInstaller command
    cmd = ["pyinstaller"]
    cmd.extend(PYINSTALLER_OPTS)

    # Add icon if available
    if icon_file.exists():
        cmd.extend(["--icon", str(icon_file)])
        log(f"  Using icon: {icon_file.name}")
    else:
        log("  No icon file found, building without icon", "WARNING")

    # Add hidden imports
    for imp in HIDDEN_IMPORTS:
        cmd.extend(["--hidden-import", imp])

    # Add data files
    for src, dst in DATA_FILES:
        src_path = project_dir / src
        if src_path.exists():
            # PyInstaller data format: source;destination
            cmd.extend(["--add-data", f"{src_path}{os.pathsep}{dst}"])

    # Debug mode: show console
    if debug:
        cmd = [c for c in cmd if c != "--windowed"]
        cmd.append("--console")
        log("  Debug mode: console window enabled")

    # Add main script
    cmd.append(str(main_script))

    log(f"  Running: {' '.join(cmd[:5])}...")

    # Run PyInstaller
    try:
        result = subprocess.run(
            cmd,
            cwd=project_dir,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            log("PyInstaller failed:", "ERROR")
            print(result.stderr)
            return False

        # Check output
        exe_path = project_dir / "dist" / f"{APP_NAME}.exe"
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            log(f"Build successful: {exe_path} ({size_mb:.1f} MB)", "SUCCESS")
            return True
        else:
            log("Executable not found after build", "ERROR")
            return False

    except FileNotFoundError:
        log("PyInstaller not found. Install with: pip install pyinstaller", "ERROR")
        return False
    except Exception as e:
        log(f"Build failed: {e}", "ERROR")
        return False


def create_version_info(project_dir: Path) -> None:
    """Create a version info file for Windows executable metadata."""
    version_file = project_dir / "version_info.txt"

    # Parse version into tuple
    version_parts = APP_VERSION.split(".")
    while len(version_parts) < 4:
        version_parts.append("0")
    version_tuple = ", ".join(version_parts[:4])

    content = f'''# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({version_tuple}),
    prodvers=({version_tuple}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '040904B0',
          [
            StringStruct('CompanyName', 'AI Implemented'),
            StringStruct('FileDescription', 'TalkFlow - Voice Dictation Client'),
            StringStruct('FileVersion', '{APP_VERSION}'),
            StringStruct('InternalName', '{APP_NAME}'),
            StringStruct('LegalCopyright', 'Copyright 2026 AI Implemented'),
            StringStruct('OriginalFilename', '{APP_NAME}.exe'),
            StringStruct('ProductName', '{APP_NAME}'),
            StringStruct('ProductVersion', '{APP_VERSION}'),
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
'''

    version_file.write_text(content)
    log(f"Created version info: {version_file.name}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build TalkFlow Windows installer"
    )
    parser.add_argument(
        "--clean", action="store_true",
        help="Clean build artifacts before building"
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Build with console window for debugging"
    )
    parser.add_argument(
        "--skip-icon", action="store_true",
        help="Skip icon conversion"
    )
    args = parser.parse_args()

    # Determine project directory
    project_dir = Path(__file__).parent.resolve()
    log(f"Project directory: {project_dir}")

    # Check dependencies
    if not check_dependencies():
        return 1

    # Clean if requested
    if args.clean:
        clean_build_artifacts(project_dir)

    # Convert icon
    if not args.skip_icon:
        svg_path = project_dir / ICON_SVG
        ico_path = project_dir / ICON_ICO

        if svg_path.exists() and not ico_path.exists():
            if not convert_svg_to_ico(svg_path, ico_path):
                log("Icon conversion failed, continuing without icon", "WARNING")
        elif ico_path.exists():
            log(f"Using existing icon: {ico_path.name}")

    # Create version info
    create_version_info(project_dir)

    # Build executable
    if not build_executable(project_dir, debug=args.debug):
        return 1

    log("=" * 50)
    log("Build complete!", "SUCCESS")
    log(f"Executable: {project_dir / 'dist' / APP_NAME}.exe")
    log("Next steps:")
    log("  1. Test the executable")
    log("  2. Run Inno Setup with installer.iss to create installer")

    return 0


if __name__ == "__main__":
    sys.exit(main())
