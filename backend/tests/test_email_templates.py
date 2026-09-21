import re
from pathlib import Path

import pytest

from app.services import email_templates
from app.services.email_templates import TemplateSet


def test_invite_content():
    c = email_templates.invite("Test Realm", "http://portal.test/register/tok", 7)
    assert "Test Realm" in c.subject
    assert "http://portal.test/register/tok" in c.text
    assert "7 days" in c.text
    assert "http://portal.test/register/tok" in c.html
    assert "7 days" in c.html
    assert "Create your account" in c.html


def test_password_reset_content():
    c = email_templates.password_reset(
        "Test Realm", "VICTIM", "http://portal.test/reset-password/tok", 48
    )
    assert "VICTIM" in c.subject
    assert "http://portal.test/reset-password/tok" in c.text
    assert "old password no longer works" in c.text
    assert "48 hours" in c.text
    assert "http://portal.test/reset-password/tok" in c.html
    assert "VICTIM" in c.html
    assert "Choose a new password" in c.html


def test_email_change_content():
    c = email_templates.email_change("Test Realm", "http://portal.test/confirm-email/tok", 24)
    assert "Confirm your new email" in c.subject
    assert "http://portal.test/confirm-email/tok" in c.text
    assert "24 hours" in c.text
    assert "http://portal.test/confirm-email/tok" in c.html
    assert "Confirm the email change" in c.html


def test_all_emails_share_themed_layout():
    contents = [
        email_templates.invite("R", "http://l", 7),
        email_templates.password_reset("R", "U", "http://l", 48),
        email_templates.email_change("R", "http://l", 24),
    ]
    for c in contents:
        # portal theme markers: night ground, quest-gold headings, gold button
        assert "#07090f" in c.html
        assert "#ffd100" in c.html
        assert "#e8c552" in c.html


def test_html_escapes_dynamic_values():
    c = email_templates.invite("Realm & <Friends>", "http://l", 7)
    assert "Realm &amp; &lt;Friends&gt;" in c.html
    # plain text part is not escaped
    assert "Realm & <Friends>" in c.text


REPO_ROOT = Path(__file__).resolve().parents[2]

CONTENT = """
[realm]
Realmlist = "set realmlist logon.test"
"Client version" = "3.3.5a"

[[steps]]
text = "Make an account"
[[steps]]
text = "Log in"

[[module]]
name = "Solo Craft"
note = "Scales dungeons"
url = "https://example.com/solo"
[[module]]
name = "Plain Module"
[[module]]
name = "Noted"
note = "just a note"
[[module]]
name = "Linked"
url = "https://example.com/linked"

[[link]]
label = "Discord"
url = "https://discord.gg/x"
note = "Chat & help"
[[link]]
label = "Wiki"
url = "https://wiki.test"
"""


@pytest.fixture
def override(tmp_path) -> Path:
    d = tmp_path / "override"
    d.mkdir()
    return d


@pytest.fixture
def templates(override) -> TemplateSet:
    return TemplateSet((override, TemplateSet.default().dirs[0]))


def test_invite_renders_every_block_in_html_and_text(override, templates):
    (override / "content.toml").write_text(CONTENT)
    c = email_templates.invite("Realm", "http://l", 7, templates=templates)
    for part in (c.html, c.text):
        assert "How to connect" in part
        assert "set realmlist logon.test" in part and "3.3.5a" in part
        assert "Getting started" in part and "Make an account" in part and "Log in" in part
        assert "What this realm runs" in part and "Solo Craft" in part
        assert "Links" in part and "https://discord.gg/x" in part and "https://wiki.test" in part
    # order: realm, steps, modules, links, then the expiry footer
    idx = [
        c.html.index(s)
        for s in (
            "How to connect",
            "Getting started",
            "What this realm runs",
            "Links",
            "expires in 7 days",
        )
    ]
    assert idx == sorted(idx)
    assert "1. Make an account" in c.text and "2. Log in" in c.text


def test_invite_module_row_variants(override, templates):
    (override / "content.toml").write_text(CONTENT)
    c = email_templates.invite("Realm", "http://l", 7, templates=templates)
    assert '<a href="https://example.com/solo"' in c.html and "Scales dungeons" in c.html
    assert "<b>Plain Module</b>" in c.html
    assert "<b>Noted</b><br>" in c.html and "just a note" in c.html
    assert '<a href="https://example.com/linked"' in c.html
    assert "- Solo Craft: Scales dungeons (https://example.com/solo)" in c.text
    assert "- Plain Module\n" in c.text
    assert "- Noted: just a note\n" in c.text
    assert "- Linked (https://example.com/linked)" in c.text
    assert "- Discord (Chat & help): https://discord.gg/x" in c.text
    assert "- Wiki: https://wiki.test" in c.text


