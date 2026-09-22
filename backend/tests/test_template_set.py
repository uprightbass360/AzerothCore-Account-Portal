import shutil
from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.email_templates import (
    BLOCKS,
    EMAILS,
    TemplateSet,
    _split_partial,
    baked_dir,
)

REPO_TEMPLATES = Path(__file__).resolve().parents[2] / "templates" / "email"


@pytest.fixture
def baked(tmp_path) -> Path:
    """A private copy of the shipped templates to mutate."""
    dst = tmp_path / "baked"
    shutil.copytree(REPO_TEMPLATES, dst)
    return dst


def test_baked_dir_prefers_cwd_copy(tmp_path, monkeypatch):
    (tmp_path / "templates" / "email").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    assert baked_dir() == tmp_path / "templates" / "email"


def test_baked_dir_falls_back_to_repo_copy(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert baked_dir() == REPO_TEMPLATES


def test_default_and_from_settings():
    assert TemplateSet.default().dirs == (baked_dir(),)
    s = Settings(_env_file=None, email_template_dir="/over")
    assert TemplateSet.from_settings(s).dirs == (Path("/over"), baked_dir())
    s = Settings(_env_file=None)
    assert TemplateSet.from_settings(s).dirs == (baked_dir(),)


def test_find_prefers_override_then_baked_then_none(tmp_path, baked):
    override = tmp_path / "override"
    override.mkdir()
    (override / "content.toml").write_text("")
    ts = TemplateSet((override, baked))
    assert ts.find("content.toml") == override / "content.toml"
    assert ts.find("base.html") == baked / "base.html"
    assert ts.find("nope.html") is None


def test_read_missing_raises_with_search_path(tmp_path):
    ts = TemplateSet((tmp_path,))
    with pytest.raises(FileNotFoundError, match="base.html"):
        ts.read("base.html")


def test_meta_reads_subject_and_button(baked):
    m = TemplateSet((baked,)).meta("invite")
    assert m == {
        "subject": "You're invited to join ${server_name}",
        "button_label": "Create your account",
    }


def test_meta_requires_both_keys(baked):
    (baked / "invite.toml").write_text('subject = "x"\n')
    with pytest.raises(ValueError, match="invite.toml"):
        TemplateSet((baked,)).meta("invite")


def test_meta_requires_string_values(baked):
    (baked / "invite.toml").write_text('subject = 5\nbutton_label = "x"\n')
    with pytest.raises(ValueError, match="invite.toml"):
        TemplateSet((baked,)).check()


def test_split_partial():
    wrapper, rows = _split_partial("W\n${rows}\n<!-- row -->\nA\n<!-- row:note -->\nB\n")
    assert wrapper == "W\n${rows}\n"
    assert rows == {"": "A\n", "note": "B\n"}


def test_check_passes_on_shipped_templates():
    TemplateSet.default().check()


def test_check_reports_missing_file(baked):
    (baked / "partials" / "install.txt").unlink()
    with pytest.raises(FileNotFoundError, match="partials/install.txt"):
        TemplateSet((baked,)).check()


def test_check_reports_missing_row_variant(baked):
    p = baked / "partials" / "modules.html"
    text = p.read_text()
    p.write_text(text[: text.index("<!-- row:note:url -->")])
    with pytest.raises(ValueError, match="modules.html.*note:url"):
        TemplateSet((baked,)).check()


def test_check_reports_bad_meta(baked):
    (baked / "email_change.toml").write_text("[[[")
    with pytest.raises(ValueError, match="email_change.toml"):
        TemplateSet((baked,)).check()


def test_check_reports_wrapper_missing_rows_placeholder(baked):
    p = baked / "partials" / "links.html"
    text = p.read_text()
    p.write_text(text.replace("${rows}", ""))
    with pytest.raises(ValueError, match=r"links\.html.*\$\{rows\}"):
        TemplateSet((baked,)).check()


def test_block_and_email_registries():
    assert EMAILS == ("invite", "password_reset", "email_change")
    assert BLOCKS == {
        "install": ("url",),
        "modules": ("note", "url"),
        "configure": ("url",),
        "links": ("note",),
    }
