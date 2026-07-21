import time
import pyotp
from flask import Flask, request, jsonify, render_template, session

import storage
import migration_parser

# Bumped automatically by semantic-release based on conventional commits -
# don't edit by hand. See pyproject.toml [tool.semantic_release].
__version__ = "0.1.0"

app = Flask(__name__)
app.secret_key = __import__("os").urandom(24)

# The derived encryption key lives only in memory, keyed by Flask session id.
# This is a single-user local app, so a simple in-process dict is enough.
_unlocked_keys = {}


def _get_key():
    sid = session.get("sid")
    if not sid:
        return None
    return _unlocked_keys.get(sid)


def _require_unlocked():
    key = _get_key()
    if key is None:
        return None
    return key


@app.route("/")
def index():
    return render_template("index.html", initialized=storage.is_initialized())


@app.route("/api/status")
def status():
    return jsonify({
        "initialized": storage.is_initialized(),
        "unlocked": _get_key() is not None,
        "version": __version__,
    })


@app.route("/api/setup", methods=["POST"])
def setup():
    if storage.is_initialized():
        return jsonify({"error": "Vault already exists"}), 400
    password = (request.json or {}).get("password", "")
    if len(password) < 6:
        return jsonify({"error": "Master password must be at least 6 characters"}), 400

    key = storage.initialize_vault(password)
    import os
    sid = os.urandom(16).hex()
    session["sid"] = sid
    session.permanent = False
    _unlocked_keys[sid] = key
    return jsonify({"ok": True})


@app.route("/api/unlock", methods=["POST"])
def unlock():
    password = (request.json or {}).get("password", "")
    key = storage.unlock_vault(password)
    if key is None:
        return jsonify({"error": "Incorrect password"}), 401

    import os
    sid = os.urandom(16).hex()
    session["sid"] = sid
    session.permanent = False
    _unlocked_keys[sid] = key
    return jsonify({"ok": True})


@app.route("/api/lock", methods=["POST"])
def lock():
    sid = session.get("sid")
    if sid and sid in _unlocked_keys:
        del _unlocked_keys[sid]
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/import/preview", methods=["POST"])
def import_preview():
    """Parses a scanned QR string (client-side decoded) without saving yet."""
    key = _require_unlocked()
    if key is None:
        return jsonify({"error": "Vault is locked"}), 401

    qr_text = (request.json or {}).get("qr_text", "")
    try:
        if qr_text.startswith("otpauth-migration://"):
            accounts = migration_parser.parse_migration_url(qr_text)
        elif qr_text.startswith("otpauth://"):
            accounts = migration_parser.parse_single_otpauth_url(qr_text)
        else:
            return jsonify({"error": "That QR code isn't an authenticator export or account code"}), 400
    except migration_parser.ParseError as e:
        return jsonify({"error": str(e)}), 400
    except Exception:
        return jsonify({"error": "Couldn't read that QR code — try a clearer image"}), 400

    if not accounts:
        return jsonify({"error": "No accounts found in that QR code"}), 400

    # Don't send raw secrets back to the client for display; just previews.
    preview = [{"issuer": a["issuer"], "account_name": a["account_name"], "type": a["type"]} for a in accounts]
    # Stash full parsed accounts in-memory keyed by session for the confirm step
    session["_pending_import"] = accounts
    return jsonify({"accounts": preview})


@app.route("/api/import/confirm", methods=["POST"])
def import_confirm():
    key = _require_unlocked()
    if key is None:
        return jsonify({"error": "Vault is locked"}), 401

    pending = session.get("_pending_import")
    if not pending:
        return jsonify({"error": "Nothing to import"}), 400

    selected_indices = (request.json or {}).get("selected_indices")
    if selected_indices is not None:
        pending = [a for i, a in enumerate(pending) if i in selected_indices]

    storage.add_accounts(key, pending)
    session.pop("_pending_import", None)
    return jsonify({"ok": True})


def _generate_code(account):
    digits = account.get("digits", 6)
    algo = account.get("algorithm", "SHA1")
    secret = account["secret"]

    if account.get("type") == "hotp":
        hotp = pyotp.HOTP(secret, digits=digits)
        counter = account.get("counter", 0)
        code = hotp.at(counter)
        return {"code": code, "type": "hotp", "counter": counter}
    else:
        totp = pyotp.TOTP(secret, digits=digits, interval=30)
        code = totp.now()
        remaining = 30 - (int(time.time()) % 30)
        return {"code": code, "type": "totp", "remaining": remaining}


@app.route("/api/accounts")
def list_accounts():
    key = _require_unlocked()
    if key is None:
        return jsonify({"error": "Vault is locked"}), 401

    accounts = storage.get_accounts(key)
    out = []
    for a in accounts:
        gen = _generate_code(a)
        out.append({
            "id": a["id"],
            "issuer": a["issuer"],
            "account_name": a["account_name"],
            "digits": a.get("digits", 6),
            **gen,
        })
    return jsonify({"accounts": out})


@app.route("/api/accounts/<account_id>/hotp_next", methods=["POST"])
def hotp_next(account_id):
    """Advances an HOTP counter after the user copies a code (HOTP is used-once)."""
    key = _require_unlocked()
    if key is None:
        return jsonify({"error": "Vault is locked"}), 401

    accounts = storage.get_accounts(key)
    target = next((a for a in accounts if a["id"] == account_id), None)
    if not target:
        return jsonify({"error": "Account not found"}), 404

    new_counter = target.get("counter", 0) + 1
    storage.update_hotp_counter(key, account_id, new_counter)
    return jsonify({"ok": True, "counter": new_counter})


@app.route("/api/accounts/<account_id>", methods=["DELETE"])
def delete_account(account_id):
    key = _require_unlocked()
    if key is None:
        return jsonify({"error": "Vault is locked"}), 401

    storage.delete_account(key, account_id)
    return jsonify({"ok": True})


@app.route("/api/accounts/<account_id>", methods=["PATCH"])
def rename_account(account_id):
    key = _require_unlocked()
    if key is None:
        return jsonify({"error": "Vault is locked"}), 401

    body = request.json or {}
    issuer = (body.get("issuer") or "").strip()
    account_name = (body.get("account_name") or "").strip()

    if not issuer and not account_name:
        return jsonify({"error": "Name can't be empty"}), 400

    try:
        updated = storage.rename_account(key, account_id, issuer, account_name)
    except KeyError:
        return jsonify({"error": "Account not found"}), 404

    return jsonify({"ok": True, "issuer": updated["issuer"], "account_name": updated["account_name"]})


if __name__ == "__main__":
    print("\n  Authenticator running at http://127.0.0.1:5057\n")
    app.run(host="127.0.0.1", port=5057, debug=False)
