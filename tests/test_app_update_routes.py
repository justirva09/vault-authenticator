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
