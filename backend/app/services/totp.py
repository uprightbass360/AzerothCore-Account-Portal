import base64
import os

import pyotp
import segno


def new_secret() -> str:
    """16-char base32 secret (10 random bytes) — AzerothCore SOAP requires exactly 16 chars."""
    return base64.b32encode(os.urandom(10)).decode("ascii")


def provisioning_uri(secret: str, username: str, issuer: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=username, issuer_name=issuer)


def qr_svg(uri: str) -> str:
    return segno.make(uri).svg_inline(scale=4)


def verify_code(secret: str, code: str) -> bool:
    return pyotp.TOTP(secret).verify(code, valid_window=1)


def secret_from_db(raw: bytes) -> str:
    """acore_auth stores the base32-DECODED bytes; pyotp wants base32 text."""
    return base64.b32encode(raw).decode("ascii")
