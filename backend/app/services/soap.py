"""AzerothCore SOAP client (urn:AC executeCommand)."""

import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

import httpx

_ENVELOPE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" '
    'xmlns:ns1="urn:AC"><SOAP-ENV:Body><ns1:executeCommand><command>{command}</command>'
    "</ns1:executeCommand></SOAP-ENV:Body></SOAP-ENV:Envelope>"
)


class SoapError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


def _extract(text: str) -> str:
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SoapError(f"unparseable SOAP response: {exc}") from exc
    fault = root.find(".//faultstring")
    if fault is not None:
        raise SoapError(fault.text or "SOAP fault")
    result = root.find(".//result")
    return (result.text or "") if result is not None else ""


class SoapClient:
    def __init__(self, url: str, username: str, password: str, timeout: float = 5.0) -> None:
        self._url = url
        self._auth = (username, password)
        self._timeout = timeout

    async def execute(self, command: str) -> str:
        body = _ENVELOPE.format(command=escape(command))
        last_exc: Exception | None = None
        for _ in range(2):  # one retry on transport errors
            try:
                async with httpx.AsyncClient(auth=self._auth, timeout=self._timeout) as client:
                    resp = await client.post(
                        self._url, content=body, headers={"Content-Type": "text/xml"}
                    )
                return _extract(resp.text)
            except httpx.HTTPError as exc:
                last_exc = exc
        raise SoapError(f"SOAP transport failure: {last_exc}")

    async def account_create(self, username: str, password: str) -> str:
        return await self.execute(f"account create {username} {password}")

    async def set_password(self, username: str, password: str) -> str:
        return await self.execute(f"account set password {username} {password} {password}")

    async def set_email(self, username: str, email: str) -> str:
        return await self.execute(f"account set email {username} {email} {email}")

    async def set_2fa(self, username: str, secret: str) -> str:
        return await self.execute(f"account set 2fa {username} {secret}")

    async def disable_2fa(self, username: str) -> str:
        return await self.execute(f"account set 2fa {username} off")

    async def ban(self, username: str, reason: str) -> str:
        return await self.execute(f"ban account {username} -1 {reason}")

    async def unban(self, username: str) -> str:
        return await self.execute(f"unban account {username}")

    async def server_info(self) -> str:
        return await self.execute("server info")
