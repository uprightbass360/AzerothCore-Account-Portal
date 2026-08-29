import httpx
import pytest
import respx

from app.services.soap import SoapClient, SoapError

URL = "http://soap.test/"


def ok(result: str) -> httpx.Response:
    return httpx.Response(
        200,
        text=(
            '<?xml version="1.0"?><SOAP-ENV:Envelope '
            'xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ns1="urn:AC">'
            f"<SOAP-ENV:Body><ns1:executeCommandResponse><result>{result}</result>"
            "</ns1:executeCommandResponse></SOAP-ENV:Body></SOAP-ENV:Envelope>"
        ),
    )


def fault(msg: str) -> httpx.Response:
    return httpx.Response(
        500,
        text=(
            '<?xml version="1.0"?><SOAP-ENV:Envelope '
            'xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">'
            "<SOAP-ENV:Body><SOAP-ENV:Fault><faultcode>SOAP-ENV:Client</faultcode>"
            f"<faultstring>{msg}</faultstring></SOAP-ENV:Fault></SOAP-ENV:Body></SOAP-ENV:Envelope>"
        ),
    )


@pytest.fixture
def client():
    return SoapClient(URL, "gm", "pw")


@respx.mock
async def test_execute_success_sends_auth_and_command(client):
    route = respx.post(URL).mock(return_value=ok("Account created: BOB"))
    result = await client.execute("account create BOB pw")
    assert result == "Account created: BOB"
    req = route.calls.last.request
    assert b"account create BOB pw" in req.content
    assert req.headers["Authorization"].startswith("Basic ")
    assert "text/xml" in req.headers["Content-Type"]


@respx.mock
async def test_execute_fault_raises(client):
    respx.post(URL).mock(return_value=fault("Account already exist!"))
    with pytest.raises(SoapError) as e:
        await client.execute("account create BOB pw")
    assert "exist" in e.value.message


@respx.mock
async def test_transport_error_retries_once_then_raises(client):
    route = respx.post(URL).mock(side_effect=httpx.ConnectError("down"))
    with pytest.raises(SoapError):
        await client.execute("server info")
    assert route.call_count == 2


@respx.mock
async def test_transport_error_then_success(client):
    route = respx.post(URL)
    route.side_effect = [httpx.ConnectError("blip"), ok("ok")]
    assert await client.execute("server info") == "ok"


@respx.mock
async def test_command_is_xml_escaped(client):
    route = respx.post(URL).mock(return_value=ok("x"))
    await client.execute("a <b> & 'c'")
    assert b"a &lt;b&gt; &amp;" in route.calls.last.request.content


@respx.mock
async def test_unparseable_response_raises(client):
    respx.post(URL).mock(return_value=httpx.Response(200, text="not xml"))
    with pytest.raises(SoapError):
        await client.execute("server info")


@respx.mock
async def test_helpers_build_commands(client):
    route = respx.post(URL).mock(return_value=ok("done"))
    await client.account_create("BOB", "pw12345678")
    assert b"account create BOB pw12345678" in route.calls.last.request.content
    await client.set_password("BOB", "newpw123")
    assert b"account set password BOB newpw123 newpw123" in route.calls.last.request.content
    await client.set_email("BOB", "b@c.d")
    assert b"account set email BOB b@c.d b@c.d" in route.calls.last.request.content
    await client.set_2fa("BOB", "ABCDEFGHIJKLMNOP")
    assert b"account set 2fa BOB ABCDEFGHIJKLMNOP" in route.calls.last.request.content
    await client.disable_2fa("BOB")
    assert b"account set 2fa BOB off" in route.calls.last.request.content
    await client.ban("BOB", "Locked via portal")
    assert b"ban account BOB -1 Locked via portal" in route.calls.last.request.content
    await client.unban("BOB")
    assert b"unban account BOB" in route.calls.last.request.content
    await client.server_info()
    assert b"server info" in route.calls.last.request.content