def test_invite_omits_unconfigured_blocks(override, templates):
    (override / "content.toml").write_text('[[link]]\nlabel = "Only"\nurl = "http://only"\n')
    c = email_templates.invite("Realm", "http://l", 7, templates=templates)
    for part in (c.html, c.text):
        assert "How to connect" not in part
        assert "Getting started" not in part
        assert "What this realm runs" not in part
        assert "Links" in part and "http://only" in part


def test_invite_with_empty_content_has_no_blocks(override, templates):
    (override / "content.toml").write_text("")
    c = email_templates.invite("Realm", "http://l", 7, templates=templates)
    assert "<h2" not in c.html
    assert c.text.count("\n\n") == 2  # intro / link / footer only


def test_reset_and_change_never_carry_blocks(override, templates):
    (override / "content.toml").write_text(CONTENT)
    for c in (
        email_templates.password_reset("R", "U", "http://l", 48, templates=templates),
        email_templates.email_change("R", "http://l", 24, templates=templates),
    ):
        assert "What this realm runs" not in c.html and "How to connect" not in c.text


def test_block_content_is_escaped_in_html_only(override, templates):
    (override / "content.toml").write_text(
        '[realm]\n"A <b>" = "x & y"\n[[module]]\nname = "<M>"\nurl = "http://m/?a=1&b=2"\n'
    )
    c = email_templates.invite("Realm", "http://l", 7, templates=templates)
    assert "A &lt;b&gt;" in c.html and "x &amp; y" in c.html and "&lt;M&gt;" in c.html
    assert 'href="http://m/?a=1&amp;b=2"' in c.html
    assert "A <b>: x & y" in c.text and "<M> (http://m/?a=1&b=2)" in c.text


def test_module_with_rejected_url_scheme_renders_unlinked(override, templates):
    (override / "content.toml").write_text(
        '[[module]]\nname = "Evil"\nurl = "javascript:alert(1)"\n'
    )
    c = email_templates.invite("Realm", "http://l", 7, templates=templates)
    assert "javascript:" not in c.html
    assert "javascript:" not in c.text


def test_theme_values_flow_into_html(override, templates):
    (override / "theme.toml").write_text('[color]\nquestgold = "#123456"\n')
    c = email_templates.invite("Realm", "http://l", 7, templates=templates)
    assert "#123456" in c.html and "#ffd100" not in c.html


def test_no_unresolved_placeholders(override, templates):
    (override / "content.toml").write_text(CONTENT)
    for c in (
        email_templates.invite("R", "http://l", 7, templates=templates),
        email_templates.password_reset("R", "U", "http://l", 48, templates=templates),
        email_templates.email_change("R", "http://l", 24, templates=templates),
    ):
        for part in (c.subject, c.text, c.html):
            assert not re.search(r"\$\{|\$[A-Za-z]", part), part


def test_in_place_edit_is_picked_up_without_restart(override, templates):
    p = override / "content.toml"
    p.write_text('[[link]]\nlabel = "First"\nurl = "http://1"\n')
    assert "http://1" in email_templates.invite("R", "http://l", 7, templates=templates).text
    p.write_text('[[link]]\nlabel = "Second"\nurl = "http://2"\n')
    c = email_templates.invite("R", "http://l", 7, templates=templates)
    assert "http://2" in c.text and "http://1" not in c.text


def test_override_of_one_file_keeps_the_rest(override, templates):
    (override / "invite.toml").write_text('subject = "Join ${server_name}!"\nbutton_label = "Go"\n')
    c = email_templates.invite("Realm", "http://l", 7, templates=templates)
    assert c.subject == "Join Realm!"
    assert ">Go</a>" in c.html
    assert "You've been invited" in c.html  # invite.html still from baked


def test_theme_matches_layout_css():
    css = (REPO_ROOT / "frontend" / "src" / "routes" / "layout.css").read_text()
    theme = (REPO_ROOT / "templates" / "email" / "theme.toml").read_text()
    shared = {
        "night": "--color-night",
        "panel": "--color-panel",
        "gold_deep": "--color-gold-deep",
        "gold_corner": "--color-gold-corner",
        "questgold": "--color-questgold",
        "parchment": "--color-parchment",
    }
    for key, var in shared.items():
        css_value = re.search(rf"{var}:\s*(#[0-9a-fA-F]{{6}})", css).group(1)
        toml_value = re.search(rf'^{key}\s*=\s*"(#[0-9a-fA-F]{{6}})"', theme, re.MULTILINE).group(1)
        assert css_value.lower() == toml_value.lower(), key
