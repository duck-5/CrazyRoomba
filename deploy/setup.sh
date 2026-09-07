#!/usr/bin/env bash
# Wrapper redirecting to root setup.sh
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec bash "${SCRIPT_DIR}/../setup.sh" "$@"
