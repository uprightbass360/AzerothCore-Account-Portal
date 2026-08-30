"""Fake AzerothCore SOAP server for local UX testing.

Speaks the urn:AC executeCommand envelope and applies account commands to the
SQLite acore_auth stand-in, so registration / password change / 2FA / lock
work end-to-end without a worldserver.

Run with the backend venv: uv run --project backend python tools/uxtest/fake_soap.py
"""

import base64
import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).parents[2] / "backend"))

from app.core.srp6 import calculate_verifier  # noqa: E402

DB_PATH = Path(__file__).parent / ".data" / "acore.db"
PORT = 7878

OK = (
    '<?xml version="1.0"?><SOAP-ENV:Envelope '
    'xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="urn:AC">'
    "<SOAP-ENV:Body><ns1:executeCommandResponse><result>{result}</result>"
    "</ns1:executeCommandResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>"
)
FAULT = (
    '<?xml version="1.0"?><SOAP-ENV:Envelope '
    'xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
    "<SOAP-ENV:Body><SOAP-ENV:Fault><faultcode>SOAP-ENV:Client</faultcode>"
    "<faultstring>{msg}</faultstring></SOAP-ENV:Fault></SOAP-ENV:Body></SOAP-ENV:Envelope>"
)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def account_id(conn: sqlite3.Connection, user: str) -> int | None:
    row = conn.execute(
        "SELECT id FROM account WHERE upper(username)=?", (user.upper(),)
    ).fetchone()
    return row["id"] if row else None


def handle(command: str) -> tuple[str, str | None]:
    """Returns (result, fault). One of the two is None-ish."""
    conn = db()
    try:
        if command == "server info":
            return "AzerothCore rev. uxtest-fake (local UX harness)", None

        if m := re.fullmatch(r"account create (\S+) (\S+)", command):
            user, pw = m.group(1).upper(), m.group(2)
            if account_id(conn, user) is not None:
                return "", "Account with this name already exist!"
            salt = os.urandom(32)
            next_id = (conn.execute("SELECT COALESCE(MAX(id),0)+1 AS n FROM account").fetchone())["n"]
            conn.execute(
                "INSERT INTO account (id, username, salt, verifier, email, totp_secret, joindate)"
                " VALUES (?,?,?,?,NULL,NULL,?)",
                (next_id, user, salt, calculate_verifier(user, pw, salt),
                 datetime.utcnow().isoformat(sep=" ")),
            )
            conn.commit()
            return f"Account created: {user}", None

        if m := re.fullmatch(r"account set password (\S+) (\S+) \2", command):
            user, pw = m.group(1).upper(), m.group(2)
            if account_id(conn, user) is None:
                return "", "Account not exist"
            salt = os.urandom(32)
            conn.execute(
                "UPDATE account SET salt=?, verifier=? WHERE upper(username)=?",
                (salt, calculate_verifier(user, pw, salt), user),
            )
            conn.commit()
            return "The password was changed", None

        if m := re.fullmatch(r"account set email (\S+) (\S+) \2", command):
            user, email = m.group(1).upper(), m.group(2)
            if account_id(conn, user) is None:
                return "", "Account not exist"
            conn.execute("UPDATE account SET email=? WHERE upper(username)=?", (email, user))
            conn.commit()
            return "Email set", None

        if m := re.fullmatch(r"account set 2fa (\S+) off", command):
            user = m.group(1).upper()
            conn.execute("UPDATE account SET totp_secret=NULL WHERE upper(username)=?", (user,))
            conn.commit()
            return "2FA disabled", None

        if m := re.fullmatch(r"account set 2fa (\S+) ([A-Z2-7]{16})", command):
            user, secret = m.group(1).upper(), m.group(2)
            if account_id(conn, user) is None:
                return "", "Account not exist"
            conn.execute(
                "UPDATE account SET totp_secret=? WHERE upper(username)=?",
                (base64.b32decode(secret), user),
            )
            conn.commit()
            return "2FA enabled", None

        if m := re.fullmatch(r"ban account (\S+) -1 (.+)", command):
            user = m.group(1).upper()
            aid = account_id(conn, user)
            if aid is None:
                return "", "Account not exist"
            conn.execute(
                "INSERT INTO account_banned (id, bandate, unbandate, bannedby, banreason, active)"
                " VALUES (?,?,0,'uxtest',?,1)",
                (aid, int(datetime.utcnow().timestamp()), m.group(2)),
            )
            conn.commit()
            return f"Account {user} banned", None

        if m := re.fullmatch(r"unban account (\S+)", command):
            user = m.group(1).upper()
            aid = account_id(conn, user)
            if aid is None:
                return "", "Account not exist"
            conn.execute("UPDATE account_banned SET active=0 WHERE id=?", (aid,))
            conn.commit()
            return f"Account {user} unbanned", None

        return "", f"There is no such command: {command.split()[0]}"
    finally:
        conn.close()


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        try:
            root = ET.fromstring(body)
            command = (root.find(".//command").text or "").strip()
        except Exception:
            self._send(500, FAULT.format(msg="unparseable request"))
            return
        result, fault = handle(command)
        print(f"[fake-soap] {command!r} -> {fault or result!r}", flush=True)
        if fault:
            self._send(500, FAULT.format(msg=escape(fault)))
        else:
            self._send(200, OK.format(result=escape(result)))

    def _send(self, status: int, payload: str) -> None:
        data = payload.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/xml")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # quiet default access log
        pass


if __name__ == "__main__":
    print(f"fake SOAP listening on :{PORT}, db={DB_PATH}", flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
