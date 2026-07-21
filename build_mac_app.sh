#!/bin/bash
# Builds Vault Authenticator into a double-clickable macOS .app.
# Run this from inside the totp-desktop folder:
#   chmod +x build_mac_app.sh
#   ./build_mac_app.sh
set -e

cd "$(dirname "$0")"

if [ ! -d venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi

source venv/bin/activate
echo "Installing dependencies..."
pip install -q -r requirements.txt

echo "Building app bundle..."
rm -rf build dist
pyinstaller vault.spec

echo ""
echo "Done. Your app is at:"
echo "  $(pwd)/dist/Vault Authenticator.app"
echo ""
echo "Drag it into /Applications, then just double-click it to launch."
