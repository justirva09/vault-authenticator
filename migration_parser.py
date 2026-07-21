"""
Parses the payload embedded in Google Authenticator's "Export accounts" QR code.

That QR code encodes a URL like:
    otpauth-migration://offline?data=<base64>

The base64 blob is a small protobuf message (reverse-engineered years ago and
widely documented/open-sourced — this is the same schema used by many other
open-source Authenticator-migration tools). Rather than depend on the `protobuf`
package + generated stubs, this module hand-parses the wire format directly,
since the schema only has a handful of simple fields.

MigrationPayload:
  repeated OtpParameters otp_parameters = 1;
    OtpParameters:
      bytes  secret    = 1
      string name      = 2   (account / username)
      string issuer    = 3
      enum   algorithm = 4   (0=unspecified,1=SHA1,2=SHA256,3=SHA512,4=MD5)
      enum   digits    = 5   (0=unspecified,1=SIX,2=EIGHT)
      enum   type      = 6   (0=unspecified,1=HOTP,2=TOTP)
      int64  counter   = 7   (only used for HOTP)
"""
import base64
from urllib.parse import urlparse, parse_qs

ALGO_MAP = {0: "SHA1", 1: "SHA1", 2: "SHA256", 3: "SHA512", 4: "MD5"}
DIGITS_MAP = {0: 6, 1: 6, 2: 8}
TYPE_MAP = {0: "totp", 1: "hotp", 2: "totp"}


class ParseError(Exception):
    pass


def _read_varint(buf, pos):
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ParseError("Truncated varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def _read_field(buf, pos):
    tag, pos = _read_varint(buf, pos)
    field_num = tag >> 3
    wire_type = tag & 0x07
    if wire_type == 0:  # varint
        value, pos = _read_varint(buf, pos)
    elif wire_type == 2:  # length-delimited
        length, pos = _read_varint(buf, pos)
        value = buf[pos:pos + length]
        pos += length
    elif wire_type == 5:  # fixed32
        value = buf[pos:pos + 4]
        pos += 4
    elif wire_type == 1:  # fixed64
        value = buf[pos:pos + 8]
        pos += 8
    else:
        raise ParseError(f"Unsupported wire type {wire_type}")
    return field_num, value, pos


def _parse_otp_parameters(buf):
    fields = {}
    pos = 0
    while pos < len(buf):
        field_num, value, pos = _read_field(buf, pos)
        fields[field_num] = value

    secret = fields.get(1, b"")
    name = fields.get(2, b"").decode("utf-8", errors="replace") if isinstance(fields.get(2), (bytes, bytearray)) else ""
    issuer = fields.get(3, b"").decode("utf-8", errors="replace") if isinstance(fields.get(3), (bytes, bytearray)) else ""
    algorithm = ALGO_MAP.get(fields.get(4, 1), "SHA1")
    digits = DIGITS_MAP.get(fields.get(5, 1), 6)
    otp_type = TYPE_MAP.get(fields.get(6, 2), "totp")
    counter = fields.get(7, 0)

    return {
        "secret_bytes": bytes(secret),
        "name": name,
        "issuer": issuer,
        "algorithm": algorithm,
        "digits": digits,
        "type": otp_type,
        "counter": counter if isinstance(counter, int) else 0,
    }


def parse_migration_payload(raw_bytes):
    """Parses the top-level MigrationPayload protobuf message."""
    pos = 0
    accounts = []
    while pos < len(raw_bytes):
        field_num, value, pos = _read_field(raw_bytes, pos)
        if field_num == 1 and isinstance(value, (bytes, bytearray)):
            accounts.append(_parse_otp_parameters(value))
    return accounts


def _base32_secret(secret_bytes):
    """TOTP libraries expect base32-encoded secrets."""
    return base64.b32encode(secret_bytes).decode("utf-8").rstrip("=")


def parse_migration_url(url):
    """
    Accepts the full otpauth-migration://offline?data=... string decoded from
    the QR code and returns a list of account dicts ready for storage.
    """
    parsed = urlparse(url)
    if parsed.scheme != "otpauth-migration":
        raise ParseError("Not a Google Authenticator export QR code")

    qs = parse_qs(parsed.query)
    if "data" not in qs:
        raise ParseError("QR code is missing migration data")

    b64_data = qs["data"][0]
    # Migration data is base64 (may be URL-encoded, may need padding fixed)
    padding = "=" * (-len(b64_data) % 4)
    raw_bytes = base64.b64decode(b64_data + padding)

    parsed_accounts = parse_migration_payload(raw_bytes)

    results = []
    for acct in parsed_accounts:
        if not acct["secret_bytes"]:
            continue
        results.append({
            "issuer": acct["issuer"] or (acct["name"].split(":")[0] if ":" in acct["name"] else "") or "Unknown",
            "account_name": acct["name"],
            "secret": _base32_secret(acct["secret_bytes"]),
            "algorithm": acct["algorithm"],
            "digits": acct["digits"],
            "type": acct["type"],
            "counter": acct["counter"],
        })
    return results


def parse_single_otpauth_url(url):
    """
    Handles a plain (non-migration) otpauth://totp/... URL, in case someone
    scans an individual account QR code instead of the batch export.
    """
    parsed = urlparse(url)
    if parsed.scheme != "otpauth":
        raise ParseError("Not a valid otpauth QR code")

    otp_type = parsed.netloc.lower()  # 'totp' or 'hotp'
    label = parsed.path.lstrip("/")
    qs = parse_qs(parsed.query)

    secret = qs.get("secret", [""])[0]
    issuer = qs.get("issuer", [""])[0]
    algorithm = qs.get("algorithm", ["SHA1"])[0].upper()
    digits = int(qs.get("digits", ["6"])[0])
    counter = int(qs.get("counter", ["0"])[0])

    account_name = label
    if ":" in label and not issuer:
        issuer, account_name = label.split(":", 1)

    if not secret:
        raise ParseError("QR code is missing a secret")

    return [{
        "issuer": issuer or "Unknown",
        "account_name": account_name,
        "secret": secret.strip(),
        "algorithm": algorithm if algorithm in ("SHA1", "SHA256", "SHA512", "MD5") else "SHA1",
        "digits": digits,
        "type": otp_type if otp_type in ("totp", "hotp") else "totp",
        "counter": counter,
    }]
