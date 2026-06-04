#!/usr/bin/env bash
# TalkFlow — self-hosted STT server installer (one-shot, idempotent)
# ==================================================================
# Stands up the faster-whisper WebSocket transcription server (server.py) so
# TalkFlow clients can dictate against your own hardware instead of Groq.
# It will, as needed:
#
#   1. detect the package manager (apt / dnf / pacman) and whether this is a
#      systemd host;
#   2. detect an NVIDIA GPU via nvidia-smi (falls back to CPU/int8 automatically
#      if none is found — slower, but works);
#   3. install in one of two modes (auto-detected, override with --mode):
#        - docker : build + run via the existing docker-compose.yml (needs the
#                   nvidia container toolkit for GPU);
#        - native : python venv + a systemd service `talkflow-server.service`
#                   (Restart=always, enabled at boot);
#   4. wait for the server to answer, then print the ws:// URL and how to point
#      a client at it.
#
# Run as your normal user (it sudo's for the system bits) or as root:
#     bash install-server.sh                       # auto-detect mode
#     bash install-server.sh --mode native         # force venv + systemd
#     bash install-server.sh --mode docker         # force docker compose
#     bash install-server.sh --port 9876 --model large-v3 --device cuda
#     bash install-server.sh --uninstall
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${CYAN}==>${NC} $*"; }
ok()    { echo -e "${GREEN}  ✓${NC} $*"; }
warn()  { echo -e "${YELLOW}  ⚠${NC} $*"; }
die()   { echo -e "${RED}  ✗${NC} $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Defaults / flag parsing
# ---------------------------------------------------------------------------
MODE="auto"                                   # auto | docker | native
PORT="${SERVER_PORT:-9876}"
MODEL="${WHISPER_MODEL:-large-v3}"
DEVICE="${WHISPER_DEVICE:-}"                   # empty → auto from GPU detection
COMPUTE="${WHISPER_COMPUTE:-}"                 # empty → auto from device
BEAM_SIZE="${WHISPER_BEAM_SIZE:-5}"
LANGUAGE="${WHISPER_LANGUAGE:-en}"
DO_UNINSTALL=0

SERVICE_NAME="talkflow-server.service"
SYS_UNIT="/etc/systemd/system/${SERVICE_NAME}"
COMPOSE_PROJECT="talkflow-server"
ENV_FILE_NAME=".talkflow-server.env"

usage() {
    sed -n '2,30p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit 0
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)     MODE="${2:-}"; shift 2 ;;
        --mode=*)   MODE="${1#*=}"; shift ;;
        --port)     PORT="${2:-}"; shift 2 ;;
        --port=*)   PORT="${1#*=}"; shift ;;
        --model)    MODEL="${2:-}"; shift 2 ;;
        --model=*)  MODEL="${1#*=}"; shift ;;
        --device)   DEVICE="${2:-}"; shift 2 ;;
        --device=*) DEVICE="${1#*=}"; shift ;;
        --compute)  COMPUTE="${2:-}"; shift 2 ;;
        --compute=*) COMPUTE="${1#*=}"; shift ;;
        --uninstall) DO_UNINSTALL=1; shift ;;
        -h|--help)  usage ;;
        *)          die "Unknown argument: $1 (try --help)" ;;
    esac
done

case "$MODE" in auto|docker|native) ;; *) die "--mode must be auto, docker or native" ;; esac
[[ "$PORT" =~ ^[0-9]+$ ]] || die "--port must be numeric (got: $PORT)"

# ---------------------------------------------------------------------------
# Root / sudo handling — native mode installs to /opt when root, else ~
# ---------------------------------------------------------------------------
if [[ "$(id -u)" -eq 0 ]]; then
    SUDO=""
    INSTALL_DIR="/opt/talkflow-server"
else
    if command -v sudo >/dev/null; then SUDO="sudo"; else SUDO=""; fi
    INSTALL_DIR="$HOME/talkflow-server"
