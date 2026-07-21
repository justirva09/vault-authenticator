"""
Self-update: checks GitHub Releases for a newer tagged version, downloads
and checksum-verifies the platform build, then swaps it into place and
relaunches. Only functional in a PyInstaller-frozen build (sys.frozen) -
running via `python3 app.py` during development just reports state.
"""
import hashlib
import json
import ntpath
import os
import posixpath
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.request
import zipfile

import certifi

REPO = "justirva09/vault-authenticator"
GITHUB_API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"

# PyInstaller-frozen builds don't reliably inherit the OS's CA trust store,
# so HTTPS requests need an explicit CA bundle or they fail with
# CERTIFICATE_VERIFY_FAILED.
_SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())

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
        with urllib.request.urlopen(req, timeout=10, context=_SSL_CONTEXT) as resp:
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
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as resp:
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
    path_mod = ntpath if sys.platform == "win32" else posixpath
    if sys.platform == "darwin":
        return path_mod.dirname(path_mod.dirname(path_mod.dirname(exe)))
    return path_mod.dirname(exe)


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
