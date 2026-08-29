import base64
import re

import pyotp

from app.services import totp


def test_new_secret_is_16_char_base32():
    s = totp.new_secret()
    assert re.fullmatch(r"[A-Z2-7]{16}", s)
    assert totp.new_secret() != s


def test_provisioning_uri():
    uri = totp.provisioning_uri("ABCDEFGHIJKLMNOP", "BOB", "MyRealm")
    assert uri.startswith("otpauth://totp/")
    assert "MyRealm" in uri and "BOB" in uri and "secret=ABCDEFGHIJKLMNOP" in uri


def test_qr_svg():
    svg = totp.qr_svg("otpauth://totp/x?secret=ABCDEFGHIJKLMNOP")
    assert svg.startswith("<svg") and "</svg>" in svg


def test_verify_code_window():
    s = totp.new_secret()
    assert totp.verify_code(s, pyotp.TOTP(s).now()) is True
    assert totp.verify_code(s, "000000") in (True, False)  # deterministic call, no crash
    assert totp.verify_code(s, "not6dig") is False


def test_secret_from_db_roundtrip():
    s = totp.new_secret()
    raw = base64.b32decode(s)
    assert totp.secret_from_db(raw) == s