fi

# ---------------------------------------------------------------------------
# Package-manager + systemd detection
# ---------------------------------------------------------------------------
detect_pkg() {
    if command -v apt-get >/dev/null;  then echo apt;    return; fi
    if command -v dnf     >/dev/null;  then echo dnf;    return; fi
    if command -v pacman  >/dev/null;  then echo pacman; return; fi
    echo none
}
PKG="$(detect_pkg)"
HAS_SYSTEMD=0
if command -v systemctl >/dev/null && [[ -d /run/systemd/system ]]; then HAS_SYSTEMD=1; fi

# ---------------------------------------------------------------------------
# GPU detection → choose device/compute defaults when not overridden
# ---------------------------------------------------------------------------
HAS_GPU=0
if command -v nvidia-smi >/dev/null && nvidia-smi -L >/dev/null 2>&1; then
    HAS_GPU=1
    GPU_NAME="$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n1)"
    ok "NVIDIA GPU detected: ${GPU_NAME:-unknown}"
else
    warn "No NVIDIA GPU detected — the server will run on CPU (slower)."
fi

if [[ -z "$DEVICE" ]]; then
    if [[ "$HAS_GPU" -eq 1 ]]; then DEVICE="cuda"; else DEVICE="cpu"; fi
fi
if [[ -z "$COMPUTE" ]]; then
    if [[ "$DEVICE" == "cuda" ]]; then COMPUTE="float16"; else COMPUTE="int8"; fi
fi

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------
uninstall() {
    info "Uninstalling TalkFlow STT server"
    # Native systemd service
    if [[ "$HAS_SYSTEMD" -eq 1 ]]; then
        $SUDO systemctl disable --now "$SERVICE_NAME" 2>/dev/null || true
        $SUDO rm -f "$SYS_UNIT"
        $SUDO systemctl daemon-reload 2>/dev/null || true
        ok "Removed systemd service ${SERVICE_NAME} (if present)."
    fi
    # Docker
    if command -v docker >/dev/null; then
        if docker compose version >/dev/null 2>&1; then
            ( cd "$HERE" && docker compose -p "$COMPOSE_PROJECT" down 2>/dev/null ) || true
        fi
        docker rm -f "$COMPOSE_PROJECT" 2>/dev/null || true
        ok "Stopped docker container (if present)."
    fi
    warn "Left the venv at $INSTALL_DIR and any docker images/volumes in place."
    warn "Remove them manually if desired: rm -rf '$INSTALL_DIR'"
    exit 0
}
[[ "$DO_UNINSTALL" -eq 1 ]] && uninstall

# ---------------------------------------------------------------------------
# Mode auto-detection
# ---------------------------------------------------------------------------
docker_ready() {
    command -v docker >/dev/null || return 1
    docker info >/dev/null 2>&1 || return 1
    docker compose version >/dev/null 2>&1 || return 1
    return 0
}
nvidia_docker_ready() {
    # nvidia container toolkit registers an "nvidia" runtime
    docker info 2>/dev/null | grep -qi 'nvidia' && return 0
    [[ -x /usr/bin/nvidia-ctk ]] && return 0
    return 1
}

if [[ "$MODE" == "auto" ]]; then
    if docker_ready; then
        if [[ "$HAS_GPU" -eq 0 ]] || nvidia_docker_ready; then
            MODE="docker"
        else
            warn "Docker is present but the NVIDIA container toolkit is not — using native mode to keep GPU access."
            MODE="native"
        fi
    else
        MODE="native"
    fi
fi
info "Install mode: ${MODE}  (pkg=${PKG}, systemd=${HAS_SYSTEMD}, gpu=${HAS_GPU})"
info "Settings: port=${PORT} model=${MODEL} device=${DEVICE} compute=${COMPUTE}"

