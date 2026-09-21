import logging

from app.services.email_content import (
    DEFAULT_THEME,
    EmailContentConfig,
    Link,
    Module,
    RealmEntry,
    Step,
    load_content,
    load_theme,
)

FULL = """
[realm]
Realmlist = "set realmlist logon.test"
"Client version" = "3.3.5a"

[[steps]]
text = "One"
[[steps]]
text = "Two"

[[module]]
name = "Solo Craft"
note = "Scales dungeons"
url = "https://example.com/solocraft"
[[module]]
name = "Transmog"

[[link]]
label = "Discord"
url = "https://discord.gg/x"
note = "Chat"
[[link]]
label = "Wiki"
url = "https://wiki.test"
"""


def test_load_content_full(tmp_path):
    p = tmp_path / "content.toml"
    p.write_text(FULL)
    cfg = load_content(p)
    assert cfg.realm == (
        RealmEntry("Realmlist", "set realmlist logon.test"),
        RealmEntry("Client version", "3.3.5a"),
    )
    assert cfg.steps == (Step("One"), Step("Two"))
    assert cfg.modules == (
        Module("Solo Craft", "Scales dungeons", "https://example.com/solocraft"),
        Module("Transmog"),
    )
    assert cfg.links == (
        Link("Discord", "https://discord.gg/x", "Chat"),
        Link("Wiki", "https://wiki.test"),
    )


def test_load_content_missing_file_is_empty():
    assert load_content(None) == EmailContentConfig()


def test_load_content_empty_file_is_empty(tmp_path):
    p = tmp_path / "content.toml"
    p.write_text("")
    assert load_content(p) == EmailContentConfig()


def test_load_content_malformed_falls_back_and_warns(tmp_path, caplog):
    p = tmp_path / "content.toml"
    p.write_text("this = = is not toml")
    with caplog.at_level(logging.WARNING, logger="portal.email"):
        assert load_content(p) == EmailContentConfig()
    assert "content.toml" in caplog.text


def test_load_content_unreadable_falls_back(tmp_path):
    # a directory raises OSError on open(); treated like malformed
    assert load_content(tmp_path) == EmailContentConfig()


def test_entry_missing_required_field_is_skipped(tmp_path, caplog):
    p = tmp_path / "content.toml"
    p.write_text(
        '[[module]]\nnote = "no name"\n[[module]]\nname = "Kept"\n'
        '[[link]]\nlabel = "no url"\n[[link]]\nlabel = "L"\nurl = "http://l"\n'
        '[[steps]]\ntext = 5\n[[steps]]\ntext = "ok"\n'
    )
    with caplog.at_level(logging.WARNING, logger="portal.email"):
        cfg = load_content(p)
    assert cfg.modules == (Module("Kept"),)
    assert cfg.links == (Link("L", "http://l"),)
    assert cfg.steps == (Step("ok"),)
    assert "skipping" in caplog.text


def test_wrong_shapes_are_ignored(tmp_path):
    p = tmp_path / "content.toml"
    p.write_text('realm = "not a table"\nsteps = "not an array"\nlink = [1, 2]\n')
    assert load_content(p) == EmailContentConfig()


def test_realm_skips_non_string_values(tmp_path):
    p = tmp_path / "content.toml"
    p.write_text('[realm]\nPort = 3724\nHost = "logon.test"\nEmpty = ""\n')
    assert load_content(p).realm == (RealmEntry("Host", "logon.test"),)


def test_optional_fields_default_to_empty_when_wrong_type(tmp_path):
    p = tmp_path / "content.toml"
    p.write_text('[[module]]\nname = "M"\nnote = 7\nurl = false\n')
    assert load_content(p).modules == (Module("M", "", ""),)


def test_load_theme_missing_is_default():
    assert load_theme(None) == DEFAULT_THEME
    assert "color_night" in DEFAULT_THEME and "font_body" in DEFAULT_THEME


def test_load_theme_overrides_known_keys_only(tmp_path):
    p = tmp_path / "theme.toml"
    p.write_text(
        '[color]\nnight = "#000"\nbogus = "#fff"\nparchment = 3\n[font]\nbody = "Arial"\nunused = "x"\n'
    )
    theme = load_theme(p)
    assert theme["color_night"] == "#000"
    assert theme["font_body"] == "Arial"
    assert theme["color_parchment"] == DEFAULT_THEME["color_parchment"]
    assert "color_bogus" not in theme and "font_unused" not in theme


def test_load_theme_ignores_non_table_sections(tmp_path):
    p = tmp_path / "theme.toml"
    p.write_text('color = "nope"\n')
    assert load_theme(p) == DEFAULT_THEME


def test_load_theme_malformed_is_default(tmp_path):
    p = tmp_path / "theme.toml"
    p.write_text("[[[")
    assert load_theme(p) == DEFAULT_THEME
