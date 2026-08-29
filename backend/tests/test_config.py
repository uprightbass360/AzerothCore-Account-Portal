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
    assert s.totp_issuer == "AzerothCore"


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
