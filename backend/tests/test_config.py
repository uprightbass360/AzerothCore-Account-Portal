from app.core.config import Settings, get_settings


def make_settings(**overrides) -> Settings:
    defaults = {"_env_file": None}
    defaults.update(overrides)
    return Settings(**defaults)


def test_defaults():
    s = make_settings()
    assert s.database_url.startswith("sqlite+aiosqlite")
    assert s.soap_url == "http://ac-worldserver:7878/"
    assert s.invite_ttl_days == 7
    assert s.session_ttl_days == 7
    assert s.server_name == "AzerothCore"


def test_server_name_env(monkeypatch):
    monkeypatch.setenv("PORTAL_SERVER_NAME", "My Realm")
    assert make_settings().server_name == "My Realm"


def test_server_name_falls_back_to_totp_issuer(monkeypatch):
    monkeypatch.setenv("PORTAL_TOTP_ISSUER", "Legacy Realm")
    assert make_settings().server_name == "Legacy Realm"


def test_server_name_wins_over_totp_issuer(monkeypatch):
    monkeypatch.setenv("PORTAL_SERVER_NAME", "New Realm")
    monkeypatch.setenv("PORTAL_TOTP_ISSUER", "Legacy Realm")
    assert make_settings().server_name == "New Realm"


def test_env_prefix(monkeypatch):
    monkeypatch.setenv("PORTAL_SOAP_USER", "gmbot")
    monkeypatch.setenv("PORTAL_INVITE_TTL_DAYS", "3")
    s = make_settings()
    assert s.soap_user == "gmbot"
    assert s.invite_ttl_days == 3


def test_admin_username_list_parses_and_uppercases():
    s = make_settings(admin_usernames=" alice, bob ,")
    assert s.admin_username_list == ["ALICE", "BOB"]
    assert make_settings().admin_username_list == []


def test_get_settings_cached():
    assert get_settings() is get_settings()
