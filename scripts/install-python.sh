#!/usr/bin/env bash
# Install Python dependencies
# Usage: install-python.sh (no args)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(readlink -f "${SCRIPT_DIR}/..")"

source "${SCRIPT_DIR}/common.sh"

# Install Python dependencies
install_python() {
    cd "${ROOT_DIR}"
    rm -fr .venv examples/cli/.venv examples/cli/packages/example_cli/.venv && uv sync --all-extras --all-groups
}

install_python
