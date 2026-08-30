"""Seed a SQLite stand-in for acore_auth with test accounts (real SRP6 verifiers).

Run with the backend venv: uv run --project backend python tools/uxtest/seed_acore.py
"""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[2] / "backend"))

from sqlalchemy import create_engine  # noqa: E402

from app.core.srp6 import calculate_verifier  # noqa: E402
from app.services import acore  # noqa: E402

DATA_DIR = Path(__file__).parent / ".data"
DB_PATH = DATA_DIR / "acore.db"

ACCOUNTS = [
    # (id, username, password, email, joined_days_ago, last_login_days_ago)
    (1, "TESTADMIN", "uxtestpass1", "admin@uxtest.local", 400, 1),
    (2, "ALICE", "alicepass1", "alice@uxtest.local", 200, 3),
    (3, "BOB", "bobpass99", "bob@uxtest.local", 150, 30),
    (4, "CHARLIE", "charliepw1", "charlie@uxtest.local", 100, 60),
]


def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    if DB_PATH.exists():
        os.remove(DB_PATH)
    engine = create_engine(f"sqlite:///{DB_PATH}")
    acore.metadata.create_all(engine)
    now = datetime.utcnow()
    with engine.begin() as conn:
        for id_, user, pw, email, joined, seen in ACCOUNTS:
            salt = os.urandom(32)
            conn.execute(
                acore.account.insert().values(
                    id=id_,
                    username=user,
                    salt=salt,
                    verifier=calculate_verifier(user, pw, salt),
                    email=email,
                    totp_secret=None,
                    joindate=now - timedelta(days=joined),
                    last_login=now - timedelta(days=seen),
                )
            )
        # CHARLIE arrives pre-locked so the admin list shows a locked row
        conn.execute(
            acore.account_banned.insert().values(
                id=4, bandate=1, unbandate=0, bannedby="uxtest", banreason="seeded", active=1
            )
        )
    print(f"seeded {DB_PATH} with {len(ACCOUNTS)} accounts (CHARLIE locked)")


if __name__ == "__main__":
    main()
