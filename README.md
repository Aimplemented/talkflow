# TalkFlow

Real-time speech-to-text system with client-server architecture. Push-to-talk dictation that transcribes speech and injects text at your cursor.

## Architecture

- **Server:** Dockerized Faster-Whisper (large-v3 model), WebSocket-based
- **Client:** Python GUI/CLI with push-to-talk hotkey, audio capture, and keystroke injection

## Quick Start

### Server (Linux/Docker)
```bash
cd server
docker compose up -d
```

### Client (macOS/Windows)
```bash
cd client
pip install -r requirements.txt  # or use the venv
python client.py --server <server-ip>:9876
```

### Windows Installer
Run `TalkFlow-Install.ps1` or `TalkFlow-Install.bat` for automated setup.

## Components

| Component | Location | Description |
|-----------|----------|-------------|
| Server | `server/` | Faster-Whisper transcription server (Docker) |
| Client | `client/` | Cross-platform client with GUI |
| Windows Installer | `TalkFlow-Install.*` | Automated Windows setup scripts |

## Configuration

- **Default hotkey:** Ctrl+Shift+D (toggle recording)
- **Default server port:** 9876
- **Model:** faster-whisper large-v3

## License

Private — AI Implemented © 2026
