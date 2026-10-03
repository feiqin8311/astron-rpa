#!/bin/bash
# electron-builder afterInstall: $1 = install prefix
set -e

PREFIX="${1:-/opt/astron-rpa}"
PLUGIN_DIR="${PREFIX}/resources/browser-plugins"
POLICY_DIR="/etc/opt/chrome/policies/managed"
EDGE_POLICY_DIR="/etc/opt/edge/policies/managed"
EXT_DIR="/opt/google/chrome/extensions"
PLUGIN_ID="hklbenkcbnefkhgodegcoihmgoodlgod"

mkdir -p "$POLICY_DIR" "$EDGE_POLICY_DIR" "$EXT_DIR"

if [ -f "${PLUGIN_DIR}/policy.json" ]; then
  cp "${PLUGIN_DIR}/policy.json" "${POLICY_DIR}/astron-rpa.json"
  cp "${PLUGIN_DIR}/policy.json" "${EDGE_POLICY_DIR}/astron-rpa.json"
fi

CRX=""
for f in "${PLUGIN_DIR}"/chrome-*-${PLUGIN_ID}.crx; do
  if [ -f "$f" ]; then
    CRX="$f"
  fi
done

if [ -n "$CRX" ]; then
  VERSION=$(basename "$CRX" | sed -n "s/^chrome-\([0-9.]*\)-${PLUGIN_ID}\\.crx$/\\1/p")
  DEST_CRX="${EXT_DIR}/$(basename "$CRX")"
  cp "$CRX" "$DEST_CRX"
  cat > "${EXT_DIR}/${PLUGIN_ID}.json" <<EOF
{
  "external_crx": "${DEST_CRX}",
  "external_version": "${VERSION}"
}
EOF
fi

# Enable GNOME AT-SPI for the installing user when possible
if command -v gsettings >/dev/null 2>&1 && [ -n "${SUDO_USER:-}" ]; then
  su - "$SUDO_USER" -c 'gsettings set org.gnome.desktop.interface toolkit-accessibility true' >/dev/null 2>&1 || true
fi

# Ubuntu 24.04: Electron sandbox needs the SUID bit
if [ -f "${PREFIX}/chrome-sandbox" ]; then
  chmod 4755 "${PREFIX}/chrome-sandbox" || true
fi

exit 0