# ---------------------------------------------------------------------------
# Wait-for-server helper + final instructions (shared by both modes)
# ---------------------------------------------------------------------------
HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
[[ -n "$HOST_IP" ]] || HOST_IP="$(hostname)"

wait_for_server() {
    info "Waiting for the server to answer on :${PORT} (model download can take minutes on first run)…"
    local i
    for i in $(seq 1 90); do
        if command -v curl >/dev/null && curl -fsS "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
            ok "Server is healthy on :${PORT}"
            return 0
        fi
        # Fall back to a raw TCP probe if curl/health isn't available.
        if (exec 3<>"/dev/tcp/127.0.0.1/${PORT}") 2>/dev/null; then
            exec 3>&- 3<&- 2>/dev/null || true
            ok "Server is listening on :${PORT}"
            return 0
        fi
        sleep 2
    done
    warn "Server did not answer within ~3 min — it may still be downloading the model."
    return 1
}

print_client_instructions() {
    echo
    ok "TalkFlow STT server is up."
    echo -e "  WebSocket URL for clients:  ${CYAN}ws://${HOST_IP}:${PORT}/ws/dictate${NC}"
    echo
    echo -e "  Point a TalkFlow client at this server with:"
    echo -e "    ${CYAN}python streamdeck_daemon.py setup --backend server --server ${HOST_IP}:${PORT}${NC}"
    echo -e "  If your client's 'setup' doesn't persist server settings, pass them at run time instead:"
    echo -e "    ${CYAN}python streamdeck_daemon.py daemon --backend server --server ${HOST_IP}:${PORT}${NC}"
    echo
}

# ===========================================================================
# DOCKER MODE
# ===========================================================================
install_docker() {
    docker_ready || die "Docker mode requested but docker (with the compose plugin) is not available/running."
    [[ -f "$HERE/docker-compose.yml" ]] || die "docker-compose.yml not found next to this script."
    if [[ "$HAS_GPU" -eq 1 ]] && ! nvidia_docker_ready; then
        warn "GPU present but NVIDIA container toolkit not detected — the container may fail to see the GPU."
        warn "Install it: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html"
    fi

    # Write an env file compose reads for variable substitution.
    local env_path="$HERE/.env"
    info "Writing compose env → $env_path"
    cat > "$env_path" <<EOF
# Generated by install-server.sh — safe to edit and re-run.
WHISPER_MODEL=${MODEL}
WHISPER_DEVICE=${DEVICE}
WHISPER_COMPUTE=${COMPUTE}
WHISPER_BEAM_SIZE=${BEAM_SIZE}
WHISPER_LANGUAGE=${LANGUAGE}
SERVER_PORT=${PORT}
EOF

    # Build a compose command; drop GPU reservations on CPU-only hosts.
    local -a compose=(docker compose -p "$COMPOSE_PROJECT" --env-file "$env_path")
    if [[ "$HAS_GPU" -eq 0 ]]; then
        warn "No GPU — starting compose without GPU device reservations."
        # The compose file's deploy.reservations is ignored by `docker compose up`
        # on hosts without the nvidia runtime, so a plain up works on CPU too.
    fi

    info "Building and starting the container (docker compose up -d --build)…"
    ( cd "$HERE" && SERVER_PORT="$PORT" "${compose[@]}" up -d --build )
    ok "Container started (project: $COMPOSE_PROJECT)."
    wait_for_server || true
    echo -e "  Logs:   ${CYAN}docker compose -p ${COMPOSE_PROJECT} logs -f${NC}"
    print_client_instructions
}

# ===========================================================================
# NATIVE MODE (venv + systemd)
# ===========================================================================
ensure_python() {
    if command -v python3 >/dev/null; then return; fi
    info "Installing python3…"
    case "$PKG" in
        apt)    $SUDO apt-get update -y && $SUDO apt-get install -y python3 python3-venv python3-pip ;;
        dnf)    $SUDO dnf install -y python3 python3-pip ;;
        pacman) $SUDO pacman -Sy --noconfirm python python-pip ;;
        *)      die "No supported package manager — install python3 (with venv) manually and re-run." ;;
    esac
}

