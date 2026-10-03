#!/usr/bin/env bash
# =============================================================================
# AstronRPA Client Build Script (macOS / Linux)
# =============================================================================

set -euo pipefail

# Save script directory path
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$SCRIPT_DIR"

# =============================================================================
# 1. Argument Parsing & Help
# =============================================================================

PYTHON_DIR=""
SKIP_ENGINE=0
SKIP_FRONTEND=0

show_help() {
  cat << 'EOF'

Usage: ./build.sh [options]

Options:
  --python-dir, -p <path>   Specify Python installation directory (must contain bin/python3)
  --python-exe <path>       Alias for --python-dir (path to directory or executable)
  --skip-engine             Skip engine (Python) build
  --skip-frontend           Skip frontend build
  --help, -h                Display this help message

Environment variables:
  PYTHON_VERSION            Python version to install via uv (default: 3.13)
  PIP_INDEX_URL             PyPI index URL (default: https://pypi.tuna.tsinghua.edu.cn/simple)

Examples:
  ./build.sh
  ./build.sh --skip-frontend
  ./build.sh --skip-engine
  ./build.sh -p "/path/to/cpython-3.13-root"

EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --python-dir|-p|--python-exe)
      if [[ $# -lt 2 || "$2" =~ ^-- ]]; then
        echo "Error: $1 requires a path argument" >&2
        exit 1
      fi
      PYTHON_DIR="$2"
      shift 2
      ;;
    --skip-engine)
      SKIP_ENGINE=1
      shift
      ;;
    --skip-frontend)
      SKIP_FRONTEND=1
      shift
      ;;
    --help|-h)
      show_help
      exit 0
      ;;
    *)
      echo "Unknown parameter: $1" >&2
      show_help
      exit 1
      ;;
  esac
done

# =============================================================================
# 2. Configuration & Defaults
# =============================================================================

: "${PYTHON_VERSION:=3.13}"
: "${PIP_INDEX_URL:=https://pypi.tuna.tsinghua.edu.cn/simple}"

ENGINE_DIR="$SCRIPT_DIR/engine"
BUILD_DIR="$SCRIPT_DIR/build"
PYTHON_CORE_DIR="$BUILD_DIR/python_core"
DIST_DIR="$BUILD_DIR/dist"
WHEEL_REQUIREMENTS="$BUILD_DIR/requirements.txt"
ARCHIVE_DIST_DIR="$SCRIPT_DIR/resources"
BACKUP_FILE="$ENGINE_DIR/pyproject.toml.backup"

# electron-builder mac extraResources reads resources/${arch}/python_core.tar.gz
# (arch is arm64 / x64). Linux extraFiles still copies resources/python_core.tar.gz.
HOST_OS="$(uname -s)"
HOST_MACHINE="$(uname -m)"
case "$HOST_MACHINE" in
  arm64|aarch64) HOST_MAC_ARCH="arm64" ;;
  x86_64|amd64)  HOST_MAC_ARCH="x64" ;;
  *)             HOST_MAC_ARCH="$HOST_MACHINE" ;;
esac
if [[ "$HOST_OS" == Darwin* ]]; then
  ARCHIVE_ARCH_DIR="$ARCHIVE_DIST_DIR/$HOST_MAC_ARCH"
else
  ARCHIVE_ARCH_DIR="$ARCHIVE_DIST_DIR"
fi
ARCHIVE_FILE="$ARCHIVE_ARCH_DIR/python_core.tar.gz"
HASH_FILE="$ARCHIVE_ARCH_DIR/python_core.tar.gz.sha256.txt"

# =============================================================================
# 3. Environment Checks
# =============================================================================

if [[ "$SKIP_ENGINE" -eq 1 && "$SKIP_FRONTEND" -eq 1 ]]; then
  echo "Error: Cannot skip both engine and frontend builds" >&2
  exit 1
fi

