#!/usr/bin/env bash
# =============================================================================
# Roomba 960 Controller & Web Cockpit - Turnkey Automated Setup Script
#
# Supported OS: Raspberry Pi OS (Debian), Ubuntu, Debian
# Features:
#   1. Validates Linux environment and root/sudo privileges
#   2. Installs Docker & Docker Compose plugin if missing
#   3. Adds user to docker, dialout, and video groups
#   4. Installs udev rules for serial USB interface access (/dev/ttyACM*, /dev/ttyUSB*)
#   5. Configures .env from .env.example if missing
#   6. Builds Roomba Docker image
#   7. Installs, enables, and starts a systemd auto-start service (roomba.service)
#   8. Verifies container health and displays Cockpit web dashboard URL
# =============================================================================

set -euo pipefail

# -----------------------------------------------------------------------------
# Colorized Output Helpers
# -----------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

log_info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $*"; }
log_warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }

echo -e "${CYAN}${BOLD}"
echo "=========================================================="
echo "    Roomba 960 Modular Controller - Automated Setup       "
echo "=========================================================="
echo -e "${NC}"

# -----------------------------------------------------------------------------
# Step 1: Operating System & Permission Checks
# -----------------------------------------------------------------------------
if [ "$(uname -s)" != "Linux" ]; then
    log_error "This setup script is intended for Linux (Raspberry Pi OS, Debian, Ubuntu)."
    echo "On Windows / macOS, please run Docker Desktop and use: docker compose up -d"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -f "${SCRIPT_DIR}/docker-compose.yml" ]; then
    PROJECT_DIR="${SCRIPT_DIR}"
elif [ -f "${SCRIPT_DIR}/../docker-compose.yml" ]; then
    PROJECT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
else
    PROJECT_DIR="${SCRIPT_DIR}"
fi
cd "$PROJECT_DIR"
log_info "Project root directory: $PROJECT_DIR"

if [ "$(id -u)" -ne 0 ]; then
    if command -v sudo &>/dev/null; then
        SUDO="sudo"
    else
        log_error "This script requires root privileges. Please install sudo or run as root."
        exit 1
    fi
else
    SUDO=""
fi

REAL_USER="${SUDO_USER:-$(logname 2>/dev/null || echo "$USER")}"
log_info "Running setup for user: ${BOLD}$REAL_USER${NC}"

# -----------------------------------------------------------------------------
# Step 2: Install Docker Engine & Compose Plugin if Missing
# -----------------------------------------------------------------------------
if ! command -v docker &>/dev/null; then
    log_info "Docker is not installed. Installing Docker via official convenience script..."
    $SUDO apt-get update -y
    $SUDO apt-get install -y curl ca-certificates gnupg
    curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
    $SUDO sh /tmp/get-docker.sh
    rm -f /tmp/get-docker.sh
    $SUDO systemctl enable --now docker
    log_success "Docker installed successfully ($(docker --version 2>/dev/null || echo 'OK'))."
else
    log_success "Docker is already installed: $(docker --version)"
fi

# Verify Docker Compose V2 plugin
if ! docker compose version &>/dev/null; then
    log_info "Docker Compose plugin is missing. Attempting installation..."
    $SUDO apt-get update -y
    $SUDO apt-get install -y docker-compose-plugin || {
        log_warn "Package 'docker-compose-plugin' not found in apt repo. Installing standalone binary..."
        ARCH="$(uname -m)"
        case "$ARCH" in
            x86_64)          COMPOSE_ARCH="x86_64" ;;
            aarch64|arm64)   COMPOSE_ARCH="aarch64" ;;
            armv7l|armhf)    COMPOSE_ARCH="armv7" ;;
            *)               COMPOSE_ARCH="$ARCH" ;;
        esac
        CLI_PLUGIN_DIR="/usr/local/lib/docker/cli-plugins"
        $SUDO mkdir -p "$CLI_PLUGIN_DIR"
        $SUDO curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${COMPOSE_ARCH}" -o "${CLI_PLUGIN_DIR}/docker-compose"
        $SUDO chmod +x "${CLI_PLUGIN_DIR}/docker-compose"
    }
    log_success "Docker Compose ready: $(docker compose version 2>/dev/null || echo 'Installed')"
else
    log_success "Docker Compose is already available: $(docker compose version --short 2>/dev/null || docker compose version)"
fi

# Ensure docker daemon is active
$SUDO systemctl enable --now docker 2>/dev/null || true

# -----------------------------------------------------------------------------
# Step 3: Configure User Groups & Hardware Permissions
# -----------------------------------------------------------------------------
if [ -n "$REAL_USER" ] && [ "$REAL_USER" != "root" ]; then
    log_info "Adding '$REAL_USER' to 'docker', 'dialout', and 'video' groups..."
    $SUDO usermod -aG docker,dialout,video "$REAL_USER" 2>/dev/null || true
fi

