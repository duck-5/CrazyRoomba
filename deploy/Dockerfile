# Multi-Architecture Dockerfile for Roomba 960 Controller
# Supports Linux ARM64/ARMv7 (Raspberry Pi 3/4/5) and AMD64

FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

# Install essential runtime tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    udev \
    curl \
    v4l-utils \
    && rm -rf /var/lib/apt/lists/*

# Working directory
WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY . .

# Ensure app user has access to serial and camera devices
RUN groupadd -f dialout && groupadd -f video \
    && useradd -m -s /bin/bash -G dialout,video roomba \
    && chown -R roomba:roomba /app

USER roomba

# Expose web dashboard port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/status || exit 1

# Default execution: run the web server
ENTRYPOINT ["python", "scripts/run_server.py"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
