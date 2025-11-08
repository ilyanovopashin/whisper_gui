#!/usr/bin/env bash
# Automated setup script for Whisper GUI on macOS.
# This script installs required Homebrew packages, prepares a Python virtual environment,
# installs project dependencies, and ensures environment configuration files exist.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="${PROJECT_ROOT}/.venv"
PYTHON_MIN_VERSION="3.11"
BREW_PACKAGES=(ffmpeg yt-dlp)
START_BACKEND=false

print_heading() {
  printf "\n\033[1;34m%s\033[0m\n" "$1"
}

print_step() {
  printf "\033[1;32m➜\033[0m %s\n" "$1"
}

print_warn() {
  printf "\033[1;33m⚠\033[0m %s\n" "$1"
}

print_error() {
  printf "\033[1;31m✖\033[0m %s\n" "$1"
}

usage() {
  cat <<USAGE
Usage: $(basename "$0") [options]

Options:
  --start-backend    Launch the FastAPI backend with uvicorn after setup completes.
  -h, --help         Show this help message and exit.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --start-backend)
      START_BACKEND=true
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      print_error "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

print_heading "Whisper GUI macOS setup"

if [[ "$(uname -s)" != "Darwin" ]]; then
  print_error "This script is intended to run on macOS (Darwin)."
  exit 1
fi

print_step "Checking for Homebrew"
if ! command -v brew >/dev/null 2>&1; then
  print_error "Homebrew is not installed. Install it from https://brew.sh and re-run this script."
  exit 1
fi

print_step "Updating Homebrew"
brew update

print_step "Installing required Homebrew packages: ${BREW_PACKAGES[*]}"
brew install "${BREW_PACKAGES[@]}"

# Determine a suitable Python interpreter
print_step "Locating Python ${PYTHON_MIN_VERSION}+ interpreter"
PYTHON_BIN=""
if command -v python${PYTHON_MIN_VERSION} >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python${PYTHON_MIN_VERSION})"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  print_error "Python ${PYTHON_MIN_VERSION}+ is required. Install it via Homebrew (brew install python@3.11) and rerun the script."
  exit 1
fi

PYTHON_VERSION="$(${PYTHON_BIN} -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
PYTHON_OK=$(${PYTHON_BIN} - <<PY
import sys
min_version = tuple(int(part) for part in "${PYTHON_MIN_VERSION}".split("."))
print("true" if sys.version_info >= min_version else "false")
PY
)
if [[ "${PYTHON_OK}" != "true" ]]; then
  print_error "Python ${PYTHON_MIN_VERSION}+ required, but found ${PYTHON_VERSION}. Install a newer Python via Homebrew (brew install python@3.11)."
  exit 1
fi

print_step "Using Python interpreter: ${PYTHON_BIN} (${PYTHON_VERSION})"

print_step "Creating virtual environment at ${VENV_DIR}"
${PYTHON_BIN} -m venv "${VENV_DIR}"

print_step "Activating virtual environment"
# shellcheck disable=SC1090
source "${VENV_DIR}/bin/activate"

print_step "Upgrading pip"
pip install --upgrade pip

print_step "Installing project dependencies"
pip install -e "${PROJECT_ROOT}[dev]"

ENV_FILE="${PROJECT_ROOT}/.env"
EXAMPLE_ENV_FILE="${PROJECT_ROOT}/.env.example"
if [[ -f "${EXAMPLE_ENV_FILE}" && ! -f "${ENV_FILE}" ]]; then
  print_step "Creating .env from .env.example"
  cp "${EXAMPLE_ENV_FILE}" "${ENV_FILE}"
  print_warn "Update ${ENV_FILE} to match your environment (e.g., WHISPERX_MODEL, storage paths)."
elif [[ ! -f "${ENV_FILE}" ]]; then
  print_warn "No .env file detected. Create ${ENV_FILE} with required environment variables."
fi

print_step "Setup complete."
print_heading "Next steps"
cat <<'NEXTSTEPS'
1. Review and adjust the .env file if necessary.
2. (Optional) Install frontend dependencies:
     cd frontend && npm install
3. Start the backend API:
     source .venv/bin/activate
     uvicorn app.backend.server:app --host 0.0.0.0 --port 8000
4. Start the frontend in another terminal:
     cd frontend
     npm run dev
NEXTSTEPS

if ${START_BACKEND}; then
  print_step "Launching backend with uvicorn"
  uvicorn app.backend.server:app --host 0.0.0.0 --port 8000
fi

print_heading "All done!"
