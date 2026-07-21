# Auto-Updater Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect a newer GitHub release on startup, download and checksum-verify it in the background, then swap the running build for the new one and relaunch automatically — on macOS, Windows, and Linux.

**Architecture:** A new stdlib-only `updater.py` module owns version-check / download / verify / platform-specific swap-and-relaunch logic. Three Flask routes in `app.py` expose it to the existing frontend (`check`, `status`, `apply`), which already polls similarly-shaped endpoints. The frontend gets a small banner in `templates/index.html` / `static/app.js` / `static/style.css`. CI (`release.yml`) gets one more step per platform to publish a SHA256 checksum file per archive.

**Tech Stack:** Python 3 stdlib (`urllib.request`, `hashlib`, `zipfile`, `tarfile`, `subprocess`, `threading`) — no new runtime pip dependency. `pytest` added as a dev/test-only dependency (no test suite exists yet in this repo). Vanilla JS/Flask, matching the existing frontend.

## Global Constraints

- No new pip dependency for the shipped app — `updater.py` uses only the Python standard library, so the PyInstaller build is unaffected. (Spec: "stdlib only".)
- Distribution stays portable, no installer, no elevated paths — the swap must happen at the exact path the app already lives at (`.app` bundle / `Vault Authenticator/` folder / `vault-authenticator/` folder), so `/Applications` entries, taskbar pins, and `.desktop` launchers keep working. (Spec: "Platform-specific swap + relaunch".)
- Update check happens once per launch only, never periodic. No download starts until the user clicks "Update" in the banner. (Spec: "Non-goals".)
- No auto-rollback if the newly-swapped build fails to launch — accepted risk for v1, single-user local app. (Spec: "Non-goals".)
- All destructive steps (renaming/replacing the live app root) happen only after checksum verification and extraction both succeed. (Spec: "Failure handling".)
- **Deviation from the committed spec, documented here:** the spec describes a single shared `checksums.txt` release asset. `release.yml`'s build job is a 3-way OS matrix where each leg runs in parallel and uploads to the *same* GitHub Release — if all three legs uploaded a same-named `checksums.txt`, they'd race and the release would end up with only one platform's line. This plan instead publishes one `<archive-filename>.sha256` file per archive (e.g. `Vault-Authenticator-macOS.zip.sha256`), which sidesteps the collision entirely while verifying the exact same thing per-asset.

---

## Task 1: Core updater module (`updater.py`)

**Files:**
- Create: `updater.py`
- Create: `tests/conftest.py`
- Create: `tests/test_updater.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces (used by Task 2):
  - `updater.get_status() -> dict` — JSON-safe: `{"phase": str, "current_version": str|None, "latest_version": str|None, "percent": int, "error": str|None}`. `phase` is one of `idle | checking | available | downloading | verifying | applying | error`.
  - `updater.check_for_update(current_version: str) -> None` — synchronous; meant to be run in a background thread by the caller. Updates internal status.
  - `updater.start_apply() -> None` — spawns its own background thread that runs the full download→verify→swap→relaunch pipeline, updating status as it goes. Never returns on success (process exits via `os._exit(0)`); returns normally after setting `phase="error"` on failure.

- [ ] **Step 1: Write the test suite and its scaffolding first**

Create `tests/conftest.py`:

```python
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
```

(Without this, pytest inserts `tests/` itself onto `sys.path`, not the repo root — `import updater` would otherwise fail to find `updater.py`, which lives at the repo root.)

Create `tests/test_updater.py`:

```python
import hashlib
import json
import sys
import tarfile
import zipfile
from unittest.mock import patch

import pytest

import updater


def test_parse_version_basic():
    assert updater._parse_version("v1.2.3") == (1, 2, 3)
    assert updater._parse_version("2.0.0") == (2, 0, 0)


def test_parse_version_short():
    assert updater._parse_version("v1.2") == (1, 2, 0)


