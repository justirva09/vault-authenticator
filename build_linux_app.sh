#!/bin/bash
# Builds Vault Authenticator into a native Linux app + installs a desktop
# menu entry with icon. Run from inside the totp-desktop folder:
#   chmod +x build_linux_app.sh
#   ./build_linux_app.sh
set -e

cd "$(dirname "$0")"

# pywebview needs a native web-rendering backend on Linux: either GTK
# (webkit2gtk, installed via your system package manager) or Qt (PyQtWebEngine,
# installable via pip). Check for GTK first since it's lighter; fall back to
# telling the user how to get one or the other.
HAS_GTK=0
python3 -c "import gi; gi.require_version('WebKit2', '4.1')" 2>/dev/null && HAS_GTK=1
if [ "$HAS_GTK" = "0" ]; then
  python3 -c "import gi; gi.require_version('WebKit2', '4.0')" 2>/dev/null && HAS_GTK=1
fi

if [ "$HAS_GTK" = "0" ]; then
  echo "No GTK WebKit backend found."
  echo "Install one of the following before continuing:"
  echo "  Debian/Ubuntu: sudo apt install python3-gi gir1.2-webkit2-4.1"
  echo "  Fedora:        sudo dnf install python3-gobject webkit2gtk4.1"
  echo "  Arch:          sudo pacman -S python-gobject webkit2gtk"
  echo ""
  echo "Alternatively, this script can install the Qt backend via pip instead"
  echo "(no system packages needed, but a larger download)."
  read -p "Install PyQt5 + PyQtWebEngine via pip instead? [y/N] " REPLY
  if [[ "$REPLY" =~ ^[Yy]$ ]]; then
    USE_QT=1
  else
    echo "Install a GTK backend and re-run this script."
    exit 1
  fi
fi

if [ ! -d venv ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv --system-site-packages
fi

source venv/bin/activate
echo "Installing dependencies..."
pip install -q -r requirements.txt

if [ "$USE_QT" = "1" ]; then
  pip install -q PyQt5 PyQtWebEngine
fi

echo "Building app..."
rm -rf build dist
pyinstaller vault_linux.spec

echo ""
echo "Done. Your app is at:"
echo "  $(pwd)/dist/vault-authenticator/"
echo ""

read -p "Install a desktop menu entry (so it shows up with an icon in your app launcher)? [Y/n] " REPLY
if [[ ! "$REPLY" =~ ^[Nn]$ ]]; then
  INSTALL_DIR="$HOME/.local/share/vault-authenticator"
  mkdir -p "$INSTALL_DIR"
  cp -r dist/vault-authenticator/* "$INSTALL_DIR/"
  cp icon/icon_1024.png "$INSTALL_DIR/icon_1024.png"

  mkdir -p "$HOME/.local/share/applications"
  sed "s#%INSTALL_DIR%#$INSTALL_DIR#g" icon/vault-authenticator.desktop \
    > "$HOME/.local/share/applications/vault-authenticator.desktop"
  chmod +x "$HOME/.local/share/applications/vault-authenticator.desktop"

  echo "Installed to $INSTALL_DIR"
  echo "Look for 'Vault Authenticator' in your application launcher."
  echo "(If it doesn't show up immediately, log out/in or run: update-desktop-database ~/.local/share/applications)"
else
  echo "You can run it directly with: $(pwd)/dist/vault-authenticator/vault-authenticator"
fi
