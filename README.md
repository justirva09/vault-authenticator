# Vault — Local Desktop Authenticator

[![GitHub Release](https://img.shields.io/github/v/release/justirva09/vault-authenticator)](https://github.com/justirva09/vault-authenticator/releases)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)

A simple, lightweight, self-hosted TOTP authenticator app for your desktop. Easily import your 2FA accounts directly from Google Authenticator's "Export accounts" QR code, view live refreshing codes locally, and keep your credentials completely offline — **nothing ever leaves your machine.**

> 🔒 **Security & Privacy Highlights**
> - **Zero Telemetry:** Listens on `127.0.0.1` only. No external requests or cloud dependencies.
> - **In-Browser QR Processing:** Webcam and image parsing happen locally in your browser.
> - **Encrypted at Rest:** Secrets are secured using PBKDF2 key derivation and Fernet (AES-256) encryption.
> - **Lightweight:** Built with Python and `pywebview`—no heavy Electron memory footprint.

---

## 📷 Preview

<p align="center">
  <img src="https://github.com/user-attachments/assets/0116e6af-c483-4847-a8a0-31a55732d077" width="30%" />
  <img src="https://github.com/user-attachments/assets/de4e66aa-7fab-43c5-b877-8ff9251fbb52" width="30%" />
  <img src="https://github.com/user-attachments/assets/b006ef19-b204-441b-b15e-6a6b7369815b" width="30%" />
</p>

<p align="center">
  <img src="https://github.com/user-attachments/assets/220ff5e4-aa81-455d-a7b6-403da5a9c590" width="60%" />
</p>

 

---

## 📋 Table of Contents
- [Quick Start (Python)](#-quick-start-python)
- [Native Desktop App Builds](#-native-desktop-app-builds)
  - [macOS](#macos)
  - [Windows](#windows)
  - [Linux](#linux)
- [Importing Accounts from Phone](#-importing-accounts-from-phone)
- [Day-to-Day Usage](#-day-to-day-usage)
- [Data Storage & Security](#-data-storage--security)
- [Contributing & Release Workflow](#-contributing--release-workflow)
- [Limitations](#-limitations)

---

## 🚀 Quick Start (Python)

If you prefer running directly from source:

**Prerequisites:** Python 3.9+

```bash
# 1. Clone & enter repository
git clone https://github.com/justirva09/vault-authenticator.git
cd vault-authenticator

# 2. Set up virtual environment
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

# 3. Install dependencies & run
pip install -r requirements.txt
python3 app.py
```

Open **`http://127.0.0.1:5057`** in your browser. 

*On first launch, you will set a **Master Password**. This encrypts your vault. Note: There is no password recovery!*

---

## 💻 Native Desktop App Builds

If you prefer a standalone, double-clickable app window without using the terminal, you can build a native bundle. Desktop builds use [pywebview](https://pywebview.flowrl.com/) to render the local interface in a native window.

*Note: Cross-compilation is not supported by PyInstaller; build on the target platform.*

### macOS
```bash
chmod +x build_mac_app.sh
./build_mac_app.sh
```
- **Output:** `dist/Vault Authenticator.app` (Drag to `/Applications`).
- **First Run:** Right-click the app → **Open** → **Open** to bypass unsigned Gatekeeper warnings.
- **Data Path:** `~/Library/Application Support/Vault Authenticator/`

### Windows
```cmd
build_windows_app.bat
```
- **Output:** `dist\Vault Authenticator\Vault Authenticator.exe`.
- **Prerequisites:** Requires Microsoft Edge WebView2 Runtime (pre-installed on modern Windows 10/11).
- **First Run:** If SmartScreen appears, click **More info** → **Run anyway**.
- **Data Path:** `%APPDATA%\Vault Authenticator\`

### Linux
```bash
chmod +x build_linux_app.sh
./build_linux_app.sh
```
- **Prerequisites:** Requires a web rendering backend (`webkit2gtk` or `PyQtWebEngine`). The script will prompt if GTK is missing.
- **Output:** `dist/vault-authenticator/` (Optionally installs a desktop shortcut to `~/.local/share/applications/`).
- **Data Path:** `$XDG_DATA_HOME/vault-authenticator/`

---

## 📲 Importing Accounts from Phone

Vault natively parses Google Authenticator export QR payloads (`otpauth-migration://`):

1. Open **Google Authenticator** on your phone.
2. Tap **Menu (⋮)** → **Transfer accounts** → **Export accounts**.
3. Select your accounts to generate the export QR code(s).
4. In Vault, click **Import codes**, then choose:
   - 📷 **Scan with camera:** Hold your phone's screen up to your computer's webcam.
   - 🖼️ **Upload image:** Take a screenshot of the QR code and upload/drag it into Vault.
5. Review the parsed accounts and click **Add to vault**.

*> **Note:** Exporting does **not** delete codes from your phone. You can use both simultaneously.*

---

## ⚙️ Day-to-Day Usage

- **Copying Codes:** Click any live 6-digit code to copy it directly to your clipboard.
- **Locking Vault:** Click **Lock** at any time to re-seal your encrypted vault.
- **Multiple Exports:** If Google Authenticator generates multiple QR codes, you can scan/upload them sequentially.

---

## 🔐 Data Storage & Security

- **Storage Location:** All encrypted data resides in `data/vault.enc`. Metadata resides in `data/meta.json`.
- **Encryption:** Master password derives a key using **PBKDF2**, which encrypts the vault contents via **Fernet (AES-256)**.
- **Resetting:** Deleting `data/vault.enc` and `data/meta.json` completely resets the application to its initial state.

---

## 🤖 Contributing & Release Workflow

We use automated release management via GitHub Actions:

- **Conventional Commits Required:** Push to `main` triggers `.github/workflows/release.yml`.
  - `fix: ...` → Triggers **Patch** bump (`0.1.0` → `0.1.1`)
  - `feat: ...` → Triggers **Minor** bump (`0.1.0` → `0.2.0`)
  - `feat!: ...` or `BREAKING CHANGE:` → Triggers **Major** bump (`0.1.0` → `1.0.0`)
- **Automated Builds:** Once a release tag is pushed, CI automatically builds macOS, Windows, and Linux binaries and attaches them as ZIP files to the GitHub Release.

---

## ⚠️ Limitations & Notes

- **Network Scope:** Designed strictly as a local utility. The Flask app binds to `127.0.0.1` by default. Do not expose this port to public networks.
- **Password Recovery:** There is no master password reset mechanism. If forgotten, encrypted data cannot be recovered.
- **Code Signing:** Binary builds are unsigned. OS security prompts on first launch are expected for self-built applications.
