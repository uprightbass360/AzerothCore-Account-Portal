from app.core.srp6 import calculate_verifier, verify_password

SALT1 = bytes.fromhex("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f")
VERIFIER1 = bytes.fromhex("388aa0fa07b5252db2f75c032b20fd11d63e417277a0e566cf79acf642ceb771")
SALT2 = bytes.fromhex("ff" * 32)
VERIFIER2 = bytes.fromhex("028d6648bce001ea3757f1422dc2830148a0fb9bef14b6c3e5b70a1e2871c61a")


def test_known_vectors():
    assert calculate_verifier("testuser", "testpass", SALT1) == VERIFIER1
    assert calculate_verifier("ADMIN", "s3cret!", SALT2) == VERIFIER2


def test_case_insensitive():
    assert calculate_verifier("TestUser", "TESTPASS", SALT1) == VERIFIER1


def test_verify_password():
    assert verify_password("testuser", "testpass", SALT1, VERIFIER1) is True
    assert verify_password("testuser", "wrong", SALT1, VERIFIER1) is False
    assert verify_password("other", "testpass", SALT1, VERIFIER1) is False


def test_verifier_is_32_bytes():
    assert len(calculate_verifier("a", "b", SALT1)) == 32
