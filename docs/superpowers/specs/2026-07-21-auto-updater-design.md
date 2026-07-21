# Auto-Updater Design

Date: 2026-07-21

## Goal

Detect a new release on GitHub, download it in the background, and swap +
relaunch the app on the new version — no browser, no manual unzip, no
reinstall wizard. Supports macOS, Windows, and Linux.

## Context / constraints

- App is a Python/Flask backend + pywebview native window, packaged per
  platform with PyInstaller (`vault.spec`, `vault_windows.spec`,
  `vault_linux.spec`), all `COLLECT`-based (onedir), not onefile.
- Distribution is portable, not installer-based: macOS `.app` (drag to
  `/Applications`), Windows and Linux ship as a plain zip/tar.gz folder the
  user extracts and runs directly. No admin/elevation involved anywhere.
- Releases are cut by `.github/workflows/release.yml` via
  `python-semantic-release`, tagged `v{version}`, matching
  `app.py:__version__`. Build job attaches one archive per OS to the GitHub
  Release:
  - `Vault-Authenticator-macOS.zip`
  - `Vault-Authenticator-Windows.zip`
  - `Vault-Authenticator-Linux.tar.gz`
- Repo is public (`justirva09/vault-authenticator`), so the GitHub Releases
  API can be hit unauthenticated for version checks — ample rate limit for
  one check per app launch.
- macOS builds are unsigned/not notarized (existing gap, out of scope to
  fix here) — downloaded archives carry the quarantine attribute, which
  would otherwise trigger a Gatekeeper block dialog on relaunch.

## Non-goals

- No installer, no admin-elevated install paths.
- No automatic rollback if the newly-swapped-in build fails to launch.
  Single-user local app — accepted risk for v1, not silently ignored.
- No periodic re-check while the app stays open; check happens once per
  launch only.
- No silent/fully-automatic download — user always clicks "Update" before
  any network transfer beyond the initial version check.

## Architecture overview

New `updater.py` module, stdlib only (`urllib.request`, `hashlib`,
`tempfile`, `subprocess`, `shutil` — no new pip dependency, keeps the
PyInstaller build unchanged).

`desktop.py` calls `updater.check_for_update(__version__)` a couple of
seconds after the window opens, in a background thread. It hits
`GET https://api.github.com/repos/justirva09/vault-authenticator/releases/latest`,
compares the returned `tag_name` (`vX.Y.Z`) against the running version, and
if newer, exposes the result through a new Flask route:

- `GET /api/update/status` → `{"available": bool, "version": "x.y.z"}`

Frontend polls this once on load (same pattern as the existing
`/api/status` polling) and shows a banner: `"vX.Y.Z available — Update"`.
No download happens until the user clicks it.

## Download + verify

Click "Update" → `POST /api/update/apply` kicks off a background thread:

1. Download the platform-matching asset (`Vault-Authenticator-{macOS,
   Windows,Linux}.{zip,tar.gz}`) from the release into a fresh temp dir.
2. Download `checksums.txt` (new release asset, see CI change below) and
   verify the SHA256 of the downloaded archive against it. Mismatch →
   abort, delete the temp download, leave the running app untouched, and
   surface an error banner ("Update failed, try again later").
3. Extract the archive into a temp "new version" folder.
   - macOS only: run `xattr -cr` on the extracted `.app` to clear the
     quarantine attribute so the relaunch doesn't hit Gatekeeper.

Frontend polls `GET /api/update/apply/status` for simple state:
`downloading → verifying → ready → applying`, with a download percentage
derived from the `Content-Length` header.

### CI change

`release.yml` build job gets one more step: after packaging each OS's
archive, compute its SHA256 and append to a shared `checksums.txt`, then
include it in the `softprops/action-gh-release` upload alongside the
existing `.zip`/`.tar.gz` files.

## Platform-specific swap + relaunch

App root = the folder holding the currently-running executable:

- macOS: the `.app` bundle itself.
- Windows: the `Vault Authenticator/` folder (containing `Vault
  Authenticator.exe` and its DLLs).
- Linux: the `vault-authenticator/` folder.

The swap keeps the exact same path so `/Applications` entries, taskbar
pins, and `.desktop` launchers keep working.

**macOS / Linux** — a running process's own executable file can be
renamed/replaced out from under it (the inode stays valid until the
process exits), so the current process can do this itself:

1. Rename the current app root aside (e.g. `.old-<pid>`).
2. Move the extracted new build into that now-vacated exact path.
3. Spawn the new executable as a detached process.
4. `shutil.rmtree` the renamed-aside old copy (best-effort, ignore
   errors).
5. Exit the current process.

**Windows** — the running `.exe` and its loaded DLLs are locked by the OS,
so the process can't overwrite or delete its own folder. Instead:

1. Write a small helper `.bat` to `%TEMP%` (generated at runtime).
2. Launch the helper as a detached process, then quit the main app.
3. Helper: retry-loop (with backoff) attempting to replace the app root
   with the pre-extracted new build — this only succeeds once the old
   process has fully released its file locks (i.e. after exit).
4. Launch the new `.exe`.
5. Delete itself and the temp new-build folder.

## Failure handling

All destructive steps (rename/replace of the live app root) happen only
after checksum verification and extraction have both succeeded. Any
failure before that point leaves the currently-running app completely
untouched and reports an error in the UI — no partial swap state.

## Testing

Unit-testable (no OS-level side effects):
- Version-comparison logic (`vX.Y.Z` string → tuple compare).
- Platform → asset-name mapping.
- Checksum verification against a mocked `checksums.txt` + file.

Not unit-testable, requires manual verification per platform: the actual
file swap + relaunch. Plan: cut a real test release one version ahead,
and on each of macOS/Windows/Linux confirm banner appears → download →
verify → swap → relaunch lands on the new version. This is called out
explicitly rather than assumed to work from unit tests alone.
