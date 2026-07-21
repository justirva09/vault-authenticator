import hashlib
import json
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