log_info "Configuring udev rules for Roomba serial ports..."
$SUDO bash -c 'cat << "EOF" > /etc/udev/rules.d/99-roomba.rules
# iRobot Roomba USB CDC ACM and FTDI interfaces
SUBSYSTEM=="tty", ATTRS{idVendor}=="0403", MODE="0666", GROUP="dialout"
SUBSYSTEM=="tty", KERNEL=="ttyACM[0-9]*", MODE="0666", GROUP="dialout"
SUBSYSTEM=="tty", KERNEL=="ttyUSB[0-9]*", MODE="0666", GROUP="dialout"
EOF'
$SUDO udevadm control --reload-rules 2>/dev/null || true
$SUDO udevadm trigger 2>/dev/null || true
log_success "Hardware permissions configured."

# -----------------------------------------------------------------------------
# Step 4: Environment & Port Detection
# -----------------------------------------------------------------------------
if [ ! -f "${PROJECT_DIR}/.env" ]; then
    if [ -f "${PROJECT_DIR}/.env.example" ]; then
        log_info "Creating .env from .env.example..."
        cp "${PROJECT_DIR}/.env.example" "${PROJECT_DIR}/.env"
    else
        touch "${PROJECT_DIR}/.env"
    fi
    log_success "Created .env configuration file."
else
    log_info ".env configuration file already exists."
fi

# Scan for connected Roomba hardware
DETECTED_PORTS=$(ls /dev/ttyACM* /dev/ttyUSB* 2>/dev/null || true)
if [ -n "$DETECTED_PORTS" ]; then
    log_success "Found potential Roomba serial port(s): ${DETECTED_PORTS}"
else
    log_warn "No /dev/ttyACM* or /dev/ttyUSB* ports detected right now."
    log_warn "Plug the micro-USB cable into the Roomba and Raspberry Pi."
    log_warn "The service will auto-detect the port upon connection."
fi

# -----------------------------------------------------------------------------
# Step 5: Build Docker Container
# -----------------------------------------------------------------------------
log_info "Building Roomba Cockpit Docker image (this may take a couple of minutes)..."
$SUDO docker compose -f "${PROJECT_DIR}/docker-compose.yml" build

log_success "Docker image built successfully."

# -----------------------------------------------------------------------------
# Step 6: Create and Enable Systemd Service
# -----------------------------------------------------------------------------
SERVICE_FILE="/etc/systemd/system/roomba.service"
DOCKER_BIN="$(command -v docker || echo '/usr/bin/docker')"

log_info "Registering systemd service at: $SERVICE_FILE"

$SUDO bash -c "cat << EOF > '$SERVICE_FILE'
[Unit]
Description=Roomba 960 Web Controller & Autonomy Engine (Docker Compose)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=${PROJECT_DIR}
ExecStart=${DOCKER_BIN} compose up -d --remove-orphans
ExecStop=${DOCKER_BIN} compose down
ExecReload=${DOCKER_BIN} compose restart
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF"

$SUDO systemctl daemon-reload
$SUDO systemctl enable roomba.service
log_success "Systemd service 'roomba.service' enabled for automatic boot."

log_info "Starting Roomba service now..."
$SUDO systemctl restart roomba.service

# -----------------------------------------------------------------------------
# Step 7: Verification & Quick Status
# -----------------------------------------------------------------------------
log_info "Waiting for service to initialize..."
sleep 4

# Fetch local IP addresses
IP_ADDRESSES="$(hostname -I 2>/dev/null | tr -s ' ' || ip route get 1.1.1.1 2>/dev/null | awk '{print $7}')"
PRIMARY_IP="$(echo "$IP_ADDRESSES" | awk '{print $1}')"
[ -z "$PRIMARY_IP" ] && PRIMARY_IP="localhost"

echo ""
echo -e "${GREEN}${BOLD}==========================================================${NC}"
echo -e "${GREEN}${BOLD}     Roomba 960 Controller Successfully Installed!         ${NC}"
echo -e "${GREEN}${BOLD}==========================================================${NC}"
echo ""
echo -e "  ${BOLD}Web Cockpit Dashboard:${NC} http://${PRIMARY_IP}:8000"
echo -e "  ${BOLD}Local Access:${NC}          http://localhost:8000"
echo -e "  ${BOLD}API Documentation:${NC}     http://${PRIMARY_IP}:8000/docs"
echo ""
echo -e "${BOLD}Management Commands:${NC}"
echo -e "  ${CYAN}Check service status:${NC}  sudo systemctl status roomba"
echo -e "  ${CYAN}View real-time logs:${NC}   sudo docker compose logs -f"
echo -e "  ${CYAN}Restart controller:${NC}    sudo systemctl restart roomba"
echo -e "  ${CYAN}Stop controller:${NC}       sudo systemctl stop roomba"
echo -e "  ${CYAN}Run terminal teleop:${NC}   sudo docker compose --profile teleop run --rm roomba-teleop"
echo ""
if [ -n "$REAL_USER" ] && [ "$REAL_USER" != "root" ]; then
    echo -e "${YELLOW}Note: Group changes were applied for user '${REAL_USER}'.${NC}"
    echo -e "${YELLOW}If you wish to run 'docker' without sudo in your current terminal session, run: newgrp docker${NC}"
fi
echo ""