if [[ "$SKIP_ENGINE" -eq 0 ]]; then
  if ! command -v uv >/dev/null 2>&1; then
    echo "Error: uv not found. Please install uv first (https://docs.astral.sh/uv/) and ensure uv is in PATH" >&2
    exit 1
  fi

  if ! command -v tar >/dev/null 2>&1; then
    echo "Error: tar command not found" >&2
    exit 1
  fi

  if ! command -v shasum >/dev/null 2>&1 && ! command -v sha256sum >/dev/null 2>&1; then
    echo "Error: neither shasum nor sha256sum found in PATH" >&2
    exit 1
  fi
fi

if [[ "$SKIP_FRONTEND" -eq 0 ]]; then
  if ! command -v node >/dev/null 2>&1; then
    echo "Error: node not found. Please install Node.js (>= 22)" >&2
    exit 1
  fi

  if ! command -v pnpm >/dev/null 2>&1; then
    echo "Error: pnpm not found. Please install pnpm first: npm install -g pnpm" >&2
    exit 1
  fi
fi

# Trap to guarantee engine/pyproject.toml is restored on error or exit
restore_pyproject() {
  if [[ -f "$BACKUP_FILE" ]]; then
    echo "Restoring engine/pyproject.toml from backup..."
    mv -f "$BACKUP_FILE" "$ENGINE_DIR/pyproject.toml"
  fi
}

cleanup() {
  local exit_code=$?
  trap - EXIT INT TERM HUP
  restore_pyproject
  exit "$exit_code"
}

trap cleanup EXIT INT TERM HUP

# =============================================================================
# 4. Engine Build
# =============================================================================

if [[ "$SKIP_ENGINE" -eq 1 ]]; then
  echo ""
  echo "============================================"
  echo "Engine Build Skipped"
  echo "============================================"
