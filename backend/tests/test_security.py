import hashlib

from app.core.security import hash_token, new_session_token


def test_new_session_token():
    raw, hashed = new_session_token()
    assert len(hashed) == 64
    assert hashed == hashlib.sha256(raw.encode()).hexdigest()
    assert len(raw) >= 43  # 256 bits urlsafe


def test_tokens_unique():
    assert new_session_token()[0] != new_session_token()[0]


def test_hash_token_matches():
    raw, hashed = new_session_token()
    assert hash_token(raw) == hashed