ensure_venv_support() {
    # On Debian/Ubuntu the venv module ships separately.
    if python3 -c 'import venv, ensurepip' 2>/dev/null; then return; fi
    info "Installing python venv support…"
    case "$PKG" in
        apt)    $SUDO apt-get update -y && $SUDO apt-get install -y python3-venv python3-pip ;;
        dnf)    $SUDO dnf install -y python3-pip ;;
        pacman) $SUDO pacman -Sy --noconfirm python-pip ;;
        *)      warn "Could not auto-install venv support — continuing and hoping it works." ;;
    esac
}

install_native() {
    [[ "$HAS_SYSTEMD" -eq 1 ]] || die "Native mode installs a systemd service, but this host has no systemd. Use --mode docker, or run server.py manually."
    [[ -f "$HERE/server.py" ]] || die "server.py not found next to this script."
    [[ -f "$HERE/requirements.txt" ]] || die "requirements.txt not found next to this script."
    command -v curl >/dev/null || warn "curl not found — health probing will fall back to a TCP check."

    ensure_python
    ensure_venv_support

    info "Creating install dir: $INSTALL_DIR"
    $SUDO mkdir -p "$INSTALL_DIR"
    # Make sure we own it (when installing to /opt as a sudo'ing user, root owns it).
    $SUDO cp "$HERE/server.py" "$HERE/requirements.txt" "$INSTALL_DIR/"

    if [[ ! -x "$INSTALL_DIR/venv/bin/python" ]]; then
        info "Creating virtualenv at $INSTALL_DIR/venv"
        $SUDO python3 -m venv "$INSTALL_DIR/venv"
    else
        ok "Reusing existing virtualenv."
    fi

    info "Installing Python dependencies (this can take a while)…"
    $SUDO "$INSTALL_DIR/venv/bin/pip" install --upgrade pip
    $SUDO "$INSTALL_DIR/venv/bin/pip" install -r "$INSTALL_DIR/requirements.txt"
    ok "Dependencies installed."

    # Determine which user the service should run as.
    local run_user
    if [[ "$(id -u)" -eq 0 ]]; then run_user="root"; else run_user="$(id -un)"; fi

    info "Writing systemd unit → $SYS_UNIT"
    $SUDO tee "$SYS_UNIT" >/dev/null <<EOF
[Unit]
Description=TalkFlow self-hosted STT server (faster-whisper)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${run_user}
WorkingDirectory=${INSTALL_DIR}
Environment=WHISPER_MODEL=${MODEL}
Environment=WHISPER_DEVICE=${DEVICE}
Environment=WHISPER_COMPUTE=${COMPUTE}
Environment=WHISPER_BEAM_SIZE=${BEAM_SIZE}
Environment=WHISPER_LANGUAGE=${LANGUAGE}
Environment=SERVER_PORT=${PORT}
ExecStart=${INSTALL_DIR}/venv/bin/python -m uvicorn server:app --host 0.0.0.0 --port ${PORT} --workers 1
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

    info "Enabling and starting ${SERVICE_NAME}"
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable "$SERVICE_NAME"
    $SUDO systemctl restart "$SERVICE_NAME"

    sleep 2
    if $SUDO systemctl is-active --quiet "$SERVICE_NAME"; then
        ok "Service active."
    else
        warn "Service not active yet — check: journalctl -u ${SERVICE_NAME} -e"
    fi
    wait_for_server || true
    echo -e "  Logs:   ${CYAN}journalctl -u ${SERVICE_NAME} -f${NC}"
    print_client_instructions
}

# ===========================================================================
# Dispatch
# ===========================================================================
case "$MODE" in
    docker) install_docker ;;
    native) install_native ;;
    *)      die "Unreachable mode: $MODE" ;;
esac