def test_parse_version_ordering():
    assert updater._parse_version("v1.10.0") > updater._parse_version("v1.9.9")


class _FakeResponse:
    def __init__(self, body, headers=None):
        self._body = body
        self.headers = headers or {}

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_check_for_update_detects_newer_version():
    payload = json.dumps({
        "tag_name": "v9.9.9",
        "assets": [
            {"name": "Vault-Authenticator-macOS.zip", "browser_download_url": "http://x/mac.zip"},
            {"name": "Vault-Authenticator-macOS.zip.sha256", "browser_download_url": "http://x/mac.sha256"},
        ],
    }).encode("utf-8")

    with patch("updater.urllib.request.urlopen", return_value=_FakeResponse(payload)):
        updater.check_for_update("0.1.0")

    status = updater.get_status()
    assert status["phase"] == "available"
    assert status["latest_version"] == "9.9.9"
    assert updater._latest_assets["Vault-Authenticator-macOS.zip"] == "http://x/mac.zip"


def test_check_for_update_no_newer_version():
    payload = json.dumps({"tag_name": "v0.1.0", "assets": []}).encode("utf-8")
    with patch("updater.urllib.request.urlopen", return_value=_FakeResponse(payload)):
        updater.check_for_update("0.1.0")
    assert updater.get_status()["phase"] == "idle"


def test_check_for_update_network_error_sets_error_phase():
    with patch("updater.urllib.request.urlopen", side_effect=OSError("no network")):
        updater.check_for_update("0.1.0")
    status = updater.get_status()
    assert status["phase"] == "error"
    assert "no network" in status["error"]


