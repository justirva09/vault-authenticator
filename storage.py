"""
Encrypted local storage for authenticator accounts.

All secrets are encrypted at rest with a key derived from the user's master
password (PBKDF2-HMAC-SHA256 -> Fernet/AES). Nothing is ever written to disk
in plaintext. The derived key only lives in memory for the current session.
"""
import os
import sys
import json
import base64
import time
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.fernet import Fernet, InvalidToken


def _default_data_dir():
    """
    When running as a packaged app (PyInstaller sets sys.frozen), the app
    bundle/exe folder itself isn't a safe/writable place to keep user data
    long-term (it gets replaced on every rebuild/update, and on some
    platforms it's not even writable). Use each OS's standard per-user
    app-data location instead. When running from source (dev mode), keep
    the old behavior of a local ./data folder next to the code.
    """
    if getattr(sys, "frozen", False):
        app_name = "Vault Authenticator"
        if sys.platform == "darwin":
            return os.path.expanduser(f"~/Library/Application Support/{app_name}")
        elif sys.platform == "win32":
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
            return os.path.join(base, app_name)
        else:  # linux and other unix-likes
            base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
            return os.path.join(base, "vault-authenticator")
    return os.path.join(os.path.dirname(__file__), "data")


DATA_DIR = _default_data_dir()
STORE_PATH = os.path.join(DATA_DIR, "vault.enc")
META_PATH = os.path.join(DATA_DIR, "meta.json")

os.makedirs(DATA_DIR, exist_ok=True)


def is_initialized():
    return os.path.exists(META_PATH) and os.path.exists(STORE_PATH)


def _derive_key(password: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=390000,
    )
    return base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))


def initialize_vault(password: str):
    """Called once, the first time the app runs, to set the master password."""
    salt = os.urandom(16)
    key = _derive_key(password, salt)
    fernet = Fernet(key)
    empty_vault = json.dumps({"accounts": []}).encode("utf-8")
    encrypted = fernet.encrypt(empty_vault)

    with open(META_PATH, "w") as f:
        json.dump({"salt": base64.b64encode(salt).decode("utf-8")}, f)
    with open(STORE_PATH, "wb") as f:
        f.write(encrypted)

    return key


def unlock_vault(password: str):
    """Returns the derived key if the password is correct, else None."""
    with open(META_PATH, "r") as f:
        meta = json.load(f)
    salt = base64.b64decode(meta["salt"])
    key = _derive_key(password, salt)

    try:
        _load_with_key(key)
    except InvalidToken:
        return None
    return key


def _load_with_key(key: bytes):
    fernet = Fernet(key)
    with open(STORE_PATH, "rb") as f:
        encrypted = f.read()
    decrypted = fernet.decrypt(encrypted)
    return json.loads(decrypted.decode("utf-8"))


def _save_with_key(key: bytes, data: dict):
    fernet = Fernet(key)
    encrypted = fernet.encrypt(json.dumps(data).encode("utf-8"))
    with open(STORE_PATH, "wb") as f:
        f.write(encrypted)


def get_accounts(key: bytes):
    data = _load_with_key(key)
    return data.get("accounts", [])


def add_accounts(key: bytes, new_accounts: list):
    data = _load_with_key(key)
    existing = data.get("accounts", [])
    now = time.time()
    for acct in new_accounts:
        acct = dict(acct)
        acct["id"] = base64.urlsafe_b64encode(os.urandom(9)).decode("utf-8")
        acct["added_at"] = now
        existing.append(acct)
    data["accounts"] = existing
    _save_with_key(key, data)
    return existing


def delete_account(key: bytes, account_id: str):
    data = _load_with_key(key)
    existing = data.get("accounts", [])
    existing = [a for a in existing if a.get("id") != account_id]
    data["accounts"] = existing
    _save_with_key(key, data)
    return existing


def update_hotp_counter(key: bytes, account_id: str, new_counter: int):
    data = _load_with_key(key)
    for a in data.get("accounts", []):
        if a.get("id") == account_id:
            a["counter"] = new_counter
    _save_with_key(key, data)


def rename_account(key: bytes, account_id: str, issuer: str, account_name: str):
    data = _load_with_key(key)
    accounts = data.get("accounts", [])
    found = None
    for a in accounts:
        if a.get("id") == account_id:
            a["issuer"] = issuer
            a["account_name"] = account_name
            found = a
            break
    if found is None:
        raise KeyError("account not found")
    _save_with_key(key, data)
    return found
