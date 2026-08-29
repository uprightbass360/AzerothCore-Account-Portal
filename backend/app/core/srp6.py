"""AzerothCore SRP6 verifier calculation (WoW 3.3.5 auth scheme)."""

import hashlib
import hmac

_N = int("894B645E89E1535BBDAD5B8B290650530801B18EBFBF5E8FAB3C82872A3E9BB7", 16)
_G = 7


def calculate_verifier(username: str, password: str, salt: bytes) -> bytes:
    h1 = hashlib.sha1(f"{username.upper()}:{password.upper()}".encode()).digest()
    x = int.from_bytes(hashlib.sha1(salt + h1).digest(), "little")
    return pow(_G, x, _N).to_bytes(32, "little")


def verify_password(username: str, password: str, salt: bytes, verifier: bytes) -> bool:
    return hmac.compare_digest(calculate_verifier(username, password, salt), verifier)
