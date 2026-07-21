# Vault — a local desktop authenticator

A simple, self-hosted TOTP authenticator app for your computer. Import your
accounts straight from the Google Authenticator "Export accounts" QR code
(scan with your webcam or upload a screenshot), then view live, refreshing
codes locally — nothing ever leaves your machine.

## What this is

- A small Flask web app you run locally and open in your browser
- QR scanning happens **in the browser** (webcam or uploaded image), so no
  code or secret ever needs to touch a server beyond `127.0.0.1`
- All account secrets are encrypted at rest with a master password you choose
  (PBKDF2 + Fernet/AES) — the password is never stored, only a derived key
- Nothing is sent to the internet. This never talks to any external service.

## Setup

Requires Python 3.9+.

```bash
cd totp-desktop
python3 -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python3 app.py
```

Then open **http://127.0.0.1:5057** in your browser.

The first time you run it, you'll be asked to set a master password — this
encrypts everything stored in `data/vault.enc`. There's no password recovery,
so keep it somewhere safe (a password manager is a good place).

## Building a native desktop app (no terminal, no browser)

If you don't want to open a terminal and run `python3 app.py` every time,
you can build this into a real, double-clickable desktop app on macOS,
Windows, or Linux. All three use [pywebview](https://pywebview.flowrl.com/)
to open the same local Flask server in its own native window — nothing
changes about where your data lives or leaves your machine, and the build
must be run separately on each OS (PyInstaller can't cross-compile).

### macOS

```bash
cd totp-desktop
chmod +x build_mac_app.sh
./build_mac_app.sh
```

Creates `dist/Vault Authenticator.app`. Drag it into `/Applications`.

- First launch: macOS Gatekeeper will block it since it isn't
  notarized/signed. Right-click the app → **Open** → **Open** to approve
  it once.
- Vault data lives in `~/Library/Application Support/Vault Authenticator/`.

### Windows

```bat
cd totp-desktop
build_windows_app.bat
```

Creates `dist\Vault Authenticator\Vault Authenticator.exe`. Make a
shortcut to it (or move the whole `Vault Authenticator` folder anywhere —
just keep the `.exe` together with its folder).

- Needs the Microsoft Edge WebView2 Runtime, which is already installed on
  current Windows 10/11. If it's somehow missing, Windows will prompt to
  install it.
- Windows SmartScreen will likely warn about an unrecognized app on first
  launch — click **More info** → **Run anyway**.
- Vault data lives in `%APPDATA%\Vault Authenticator\`.

### Linux

```bash
cd totp-desktop
chmod +x build_linux_app.sh
./build_linux_app.sh
```

pywebview needs a web-rendering backend on Linux — either GTK
(`webkit2gtk`, install via your distro's package manager) or Qt
(`PyQtWebEngine`, pip-installable). The script checks for GTK and offers to
install the Qt fallback via pip if it's missing.

Creates `dist/vault-authenticator/` and optionally installs a desktop menu
entry (with icon) to `~/.local/share/applications/`.

- Vault data lives in `$XDG_DATA_HOME/vault-authenticator/` (usually
  `~/.local/share/vault-authenticator/`).

### Common notes (all platforms)

- Camera QR scanning requires granting camera permission the first time
  you use it; **Upload image** always works as a fallback if that's easier.
- Rebuilding after you change code: just re-run the build script for your
  OS — it reuses the existing `venv` and rebuilds from scratch.
- None of these builds are code-signed (that requires a paid developer
  account on macOS/Windows), so you'll see an OS security warning on first
  launch — that's expected for a self-built app, not a sign of anything
  wrong.

## Versioning & releases (for contributors)

Version bumps and GitHub Releases are fully automated — you never edit the
version number by hand. `.github/workflows/release.yml` runs on every push
to `main`:

1. **Determine the version bump.** [python-semantic-release](https://python-semantic-release.readthedocs.io/)
   scans commit messages since the last release using [Conventional Commits](https://www.conventionalcommits.org/):
   - `fix: ...` → patch bump (`0.1.0` → `0.1.1`)
   - `feat: ...` → minor bump (`0.1.0` → `0.2.0`)
   - `feat!: ...` or a `BREAKING CHANGE:` footer → major bump (`0.1.0` → `1.0.0`)
   - `docs:`, `chore:`, `ci:`, `style:`, `refactor:`, `test:` → no release by
     themselves (no version bump, workflow stops there)
2. If a bump is warranted, it updates `app.py:__version__`, appends to
   `CHANGELOG.md`, commits, tags (`vX.Y.Z`), and creates a GitHub Release.
3. The build job then compiles the macOS/Windows/Linux apps from that exact
   tagged commit and attaches them to the release as downloadable zips.

If your commit message doesn't follow this convention, nothing gets
released — that push just sits on `main` with no version bump, which is
safe (not an error).

Examples:
```
feat: add search box to filter accounts
fix: prevent duplicate camera dialogs on macOS
feat!: change vault file format (breaking, needs migration)
```

## Importing your accounts from your phone

1. On your phone, open **Google Authenticator**
2. Tap the menu (⋮) → **Transfer accounts** → **Export accounts**
3. Select the accounts you want to move, and Google Authenticator will show
   you a QR code
4. In Vault, click **Import codes**, then either:
   - **Scan with camera** — hold your phone's QR code up to your webcam, or
   - **Upload image** — take a screenshot of the QR code on your phone and
     drag it in
5. Review the accounts found, then click **Add to vault**

You can repeat this for as many export QR codes as Google Authenticator shows
you (it batches accounts into multiple QR codes if you have a lot).

Note: exporting from Google Authenticator does **not** remove them from your
phone, so your phone keeps working as normal — this just gives you a second
place to view codes.

## Using it day to day

- Each account card shows a live 6-digit code with a countdown ring
- Click a code to copy it to your clipboard
- Click **Lock** any time to re-lock the vault (you'll need your master
  password again to view codes)

## Where your data lives

Everything is stored locally in `data/vault.enc`, encrypted. If you delete
that file (and `data/meta.json`), the app resets to first-run setup.

## Limitations / things to know

- This is a local dev-server style app meant for personal/local use, not for
  exposing to a network — it binds to `127.0.0.1` only by default; don't
  change that unless you understand the implications
- Camera access requires your OS/browser to grant webcam permission to the
  page (you'll be prompted)
- If you ever forget your master password, there is no recovery — you'd need
  to delete `data/vault.enc` and `data/meta.json` and re-import from your
  phone