def test_sha256_of(tmp_path):
    f = tmp_path / "file.bin"
    f.write_bytes(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert updater._sha256_of(str(f)) == expected


def test_expected_checksum_finds_matching_line():
    text = "abc123  Vault-Authenticator-macOS.zip\ndef456  Vault-Authenticator-Windows.zip\n"
    assert updater._expected_checksum(text, "Vault-Authenticator-macOS.zip") == "abc123"
    assert updater._expected_checksum(text, "missing.zip") is None


def test_extract_zip(tmp_path):
    archive = tmp_path / "a.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("MyApp/inner.txt", "hi")
    dest = tmp_path / "out"
    updater._extract(str(archive), str(dest))
    assert (dest / "MyApp" / "inner.txt").read_text() == "hi"


def test_extract_tar(tmp_path):
    inner = tmp_path / "inner.txt"
    inner.write_text("hi")
    archive = tmp_path / "a.tar.gz"
    with tarfile.open(archive, "w:gz") as t:
        t.add(str(inner), arcname="myapp/inner.txt")
    dest = tmp_path / "out"
    updater._extract(str(archive), str(dest))
    assert (dest / "myapp" / "inner.txt").read_text() == "hi"


def test_extracted_root_single_entry(tmp_path):
    (tmp_path / "MyApp.app").mkdir()
    assert updater._extracted_root(str(tmp_path)) == str(tmp_path / "MyApp.app")


def test_extracted_root_rejects_multiple_entries(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with pytest.raises(RuntimeError):
        updater._extracted_root(str(tmp_path))


def test_current_app_root_macos(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "darwin")
    monkeypatch.setattr(
        updater.sys, "executable",
        "/Apps/Vault Authenticator.app/Contents/MacOS/Vault Authenticator",
    )
    assert updater._current_app_root() == "/Apps/Vault Authenticator.app"


def test_current_app_root_windows(monkeypatch):
    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setattr(
        updater.sys, "executable",
        r"C:\Apps\Vault Authenticator\Vault Authenticator.exe",
    )
    assert updater._current_app_root() == r"C:\Apps\Vault Authenticator"


def test_swap_and_relaunch_unix_moves_directories_and_relaunches(tmp_path, monkeypatch):
    current_root = tmp_path / "Vault Authenticator.app"
    current_root.mkdir()
    (current_root / "marker.txt").write_text("old")

    new_root = tmp_path / "new_extracted" / "Vault Authenticator.app"
    new_root.parent.mkdir()
    new_root.mkdir()
    (new_root / "marker.txt").write_text("new")

    monkeypatch.setattr(updater.sys, "platform", "darwin")
    monkeypatch.setattr(updater, "_current_app_root", lambda: str(current_root))
    exit_calls = []
    monkeypatch.setattr(updater.os, "_exit", lambda code: exit_calls.append(code))
    popen_calls = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kw: popen_calls.append(args))

    updater._swap_and_relaunch_unix(str(new_root))

    assert (current_root / "marker.txt").read_text() == "new"
    assert not (tmp_path / (current_root.name + ".old")).exists()
    assert popen_calls[0][0].endswith("Vault Authenticator")
    assert exit_calls == [0]


def test_swap_and_relaunch_windows_writes_helper_script(tmp_path, monkeypatch):
    app_root = tmp_path / "Vault Authenticator"
    app_root.mkdir()
    new_root = tmp_path / "new_extracted" / "Vault Authenticator"
    new_root.parent.mkdir()
    new_root.mkdir()

    monkeypatch.setattr(updater.sys, "platform", "win32")
    monkeypatch.setattr(updater.sys, "executable", str(app_root / "Vault Authenticator.exe"))
    monkeypatch.setattr(updater, "_current_app_root", lambda: str(app_root))
    monkeypatch.setattr(updater.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(updater.os, "_exit", lambda code: None)
    popen_calls = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kw: popen_calls.append((args, kw)))
    monkeypatch.setattr(updater.subprocess, "DETACHED_PROCESS", 0x8, raising=False)
    monkeypatch.setattr(updater.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False)

    updater._swap_and_relaunch_windows(str(new_root))

    helper_files = list(tmp_path.glob("vault_update_helper_*.bat"))
    assert len(helper_files) == 1
    content = helper_files[0].read_text()
    assert "Vault Authenticator.exe" in content
    assert "rmdir /s /q" in content
    assert popen_calls[0][0][0] == "cmd.exe"
```

Modify `requirements.txt` — append after the existing Linux-webview comment block at the end of the file:

```

# Needed only for running the test suite (not part of the shipped app)
pytest>=8.0.0
```

- [ ] **Step 2: Install pytest and run the suite to verify it fails**

Run: `pip install -r requirements.txt && pytest tests/test_updater.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'updater'` (the module doesn't exist yet).

- [ ] **Step 3: Write `updater.py`**

```python
"""
Self-update: checks GitHub Releases for a newer tagged version, downloads
and checksum-verifies the platform build, then swaps it into place and
relaunches. Only functional in a PyInstaller-frozen build (sys.frozen) -
running via `python3 app.py` during development just reports state.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.request
import zipfile

REPO = "justirva09/vault-authenticator"
GITHUB_API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"

ASSET_NAMES = {
    "darwin": "Vault-Authenticator-macOS.zip",
    "win32": "Vault-Authenticator-Windows.zip",
    "linux": "Vault-Authenticator-Linux.tar.gz",
}

_lock = threading.Lock()
_status = {
    "phase": "idle",  # idle | checking | available | downloading | verifying | applying | error
    "current_version": None,
    "latest_version": None,
    "percent": 0,
    "error": None,
}
_latest_assets = {}  # asset filename -> browser_download_url, set by check_for_update


def _set_status(**kwargs):
    with _lock:
        _status.update(kwargs)


def get_status():
    with _lock:
        return dict(_status)


def _parse_version(v):
    parts = re.findall(r"\d+", v)
    nums = tuple(int(p) for p in parts[:3])
    return nums + (0,) * (3 - len(nums))


def _asset_name():
    name = ASSET_NAMES.get(sys.platform)
    if not name:
        raise RuntimeError(f"Unsupported platform: {sys.platform}")
    return name


def check_for_update(current_version):
    _set_status(phase="checking", current_version=current_version, error=None)
    try:
        req = urllib.request.Request(
            GITHUB_API_LATEST, headers={"User-Agent": "vault-authenticator-updater"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        latest_tag = data.get("tag_name", "")
        latest_version = latest_tag.lstrip("v")
        assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
        _latest_assets.clear()
        _latest_assets.update(assets)
        if _parse_version(latest_tag) > _parse_version(current_version):
            _set_status(phase="available", latest_version=latest_version)
        else:
            _set_status(phase="idle", latest_version=latest_version)
    except Exception as e:
        _set_status(phase="error", error=str(e))


def _download(url, dest_path, on_progress):
    req = urllib.request.Request(url, headers={"User-Agent": "vault-authenticator-updater"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        total = int(resp.headers.get("Content-Length", 0) or 0)
        read = 0
        with open(dest_path, "wb") as f:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                f.write(chunk)
                read += len(chunk)
                if total:
                    on_progress(int(read * 100 / total))


def _sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _expected_checksum(checksums_text, asset_filename):
    for line in checksums_text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == asset_filename:
            return parts[0].lower()
    return None


def _extract(archive_path, dest_dir):
    if archive_path.endswith(".zip"):
        with zipfile.ZipFile(archive_path) as z:
            z.extractall(dest_dir)
    else:
        with tarfile.open(archive_path) as t:
            t.extractall(dest_dir)


def _extracted_root(dest_dir):
    entries = [e for e in os.listdir(dest_dir) if not e.startswith(".")]
    if len(entries) != 1:
        raise RuntimeError(f"Unexpected archive layout: {entries}")
    return os.path.join(dest_dir, entries[0])


def _strip_quarantine(app_path):
    subprocess.run(["xattr", "-cr", app_path], check=False)


def _current_app_root():
    exe = sys.executable
    if sys.platform == "darwin":
        return os.path.dirname(os.path.dirname(os.path.dirname(exe)))
    return os.path.dirname(exe)


def _swap_and_relaunch_unix(new_root):
    current_root = _current_app_root()
    old_aside = current_root + ".old"
    if os.path.exists(old_aside):
        shutil.rmtree(old_aside, ignore_errors=True)
    os.rename(current_root, old_aside)
    shutil.move(new_root, current_root)

    if sys.platform == "darwin":
        exe = os.path.join(current_root, "Contents", "MacOS", "Vault Authenticator")
    else:
        exe = os.path.join(current_root, "vault-authenticator")
    subprocess.Popen([exe], start_new_session=True)

    shutil.rmtree(old_aside, ignore_errors=True)
    os._exit(0)


def _swap_and_relaunch_windows(new_root):
    current_root = _current_app_root()
    exe_name = os.path.basename(sys.executable)
    helper_path = os.path.join(tempfile.gettempdir(), f"vault_update_helper_{os.getpid()}.bat")

    script = (
        "@echo off\r\n"
        "setlocal\r\n"
        f'set "OLD_ROOT={current_root}"\r\n'
        f'set "NEW_ROOT={new_root}"\r\n'
        f'set "EXE_NAME={exe_name}"\r\n'
        ":retry\r\n"
        'rmdir /s /q "%OLD_ROOT%" 2>nul\r\n'
        'if exist "%OLD_ROOT%" (\r\n'
        "  timeout /t 1 /nobreak >nul\r\n"
        "  goto retry\r\n"
        ")\r\n"
        'move "%NEW_ROOT%" "%OLD_ROOT%"\r\n'
        'start "" "%OLD_ROOT%\\%EXE_NAME%"\r\n'
        'del "%~f0"\r\n'
    )
    with open(helper_path, "w") as f:
        f.write(script)

    subprocess.Popen(
        ["cmd.exe", "/c", helper_path],
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
        close_fds=True,
    )
    os._exit(0)


def start_apply():
    threading.Thread(target=_apply_worker, daemon=True).start()


def _apply_worker():
    try:
        if not getattr(sys, "frozen", False):
            _set_status(phase="error", error="Auto-update only works in the packaged app.")
            return

        asset_name = _asset_name()
        checksum_name = asset_name + ".sha256"
        asset_url = _latest_assets.get(asset_name)
        checksum_url = _latest_assets.get(checksum_name)
        if not asset_url or not checksum_url:
            _set_status(phase="error", error="Update assets not found for this platform.")
            return

        work_dir = tempfile.mkdtemp(prefix="vault_update_")
        archive_path = os.path.join(work_dir, asset_name)

        _set_status(phase="downloading", percent=0)
        _download(asset_url, archive_path, lambda p: _set_status(percent=p))

        _set_status(phase="verifying")
        checksum_path = os.path.join(work_dir, checksum_name)
        _download(checksum_url, checksum_path, lambda p: None)
        with open(checksum_path) as f:
            expected = _expected_checksum(f.read(), asset_name)
        actual = _sha256_of(archive_path)
        if not expected or expected != actual.lower():
            _set_status(phase="error", error="Downloaded update failed verification.")
            return

        extract_dir = os.path.join(work_dir, "extracted")
        os.makedirs(extract_dir, exist_ok=True)
        _extract(archive_path, extract_dir)
        new_root = _extracted_root(extract_dir)

        if sys.platform == "darwin":
            _strip_quarantine(new_root)

        _set_status(phase="applying")
        if sys.platform == "win32":
            _swap_and_relaunch_windows(new_root)
        else:
            _swap_and_relaunch_unix(new_root)
    except Exception as e:
        _set_status(phase="error", error=str(e))
```

- [ ] **Step 4: Run the test suite and verify it passes**

Run: `pytest tests/test_updater.py -v`
Expected: all tests PASS (15 tests).

- [ ] **Step 5: Commit**

```bash
git add updater.py tests/conftest.py tests/test_updater.py requirements.txt
git commit -m "feat: add core auto-updater module"
```

---

## Task 2: Flask routes wiring the updater into the app

**Files:**
- Modify: `app.py`
- Create: `tests/test_app_update_routes.py`

**Interfaces:**
- Consumes: `updater.get_status()`, `updater.check_for_update(current_version)`, `updater.start_apply()` from Task 1.
- Produces (used by Task 3):
  - `POST /api/update/check` → `{"ok": true}`, kicks off a background version check.
  - `GET /api/update/status` → whatever `updater.get_status()` returns, verbatim.
  - `POST /api/update/apply` → `{"ok": true}`, kicks off the download/verify/swap/relaunch pipeline.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_app_update_routes.py`:

```python
from unittest.mock import patch

import app as flask_app


def _client():
    flask_app.app.config["TESTING"] = True
    return flask_app.app.test_client()


def test_update_check_starts_background_thread_with_check_for_update(monkeypatch):
    client = _client()
    captured = {}

    class FakeThread:
        def __init__(self, target, args=(), daemon=None):
            captured["target"] = target
            captured["args"] = args

        def start(self):
            captured["started"] = True

    monkeypatch.setattr(flask_app.threading, "Thread", FakeThread)

    resp = client.post("/api/update/check")

    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    assert captured["target"] is flask_app.updater.check_for_update
    assert captured["args"] == (flask_app.__version__,)
    assert captured["started"] is True


def test_update_status_returns_updater_state():
    client = _client()
    fake_status = {"phase": "available", "latest_version": "9.9.9"}
    with patch("app.updater.get_status", return_value=fake_status):
        resp = client.get("/api/update/status")
    assert resp.get_json() == fake_status


def test_update_apply_triggers_start_apply():
    client = _client()
    with patch("app.updater.start_apply") as mock_apply:
        resp = client.post("/api/update/apply")
    assert resp.status_code == 200
    assert resp.get_json() == {"ok": True}
    mock_apply.assert_called_once()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_app_update_routes.py -v`
Expected: FAIL — `AttributeError: module 'app' has no attribute 'updater'` (and 404s for the not-yet-defined routes).

- [ ] **Step 3: Add the routes to `app.py`**

Modify the top of `app.py` — current imports are:

```python
import time
import pyotp
from flask import Flask, request, jsonify, render_template, session

import storage
import migration_parser
```

Change to:

```python
import threading
import time
import pyotp
from flask import Flask, request, jsonify, render_template, session

import storage
import migration_parser
import updater
```

Modify the end of `app.py` — insert the three new routes right before the `if __name__ == "__main__":` block, i.e. right after `rename_account`'s closing `return jsonify(...)` line:

```python
    return jsonify({"ok": True, "issuer": updated["issuer"], "account_name": updated["account_name"]})


@app.route("/api/update/check", methods=["POST"])
def update_check():
    threading.Thread(target=updater.check_for_update, args=(__version__,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/api/update/status")
def update_status():
    return jsonify(updater.get_status())


@app.route("/api/update/apply", methods=["POST"])
def update_apply():
    updater.start_apply()
    return jsonify({"ok": True})


if __name__ == "__main__":
```

(everything from `if __name__ == "__main__":` onward stays unchanged.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_app_update_routes.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 5: Run the full suite together**

Run: `pytest -v`
Expected: all tests from Task 1 and Task 2 PASS (18 tests total).

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_app_update_routes.py
git commit -m "feat: expose update check/status/apply routes"
```

---

## Task 3: Frontend update banner

**Files:**
- Modify: `templates/index.html`
- Modify: `static/style.css`
- Modify: `static/app.js`

**Interfaces:**
- Consumes: `/api/update/check`, `/api/update/status`, `/api/update/apply` from Task 2. `status.phase` values: `idle | checking | available | downloading | verifying | applying | error`; `status.percent` (int, only meaningful during `downloading`); `status.latest_version`; `status.error`.

- [ ] **Step 1: Add the banner markup**

Modify `templates/index.html` — insert right after `<div class="grain"></div>`:

```html
<div class="grain"></div>

<div id="update-banner" class="update-banner hidden">
  <span id="update-banner-text"></span>
  <button id="update-banner-btn" class="btn-ghost">Update</button>
</div>

<!-- SETUP SCREEN (first run only) -->
```

- [ ] **Step 2: Add banner styles**

Modify `static/style.css` — insert right after the `.grain { ... }` block (which ends at the closing brace after the `background-image` line), before the `/* ---------- Centered lock / setup card ---------- */` comment:

```css
.update-banner {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 900;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  padding: 10px 16px;
  background: var(--surface-2);
  border-bottom: 1px solid var(--accent-dim);
  font-size: 13px;
  color: var(--text);
}
.update-banner .btn-ghost {
  padding: 5px 12px;
  font-size: 12.5px;
}
```

- [ ] **Step 3: Wire up polling and the update button in `app.js`**

Modify `static/app.js` — change `boot()` from:

```js
async function boot() {
  const res = await fetch('/api/status');
  const data = await res.json();
  if (!data.initialized) {
    showView('#view-setup');
  } else if (!data.unlocked) {
    showView('#view-lock');
  } else {
    showView('#view-dashboard');
    startDashboard();
  }
}
```

to:

```js
async function boot() {
  const res = await fetch('/api/status');
  const data = await res.json();
  if (!data.initialized) {
    showView('#view-setup');
  } else if (!data.unlocked) {
    showView('#view-lock');
  } else {
    showView('#view-dashboard');
    startDashboard();
  }
  checkForUpdate();
}

// ---------------- Auto-update ----------------
let updatePollTimer = null;

async function checkForUpdate() {
  await fetch('/api/update/check', { method: 'POST' });
  updatePollTimer = setInterval(pollUpdateStatus, 1500);
}

async function pollUpdateStatus() {
  let data;
  try {
    const res = await fetch('/api/update/status');
    data = await res.json();
  } catch (e) {
    return; // server likely mid-restart after an applied update
  }
  renderUpdateBanner(data);
  if (data.phase === 'error') clearInterval(updatePollTimer);
}

function renderUpdateBanner(data) {
  const banner = $('#update-banner');
  const text = $('#update-banner-text');
  const btn = $('#update-banner-btn');

  if (data.phase === 'available') {
    text.textContent = `Version ${data.latest_version} is available.`;
    btn.textContent = 'Update';
    btn.disabled = false;
    banner.classList.remove('hidden');
  } else if (data.phase === 'downloading') {
    text.textContent = `Downloading update… ${data.percent || 0}%`;
    btn.disabled = true;
    banner.classList.remove('hidden');
  } else if (data.phase === 'verifying') {
    text.textContent = 'Verifying update…';
    btn.disabled = true;
    banner.classList.remove('hidden');
  } else if (data.phase === 'applying') {
    text.textContent = 'Restarting with the new version…';
    btn.disabled = true;
    banner.classList.remove('hidden');
  } else if (data.phase === 'error') {
    text.textContent = `Update failed: ${data.error}`;
    btn.textContent = 'Retry';
    btn.disabled = false;
    banner.classList.remove('hidden');
  } else {
    banner.classList.add('hidden');
  }
}

$('#update-banner-btn').addEventListener('click', async () => {
  await fetch('/api/update/apply', { method: 'POST' });
});
```

- [ ] **Step 4: Manual verification (no JS test framework in this repo)**

Run: `python3 app.py`, open `http://127.0.0.1:5057` in a browser, open devtools console.

1. Confirm the banner is hidden on load (no update available yet, since dev `__version__` matches or exceeds any real release).
2. Paste `renderUpdateBanner({phase: 'available', latest_version: '9.9.9'})` — expect the banner to appear at the top with "Version 9.9.9 is available." and an enabled "Update" button.
3. Paste `renderUpdateBanner({phase: 'downloading', percent: 42})` — expect "Downloading update… 42%" with the button disabled.
4. Paste `renderUpdateBanner({phase: 'verifying'})`, then `renderUpdateBanner({phase: 'applying'})`, then `renderUpdateBanner({phase: 'error', error: 'boom'})` — expect each state's text/button to update correctly, ending with an enabled "Retry" button.
5. Paste `renderUpdateBanner({phase: 'idle'})` — expect the banner to hide again.

Expected: all 5 checks match as described.

- [ ] **Step 5: Commit**

```bash
git add templates/index.html static/style.css static/app.js
git commit -m "feat: add update-available banner to the dashboard"
```

---

## Task 4: CI — publish per-asset SHA256 checksums

**Files:**
- Modify: `.github/workflows/release.yml`

**Interfaces:**
- Consumes: nothing new from earlier tasks (this only needs to produce assets whose naming matches `updater.ASSET_NAMES` + `.sha256` from Task 1).
- Produces: for each matrix leg, a `<artifact-filename>.sha256` release asset alongside the existing archive (e.g. `Vault-Authenticator-macOS.zip.sha256`, containing a line `<hex-sha256>  Vault-Authenticator-macOS.zip`).

- [ ] **Step 1: Add a checksum step per OS and include it in the upload**

Modify `.github/workflows/release.yml` — change:

```yaml
      - name: Package (macOS)
        if: runner.os == 'macOS'
        run: |
          cd dist
          zip -r "../${{ matrix.artifact }}.zip" "Vault Authenticator.app"

      - name: Package (Windows)
        if: runner.os == 'Windows'
        shell: pwsh
        run: |
          Compress-Archive -Path "dist/Vault Authenticator" -DestinationPath "${{ matrix.artifact }}.zip"

      - name: Package (Linux)
        if: runner.os == 'Linux'
        run: |
          cd dist
          tar -czf "../${{ matrix.artifact }}.tar.gz" vault-authenticator

      - name: Upload to release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ needs.release.outputs.tag }}
          files: |
            ${{ matrix.artifact }}.zip
            ${{ matrix.artifact }}.tar.gz
          fail_on_unmatched_files: false
```

to:

```yaml
      - name: Package (macOS)
        if: runner.os == 'macOS'
        run: |
          cd dist
          zip -r "../${{ matrix.artifact }}.zip" "Vault Authenticator.app"

      - name: Package (Windows)
        if: runner.os == 'Windows'
        shell: pwsh
        run: |
          Compress-Archive -Path "dist/Vault Authenticator" -DestinationPath "${{ matrix.artifact }}.zip"

      - name: Package (Linux)
        if: runner.os == 'Linux'
        run: |
          cd dist
          tar -czf "../${{ matrix.artifact }}.tar.gz" vault-authenticator

      - name: Checksum (macOS)
        if: runner.os == 'macOS'
        run: shasum -a 256 "${{ matrix.artifact }}.zip" > "${{ matrix.artifact }}.zip.sha256"

      - name: Checksum (Windows)
        if: runner.os == 'Windows'
        shell: pwsh
        run: |
          $hash = (Get-FileHash "${{ matrix.artifact }}.zip" -Algorithm SHA256).Hash.ToLower()
          "$hash  ${{ matrix.artifact }}.zip" | Out-File -Encoding ascii "${{ matrix.artifact }}.zip.sha256"

      - name: Checksum (Linux)
        if: runner.os == 'Linux'
        run: sha256sum "${{ matrix.artifact }}.tar.gz" > "${{ matrix.artifact }}.tar.gz.sha256"

      - name: Upload to release
        uses: softprops/action-gh-release@v2
        with:
          tag_name: ${{ needs.release.outputs.tag }}
          files: |
            ${{ matrix.artifact }}.zip
            ${{ matrix.artifact }}.tar.gz
            ${{ matrix.artifact }}.zip.sha256
            ${{ matrix.artifact }}.tar.gz.sha256
          fail_on_unmatched_files: false
```

(`fail_on_unmatched_files: false` already tolerates each OS only producing 2 of these 4 patterns — same as the existing zip/tar.gz split.)

- [ ] **Step 2: No unit test for this step — YAML CI config isn't unit-testable in isolation**

This is verified end-to-end in Task 5 (a real release run must produce the `.sha256` files on the release page).

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: publish per-asset sha256 checksums with each release"
```

---

## Task 5: Manual end-to-end verification (all 3 platforms)

**Files:** none (no code changes — this is a verification pass over Tasks 1–4 together, per the spec's Testing section which calls out that the actual swap/relaunch can't be unit tested).

- [ ] **Step 1: Cut a real test release one version ahead**

Merge a `fix:` or `feat:` commit to `main` so `python-semantic-release` bumps the version and the release/build pipeline runs, producing the 3 archives + 4 checksum files on the new GitHub Release (confirms Task 4 end-to-end).

- [ ] **Step 2: Verify on macOS**

Install the *previous* version's `.app` (drag to `/Applications`), launch it, confirm the "vX available — Update" banner appears, click it, and confirm: download progress shows, verification passes, the app relaunches automatically at the new version with no Gatekeeper prompt, and `/Applications/Vault Authenticator.app` is the new build (check `/api/status` version in devtools or the app's own display, if any).

- [ ] **Step 3: Verify on Windows**

Same flow: extract the previous `Vault-Authenticator-Windows.zip`, run it, confirm banner → update → the app closes, a brief console-less helper window may flash, and the app relaunches at the new version.

- [ ] **Step 4: Verify on Linux**

Same flow with the previous `Vault-Authenticator-Linux.tar.gz`, confirm banner → update → relaunch at the new version.

- [ ] **Step 5: Verify the failure path on any one platform**

Temporarily rename/replace the `.sha256` asset content on the release (or point `updater.GITHUB_API_LATEST` at a repo with a mismatched checksum) to confirm a corrupted/mismatched download surfaces "Update failed" in the banner and leaves the currently-running app fully intact and usable — not partially swapped.
