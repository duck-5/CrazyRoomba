# =============================================================================
# Multi-Architecture Dockerfile for Roomba 960 Controller & Web Hub
# Architectures supported: linux/amd64, linux/arm64 (Pi 3/4/5), linux/arm/v7
# =============================================================================

FROM python:3.11-slim-bookworm

# Build metadata
LABEL maintainer="Yuval Mantin"
LABEL description="Roomba 960 Autonomous Controller & Real-Time Web Cockpit"

# Python runtime configuration
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=1000 \
    PIP_RETRIES=20 \
    DEBIAN_FRONTEND=noninteractive \
    ROOMBA_HOST=0.0.0.0 \
    ROOMBA_HTTP_PORT=8000 \
    ROOMBA_MODE=Safe

# 1. Install system runtime dependencies:
# - udev & usbutils: Hardware device discovery, CDC ACM hotplugging for iRobot VID 0x27A6
# - curl: Container healthcheck against /api/status
# - v4l-utils: Video4Linux camera management (USB & Raspberry Pi CSI cameras)
# - libgl1 & libglib2.0-0: Headless GUI & graphics runtimes required by OpenCV for vision modes
# - ca-certificates: Secure SSL connections
RUN apt-get update && apt-get install -y --no-install-recommends \
    udev \
    usbutils \
    curl \
    v4l-utils \
    libgl1 \
    libglib2.0-0 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 2. Setup non-root application user with hardware serial and video access
# - dialout group: Grants access to /dev/ttyACM*, /dev/ttyUSB*, and /dev/serial/by-id/*
# - video group: Grants access to /dev/video* camera streams
RUN groupadd -f -g 20 dialout && \
    groupadd -f -g 44 video && \
    useradd -m -s /bin/bash -u 1000 -G dialout,video roomba

# 3. Working directory setup
WORKDIR /app

# 4. Install Python dependencies
COPY requirements.txt pyproject.toml README.md ./
RUN pip install --upgrade pip setuptools wheel && \
    pip install --default-timeout=1000 --retries=20 --prefer-binary -r requirements.txt && \
    rm -rf /root/.cache/pip

# 5. Copy project source code
COPY roomba/ ./roomba/
COPY scripts/ ./scripts/

# 6. Install the package in editable/local mode so roomba console scripts are registered
RUN pip install --no-cache-dir --no-deps -e . && \
    chown -R roomba:roomba /app

# 7. Switch to non-root user
USER roomba

# Expose web cockpit port
EXPOSE 8000

# Container health monitoring
HEALTHCHECK --interval=20s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/status || exit 1

# Default entrypoint: unified roomba CLI module
ENTRYPOINT ["python", "-m", "roomba"]

# Default command: launch web cockpit on 0.0.0.0:8000
CMD ["web", "--host", "0.0.0.0", "--port", "8000"]
