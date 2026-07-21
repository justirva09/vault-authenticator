"""
Desktop launcher for Vault Authenticator.

Runs the Flask server in a background thread (bound to 127.0.0.1 only,
same as before) and opens it in a native window via pywebview instead of
a browser tab. This is the entry point used when building the packaged
macOS .app with PyInstaller - see build_mac_app.sh.
"""
import threading
import socket
import time
import base64
import mimetypes
import os

import webview

import app as flask_app  # the existing Flask app in app.py

HOST = "127.0.0.1"
PORT = 5057


def _port_is_open(host, port, timeout=0.2):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        return s.connect_ex((host, port)) == 0


def _run_server():
    # use_reloader=False is required - the reloader spawns a second process,
    # which doesn't play well with PyInstaller-frozen apps.
    flask_app.app.run(host=HOST, port=PORT, debug=False, use_reloader=False)


class Api:
    """
    Exposed to the page as window.pywebview.api.* (pywebview's JS bridge).

    pywebview's macOS/WKWebView backend does not reliably open a file picker
    for a plain HTML <input type="file"> click (this is a long-standing
    pywebview limitation, not something fixable from the web page alone).
    So for the packaged desktop app, the page calls this native dialog
    instead and gets the chosen image back as a data URL to feed into the
    existing in-browser QR decoder - the decoding logic doesn't change at all.
    """

    def pick_image_base64(self):
        window = webview.windows[0]
        file_types = ("Image Files (*.png;*.jpg;*.jpeg;*.gif;*.bmp;*.webp)", "All files (*.*)")
        result = window.create_file_dialog(
            webview.FileDialog.OPEN, allow_multiple=False, file_types=file_types
        )
        if not result:
            return None
        path = result[0]
        mime, _ = mimetypes.guess_type(path)
        if not mime or not mime.startswith("image/"):
            mime = "image/png"
        with open(path, "rb") as f:
            data = f.read()
        b64 = base64.b64encode(data).decode("ascii")
        return f"data:{mime};base64,{b64}"


def main():
    server_thread = threading.Thread(target=_run_server, daemon=True)
    server_thread.start()

    # Wait briefly for Flask to actually be listening before opening the window
    for _ in range(50):  # up to ~5s
        if _port_is_open(HOST, PORT):
            break
        time.sleep(0.1)

    debug = os.environ.get("VAULT_DEBUG") == "1"

    webview.create_window(
        "Vault Authenticator",
        f"http://{HOST}:{PORT}",
        width=440,
        height=760,
        min_size=(380, 500),
        resizable=True,
        js_api=Api(),
    )
    webview.start(debug=debug)


if __name__ == "__main__":
    main()