else
  echo ""
  echo "============================================"
  echo "Starting Engine Build"
  echo "============================================"

  # ---------------------------------------------------------------------------
  # 4.1. Environment Setup
  # ---------------------------------------------------------------------------
  echo "Cleaning dist directory..."
  rm -rf "$DIST_DIR"

  echo "Cleaning requirements.txt..."
  rm -f "$WHEEL_REQUIREMENTS"

  if [[ -f "$BACKUP_FILE" ]]; then
    echo "Found leftover backup file, restoring engine/pyproject.toml..."
    mv -f "$BACKUP_FILE" "$ENGINE_DIR/pyproject.toml"
  fi

  echo "Creating build directory structure..."
  mkdir -p "$BUILD_DIR" "$DIST_DIR" "$ARCHIVE_ARCH_DIR"

  # Locate or install Python
  if [[ -n "$PYTHON_DIR" ]]; then
    if [[ -f "$PYTHON_DIR" && "$(basename "$PYTHON_DIR")" =~ ^python ]]; then
      PYTHON_SOURCE_ROOT="$(cd "$(dirname "$PYTHON_DIR")/.." && pwd -P)"
    elif [[ -d "$PYTHON_DIR" && -f "$PYTHON_DIR/bin/python3" ]]; then
      PYTHON_SOURCE_ROOT="$(cd "$PYTHON_DIR" && pwd -P)"
    elif [[ -d "$PYTHON_DIR" && -f "$PYTHON_DIR/python3" ]]; then
      PYTHON_SOURCE_ROOT="$(cd "$PYTHON_DIR/.." && pwd -P)"
    else
      echo "Error: Specified Python directory '$PYTHON_DIR' does not contain bin/python3" >&2
      exit 1
    fi
  else
    echo "Ensuring Python $PYTHON_VERSION is installed via uv..."
    uv python install "$PYTHON_VERSION"
    MANAGED_PY_EXE="$(uv python find --managed-python "$PYTHON_VERSION")"
    if [[ -z "$MANAGED_PY_EXE" || ! -f "$MANAGED_PY_EXE" ]]; then
      echo "Error: Failed to locate uv-managed Python $PYTHON_VERSION" >&2
      exit 1
    fi
    PYTHON_SOURCE_ROOT="$(cd "$(dirname "$MANAGED_PY_EXE")/.." && pwd -P)"
  fi

  if [[ ! -f "$PYTHON_SOURCE_ROOT/bin/python3" ]]; then
    echo "Error: Python executable not found at '$PYTHON_SOURCE_ROOT/bin/python3'" >&2
    exit 1
  fi

  echo "Using Python source root: $PYTHON_SOURCE_ROOT"
  echo "Copying Python environment to build/python_core..."
  rm -rf "$PYTHON_CORE_DIR"
  mkdir -p "$PYTHON_CORE_DIR"
  cp -R -P "$PYTHON_SOURCE_ROOT/." "$PYTHON_CORE_DIR/"
  echo "Python environment copied successfully"

  # Remove EXTERNALLY-MANAGED marker if present so uv pip can install into it
  echo "Checking for EXTERNALLY-MANAGED marker..."
  find "$PYTHON_CORE_DIR" -name "EXTERNALLY-MANAGED" -type f -exec rm -f {} +

  # ---------------------------------------------------------------------------
  # 4.2. Build Packages
  # ---------------------------------------------------------------------------
  echo "Backing up original engine/pyproject.toml..."
  cp "$ENGINE_DIR/pyproject.toml" "$BACKUP_FILE"

  echo "Building workspace members list..."
  WORKSPACE_MEMBERS=()

  for d in "$ENGINE_DIR"/shared/*; do
    if [[ -d "$d" && -f "$d/pyproject.toml" ]]; then
      WORKSPACE_MEMBERS+=("\"shared/$(basename "$d")\"")
    fi
  done

  for d in "$ENGINE_DIR"/servers/*; do
    if [[ -d "$d" && -f "$d/pyproject.toml" ]]; then
      WORKSPACE_MEMBERS+=("\"servers/$(basename "$d")\"")
    fi
  done

  for d in "$ENGINE_DIR"/components/*; do
    if [[ -d "$d" && -f "$d/pyproject.toml" ]]; then
      base="$(basename "$d")"
      if [[ "$base" != "astronverse-database" ]]; then
        WORKSPACE_MEMBERS+=("\"components/$base\"")
      fi
    fi
  done

  if [[ ${#WORKSPACE_MEMBERS[@]} -eq 0 ]]; then
    echo "Warning: No valid workspace members found"
    MEMBERS_STRING='""'
  else
    printf -v MEMBERS_STRING '%s, ' "${WORKSPACE_MEMBERS[@]}"
    MEMBERS_STRING="${MEMBERS_STRING%, }"
  fi

  {
    echo ""
    echo "[tool.uv.workspace]"
    echo "members = [$MEMBERS_STRING]"
  } >> "$ENGINE_DIR/pyproject.toml"

  echo "Starting batch build of all packages..."
  (
    cd "$ENGINE_DIR"
    uv build --all-packages --wheel -o "$DIST_DIR"
  )
  restore_pyproject
  echo "All packages built successfully"

  # ---------------------------------------------------------------------------
  # 4.3. Install Packages
  # ---------------------------------------------------------------------------
  echo "Generating requirements.txt from built packages..."
  echo "# Generated requirements from local wheels" > "$WHEEL_REQUIREMENTS"
  for whl in "$DIST_DIR"/*.whl; do
    if [[ -f "$whl" ]]; then
      echo "file://$whl" >> "$WHEEL_REQUIREMENTS"
    fi
  done

  echo "Installing packages into build/python_core..."
  uv pip install --link-mode=copy \
    --python "$PYTHON_CORE_DIR/bin/python3" \
    --find-links "$DIST_DIR" \
    -r "$WHEEL_REQUIREMENTS" \
    -i "$PIP_INDEX_URL"
  echo "Batch installation successful"

  # ---------------------------------------------------------------------------
  # 4.4. Package and Release
  # ---------------------------------------------------------------------------
  echo "Compressing python_core directory..."
  rm -f "$ARCHIVE_FILE" "$HASH_FILE"
  tar -czf "$ARCHIVE_FILE" -C "$PYTHON_CORE_DIR" .
  echo "python_core compressed successfully: $ARCHIVE_FILE"

  echo "Generating SHA-256 hash..."
  if command -v sha256sum >/dev/null 2>&1; then
    sha256_hash="$(sha256sum "$ARCHIVE_FILE" | awk '{print $1}')"
  elif command -v shasum >/dev/null 2>&1; then
    sha256_hash="$(shasum -a 256 "$ARCHIVE_FILE" | awk '{print $1}')"
  else
    echo "Error: Neither sha256sum nor shasum available" >&2
    exit 1
  fi

  printf "%s\n" "$sha256_hash" > "$HASH_FILE"
  echo "Hash file generated: $HASH_FILE"

  echo ""
  echo "============================================"
  echo "Engine Build Complete!"
  echo "============================================"
fi

# =============================================================================
# 5. Frontend Build
# =============================================================================

if [[ "$SKIP_FRONTEND" -eq 1 ]]; then
  echo ""
  echo "============================================"
  echo "Frontend Build Skipped"
  echo "============================================"
else
  echo ""
  echo "============================================"
  echo "Starting Frontend Build"
  echo "============================================"

  echo "Checking pnpm installation..."
  pnpm --version >/dev/null 2>&1
  echo "pnpm check passed"

  FRONTEND_DIR="$SCRIPT_DIR/frontend"
  echo "Navigating to frontend directory: $FRONTEND_DIR"
  if [[ ! -d "$FRONTEND_DIR" ]]; then
    echo "Frontend directory not found: $FRONTEND_DIR" >&2
    exit 1
  fi

  if [[ ! -f "$FRONTEND_DIR/package.json" ]]; then
    echo "ERROR: package.json not found in frontend directory" >&2
    exit 1
  fi

  (
    cd "$FRONTEND_DIR"
    echo "Installing frontend dependencies..."
    pnpm install

    OS_NAME="$(uname -s)"
    case "$OS_NAME" in
      Darwin*)
        ELECTRON_ARCH_FLAGS=()
        if [[ -f "$SCRIPT_DIR/resources/arm64/python_core.tar.gz" ]]; then
          ELECTRON_ARCH_FLAGS+=(--arm64)
        fi
        if [[ -f "$SCRIPT_DIR/resources/x64/python_core.tar.gz" ]]; then
          ELECTRON_ARCH_FLAGS+=(--x64)
        fi
        if [[ ${#ELECTRON_ARCH_FLAGS[@]} -eq 0 ]]; then
          echo "Error: no resources/<arch>/python_core.tar.gz found (arm64 or x64)." >&2
          echo "Run ./build.sh without --skip-engine first, or copy the matching archive from another Mac." >&2
          exit 1
        fi
        echo "Building desktop application (build:mac ${ELECTRON_ARCH_FLAGS[*]})..."
        pnpm --filter astron-rpa run build
        pnpm --filter astron-rpa exec electron-builder --mac "${ELECTRON_ARCH_FLAGS[@]}"
        ;;
      Linux*)
        echo "Building desktop application (build:linux)..."
        pnpm --filter astron-rpa run build:linux
        ;;
      *)
        echo "Warning: Unknown OS $OS_NAME, defaulting to build:mac" >&2
        echo "Building desktop application (build:mac)..."
        pnpm --filter astron-rpa run build:mac
        ;;
    esac
  )

  echo "Frontend build completed successfully"
fi

# =============================================================================
# 6. Summary
# =============================================================================

echo ""
echo "============================================"
if [[ "$SKIP_ENGINE" -eq 0 && "$SKIP_FRONTEND" -eq 0 ]]; then
  echo "Full Build Complete!"
elif [[ "$SKIP_ENGINE" -eq 0 ]]; then
  echo "Engine Build Complete!"
else
  echo "Frontend Build Complete!"
fi
echo "============================================"
echo ""
echo "Installation package location:"
if [[ "$SKIP_FRONTEND" -eq 0 ]]; then
  echo "  Frontend installer: frontend/packages/electron-app/dist/"
fi
if [[ "$SKIP_ENGINE" -eq 0 ]]; then
  echo "  Engine core archive: $ARCHIVE_FILE"
  echo "  SHA-256 hash file:   $HASH_FILE"
fi
echo ""
