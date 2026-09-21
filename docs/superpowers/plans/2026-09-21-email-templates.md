# Email Templates Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move every portal email into an editable `templates/email/` folder at the repo root, themed from one `theme.toml`, with an invite that carries realm details, getting-started steps, an admin-declared module list, and optional links.

**Architecture:** `email_content.py` parses `content.toml`/`theme.toml` into frozen dataclasses and degrades to defaults on bad input. `email_templates.py` resolves each file through a search path (override dir → baked dir), renders `string.Template` files with row-variant partials, and returns the existing `EmailContent`. `TemplateSet.check()` runs at boot so a broken image fails on the operator's screen, not in a player's inbox. Docker bakes `templates/` into the image and bind-mounts the host copy to a separate override path.

**Tech Stack:** Python 3.12 stdlib only (`string.Template`, `tomllib`, `html.escape`), FastAPI, pytest with 100% branch coverage enforced, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-21-email-templates-design.md`

## Global Constraints

- No new Python dependency. `tomllib` and `string.Template` are stdlib on the `>=3.12` floor.
- `backend/pyproject.toml` enforces `--cov-fail-under=100` with `branch = true`. Every `if`/`except`/loop-exhausted path you write needs a test that reaches it, or CI fails.
- All email CSS inline; no `<style>` blocks, no webfonts, no external assets; table-based layout.
- Everything interpolated into HTML is passed through `html.escape(..., quote=True)` — including admin-authored TOML values and theme values. Plain-text parts and subjects are not escaped.
- No wording lives in Python. Headings, sentences, labels, and button text live in template files. Numbers, separators computed by row variants, and escaping are the only Python-side contributions to output.
- A content error (`content.toml`, `theme.toml`) must never block a send. A missing template file must never reach a send — it fails at boot.
- Ruff: line length 100. Run `uv run ruff check . && uv run ruff format .` before every commit.
- All backend commands run from `backend/`: `cd backend && uv run pytest`. Tests therefore have `cwd == backend/`.
- Commit messages end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` and nothing else (no session links).
- Work on branch `feat/email-templates-folder`; `main` requires a PR.

## File Structure

| Path | Responsibility |
|------|----------------|
| `backend/app/services/email_content.py` | **Create.** Parse `content.toml` and `theme.toml` into `EmailContentConfig` / theme dict. Never raises on bad input. |
| `backend/app/services/email_templates.py` | **Rewrite.** `TemplateSet` (search path, `find`/`read`/`meta`/`check`), partial splitting, block rendering, the three public builders. |
| `backend/app/services/mailer.py` | **Modify.** Accept a `TemplateSet`, pass it to the builders. |
| `backend/app/core/config.py` | **Modify.** Add `email_template_dir: str = ""`. |
| `backend/app/main.py` | **Modify.** Build `TemplateSet`, call `check()`, hand it to `Mailer`. |
| `templates/email/**` | **Create.** 19 files: base, 3 × (html, txt, toml), 8 partials, content.toml, theme.toml, README.md. |
| `backend/tests/test_email_content.py` | **Create.** Parsing and degradation. |
| `backend/tests/test_template_set.py` | **Create.** Resolution, `check()`, baked-dir lookup. |
| `backend/tests/test_email_templates.py` | **Modify.** Existing tests kept verbatim as the regression net; add block rendering, escaping, hot-edit, theme drift. |
| `backend/tests/test_mailer.py`, `test_app.py`, `test_config.py` | **Modify.** Wiring coverage. |
| `backend/Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.github/workflows/ci.yml` | **Modify/Create.** Root build context, override mount, ignore list. |
| `README.md`, `.env.template` | **Modify.** Document the folder. |

---

### Task 1: Content parsing (`email_content.py`)

**Files:**
- Create: `backend/app/services/email_content.py`
- Test: `backend/tests/test_email_content.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces:
  ```python
  @dataclass(frozen=True) class RealmEntry: label: str; value: str
  @dataclass(frozen=True) class Step: text: str
  @dataclass(frozen=True) class Module: name: str; note: str = ""; url: str = ""
  @dataclass(frozen=True) class Link: label: str; url: str; note: str = ""
  @dataclass(frozen=True) class EmailContentConfig:
      realm: tuple[RealmEntry, ...] = ()
      steps: tuple[Step, ...] = ()
      modules: tuple[Module, ...] = ()
      links: tuple[Link, ...] = ()
  DEFAULT_THEME: dict[str, str]          # keys: color_night ... font_body
  def load_content(path: Path | None) -> EmailContentConfig
  def load_theme(path: Path | None) -> dict[str, str]
  ```
  Both loaders accept `None` (file not found anywhere) and return defaults.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_email_content.py
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
    assert cfg.links == (Link("Discord", "https://discord.gg/x", "Chat"), Link("Wiki", "https://wiki.test"))


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
    p.write_text('[color]\nnight = "#000"\nbogus = "#fff"\nparchment = 3\n[font]\nbody = "Arial"\nunused = "x"\n')
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_email_content.py --no-cov -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.email_content'`

- [ ] **Step 3: Write the implementation**

```python
# backend/app/services/email_content.py
"""Admin-editable email content and theme.

content.toml supplies the optional blocks of the invite email (realm details,
getting-started steps, modules, links); theme.toml supplies the colors and
fonts every email uses. Both are edited on the host and re-read on every send,
so they must never raise: any problem is logged and the affected part falls
back to its default. A typo here must not stop an invite going out.
"""

import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("portal.email")


@dataclass(frozen=True)
class RealmEntry:
    label: str
    value: str


@dataclass(frozen=True)
class Step:
    text: str


@dataclass(frozen=True)
class Module:
    name: str
    note: str = ""
    url: str = ""


@dataclass(frozen=True)
class Link:
    label: str
    url: str
    note: str = ""


@dataclass(frozen=True)
class EmailContentConfig:
    realm: tuple[RealmEntry, ...] = ()
    steps: tuple[Step, ...] = ()
    modules: tuple[Module, ...] = ()
    links: tuple[Link, ...] = ()


# Mirrors frontend/src/routes/layout.css; tests/test_email_templates.py checks the
# six shared colors stay in sync. Georgia stands in for Cinzel (no webfonts in mail).
DEFAULT_THEME: dict[str, str] = {
    "color_night": "#07090f",
    "color_panel": "#0b0e17",
    "color_gold_deep": "#8a6a14",
    "color_gold_corner": "#e8c552",
    "color_questgold": "#ffd100",
    "color_parchment": "#e8d9b0",
    "color_muted": "#8b8574",
    "color_faint": "#55503f",
    "color_button_text": "#1a1405",
    "font_display": "Georgia,'Times New Roman',serif",
    "font_body": "Helvetica,Arial,sans-serif",
}


def _read_toml(path: Path | None, label: str) -> dict:
    if path is None:
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        logger.warning("%s unreadable, using defaults: %s", label, exc)
        return {}


def _str(entry: dict, key: str) -> str:
    value = entry.get(key, "")
    return value if isinstance(value, str) else ""


def _entries(raw: dict, key: str, required: tuple[str, ...]) -> list[dict]:
    items = raw.get(key, [])
    if not isinstance(items, list):
        logger.warning("content.toml: [[%s]] must be an array of tables, ignoring", key)
        return []
    kept = []
    for entry in items:
        if not isinstance(entry, dict) or any(not _str(entry, k) for k in required):
            logger.warning("content.toml: skipping [[%s]] entry missing %s", key, "/".join(required))
            continue
        kept.append(entry)
    return kept


def load_content(path: Path | None) -> EmailContentConfig:
    raw = _read_toml(path, "content.toml")
    realm_raw = raw.get("realm", {})
    if not isinstance(realm_raw, dict):
        logger.warning("content.toml: [realm] must be a table, ignoring")
        realm_raw = {}
    return EmailContentConfig(
        realm=tuple(
            RealmEntry(k, v) for k, v in realm_raw.items() if isinstance(v, str) and v
        ),
        steps=tuple(Step(_str(e, "text")) for e in _entries(raw, "steps", ("text",))),
        modules=tuple(
            Module(_str(e, "name"), _str(e, "note"), _str(e, "url"))
            for e in _entries(raw, "module", ("name",))
        ),
        links=tuple(
            Link(_str(e, "label"), _str(e, "url"), _str(e, "note"))
            for e in _entries(raw, "link", ("label", "url"))
        ),
    )


def load_theme(path: Path | None) -> dict[str, str]:
    raw = _read_toml(path, "theme.toml")
    theme = dict(DEFAULT_THEME)
    for section in ("color", "font"):
        values = raw.get(section, {})
        if not isinstance(values, dict):
            continue
        for key, value in values.items():
            name = f"{section}_{key}"
            if name in theme and isinstance(value, str):
                theme[name] = value
    return theme
```

- [ ] **Step 4: Run tests to verify they pass, with full coverage of the new module**

Run: `cd backend && uv run pytest tests/test_email_content.py --cov=app.services.email_content --cov-branch --cov-report=term-missing --cov-fail-under=100 -q`
Expected: PASS, `email_content.py 100%`

- [ ] **Step 5: Lint, format, commit**

```bash
cd backend && uv run ruff check . && uv run ruff format .
git add app/services/email_content.py tests/test_email_content.py
git commit -m "feat(email): parse content.toml and theme.toml with safe fallbacks

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Template files and `TemplateSet` resolution

This task creates the shipped `templates/email/` folder and the class that finds files in it. `check()` is the test that the shipped files are complete, so they belong in the same task. Rendering comes in Task 3; leave the existing builders in `email_templates.py` untouched for now and add `TemplateSet` alongside them.

**Files:**
- Create: `templates/email/` (19 files, contents below)
- Modify: `backend/app/services/email_templates.py` (add `TemplateSet`, `baked_dir`, `_split_partial`; keep existing functions)
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_template_set.py`, `backend/tests/test_config.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  ```python
  def baked_dir() -> Path
  @dataclass(frozen=True)
  class TemplateSet:
      dirs: tuple[Path, ...]
      @classmethod default(cls) -> "TemplateSet"                 # (baked_dir(),)
      @classmethod from_settings(cls, settings: Settings) -> "TemplateSet"
      def find(self, name: str) -> Path | None                  # first dir containing name
      def read(self, name: str) -> str                          # raises FileNotFoundError
      def meta(self, name: str) -> dict[str, str]               # {"subject", "button_label"}; raises ValueError
      def check(self) -> None                                   # raises FileNotFoundError / ValueError
  def _split_partial(text: str) -> tuple[str, dict[str, str]]  # (wrapper, {variant: row})
  EMAILS = ("invite", "password_reset", "email_change")
  BLOCKS = {"realm": (), "steps": (), "modules": ("note", "url"), "links": ("note",)}
  ```
  `Settings.email_template_dir: str = ""` (env `PORTAL_EMAIL_TEMPLATE_DIR`).

- [ ] **Step 1: Create the template files**

Create every file below exactly. Paths are relative to the repo root.

`templates/email/theme.toml`:
```toml
# Colors and fonts for every portal email. Mirrors frontend/src/routes/layout.css;
# the backend test suite checks the six shared colors stay identical.
# Fonts must be mail-safe system fonts: clients do not load webfonts.

[color]
night = "#07090f"        # page background
panel = "#0b0e17"        # card background
gold_deep = "#8a6a14"    # card border
gold_corner = "#e8c552"  # card top rule, button, link text
questgold = "#ffd100"    # headings
parchment = "#e8d9b0"    # body text
muted = "#8b8574"        # footers, notes
faint = "#55503f"        # realm name under the card
button_text = "#1a1405"  # text on the gold button

[font]
display = "Georgia,'Times New Roman',serif"
body = "Helvetica,Arial,sans-serif"
```

`templates/email/content.toml`:
```toml
# Content for invite emails. Edit freely: changes apply on the next email sent,
# no restart needed. See README.md in this folder for the full reference.

# Connection details, shown as a label / value table. Any labels work.
# Uncomment and fill in for your realm.
# [realm]
# Realmlist = "set realmlist logon.example.com"
# "Client version" = "3.3.5a (12340)"

# Numbered getting-started steps.
[[steps]]
text = "Click the button above and pick a username and password."

[[steps]]
text = "Open your WoW folder, edit Data/enUS/realmlist.wtf, and set it to this realm's address."

[[steps]]
text = "Launch the game and log in with your new account."

# Modules this realm runs. This list is hand-maintained: the portal cannot ask
# the worldserver for it, so update it when you add or remove modules.
# `note` and `url` are optional.
# [[module]]
# name = "Solo Craft"
# note = "Scales dungeons and raids for solo or small-group play"
# url = "https://github.com/azerothcore/mod-solocraft"

# Community and download links. `note` is optional.
# [[link]]
# label = "Discord"
# url = "https://discord.gg/xxxx"
# note = "Get help and find groups"
```

`templates/email/base.html`:
```html
<body style="margin:0;padding:0;background-color:${color_night};">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:${color_night};">
<tr><td align="center" style="padding:32px 16px;">
<table role="presentation" width="480" cellpadding="0" cellspacing="0" style="max-width:480px;width:100%;background-color:${color_panel};border:1px solid ${color_gold_deep};border-top:3px solid ${color_gold_corner};">
<tr><td style="padding:32px 36px;">
${content}
</td></tr></table>
<p style="margin:16px 0 0;font-family:${font_body};font-size:11px;color:${color_faint};">${server_name}</p>
</td></tr></table></body>
```

`templates/email/partials/button.html`:
```html
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px 0;"><tr><td style="background-color:${color_gold_corner};"><a href="${link}" style="display:inline-block;padding:12px 28px;font-family:${font_display};font-size:15px;font-weight:700;letter-spacing:1px;color:${color_button_text};text-decoration:none;">${button_label}</a></td></tr></table>
```

`templates/email/partials/realm.html`:
```html
<h2 style="margin:24px 0 8px;font-family:${font_display};font-size:15px;font-weight:700;color:${color_questgold};">How to connect</h2>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 16px;font-family:${font_body};font-size:14px;line-height:1.6;color:${color_parchment};">
${rows}</table>
<!-- row -->
<tr><td style="padding:2px 12px 2px 0;color:${color_muted};white-space:nowrap;vertical-align:top;">${label}</td><td style="padding:2px 0;font-family:'Courier New',monospace;">${value}</td></tr>
```

`templates/email/partials/realm.txt`:
```
How to connect
${rows}
<!-- row -->
  ${label}: ${value}
```

`templates/email/partials/steps.html`:
```html
<h2 style="margin:24px 0 8px;font-family:${font_display};font-size:15px;font-weight:700;color:${color_questgold};">Getting started</h2>
<ol style="margin:0 0 16px;padding-left:20px;font-family:${font_body};font-size:14px;line-height:1.6;color:${color_parchment};">
${rows}</ol>
<!-- row -->
<li style="margin:0 0 6px;">${text}</li>
```

`templates/email/partials/steps.txt`:
```
Getting started
${rows}
<!-- row -->
  ${n}. ${text}
```

`templates/email/partials/modules.html`:
```html
<h2 style="margin:24px 0 8px;font-family:${font_display};font-size:15px;font-weight:700;color:${color_questgold};">What this realm runs</h2>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 16px;font-family:${font_body};font-size:14px;line-height:1.6;color:${color_parchment};">
${rows}</table>
<!-- row -->
<tr><td style="padding:4px 0;"><b>${name}</b></td></tr>
<!-- row:note -->
<tr><td style="padding:4px 0;"><b>${name}</b><br><span style="color:${color_muted};font-size:13px;">${note}</span></td></tr>
<!-- row:url -->
<tr><td style="padding:4px 0;"><a href="${url}" style="color:${color_gold_corner};font-weight:700;text-decoration:none;">${name}</a></td></tr>
<!-- row:note:url -->
<tr><td style="padding:4px 0;"><a href="${url}" style="color:${color_gold_corner};font-weight:700;text-decoration:none;">${name}</a><br><span style="color:${color_muted};font-size:13px;">${note}</span></td></tr>
```

`templates/email/partials/modules.txt`:
```
What this realm runs
${rows}
<!-- row -->
  - ${name}
<!-- row:note -->
  - ${name}: ${note}
<!-- row:url -->
  - ${name} (${url})
<!-- row:note:url -->
  - ${name}: ${note} (${url})
```

`templates/email/partials/links.html`:
```html
<h2 style="margin:24px 0 8px;font-family:${font_display};font-size:15px;font-weight:700;color:${color_questgold};">Links</h2>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 16px;font-family:${font_body};font-size:14px;line-height:1.6;color:${color_parchment};">
${rows}</table>
<!-- row -->
<tr><td style="padding:4px 0;"><a href="${url}" style="color:${color_gold_corner};font-weight:700;text-decoration:none;">${label}</a></td></tr>
<!-- row:note -->
<tr><td style="padding:4px 0;"><a href="${url}" style="color:${color_gold_corner};font-weight:700;text-decoration:none;">${label}</a> <span style="color:${color_muted};font-size:13px;">— ${note}</span></td></tr>
```

`templates/email/partials/links.txt`:
```
Links
${rows}
<!-- row -->
  - ${label}: ${url}
<!-- row:note -->
  - ${label} (${note}): ${url}
```

`templates/email/invite.toml`:
```toml
subject = "You're invited to join ${server_name}"
button_label = "Create your account"
```

`templates/email/invite.html`:
```html
<h1 style="margin:0 0 16px;font-family:${font_display};font-size:22px;font-weight:700;color:${color_questgold};">You're invited</h1>
<p style="margin:0 0 12px;font-family:${font_body};font-size:14px;line-height:1.6;color:${color_parchment};">You've been invited to create a game account on <b>${server_name}</b>.</p>
${button}
${blocks}
<p style="margin:0;font-family:${font_body};font-size:12px;color:${color_muted};">This invite expires in ${expires_days} days.</p>
```

`templates/email/invite.txt`:
```
You've been invited to create a game account on ${server_name}.

Register here: ${link}

${blocks}This invite expires in ${expires_days} days.
```

`templates/email/password_reset.toml`:
```toml
subject = "Set a new password for ${username} on ${server_name}"
button_label = "Choose a new password"
```

`templates/email/password_reset.html`:
```html
<h1 style="margin:0 0 16px;font-family:${font_display};font-size:22px;font-weight:700;color:${color_questgold};">Set a new password</h1>
<p style="margin:0 0 12px;font-family:${font_body};font-size:14px;line-height:1.6;color:${color_parchment};">An administrator reset the password for your <b>${server_name}</b> account <b>${username}</b>. Your old password no longer works.</p>
${button}
<p style="margin:0;font-family:${font_body};font-size:12px;color:${color_muted};">This link expires in ${expires_hours} hours.</p>
```

`templates/email/password_reset.txt`:
```
An administrator reset the password for your ${server_name} account ${username}.
Your old password no longer works.

Choose a new password here: ${link}

This link expires in ${expires_hours} hours.
```

`templates/email/email_change.toml`:
```toml
subject = "Confirm your new email for ${server_name}"
button_label = "Confirm the email change"
```

`templates/email/email_change.html`:
```html
<h1 style="margin:0 0 16px;font-family:${font_display};font-size:22px;font-weight:700;color:${color_questgold};">Confirm your new email</h1>
<p style="margin:0 0 12px;font-family:${font_body};font-size:14px;line-height:1.6;color:${color_parchment};">A request was made to use this address for a <b>${server_name}</b> game account.</p>
${button}
<p style="margin:0;font-family:${font_body};font-size:12px;color:${color_muted};">This link expires in ${expires_hours} hours. If you didn't request this, ignore this email.</p>
```

`templates/email/email_change.txt`:
```
A request was made to use this address for a ${server_name} game account.

Confirm the change here: ${link}

This link expires in ${expires_hours} hours. If you didn't request this, ignore this email.
```

`templates/email/README.md`:
````markdown
# Email templates

Everything the portal emails is built from the files in this folder. Edit them
on the host; the backend re-reads them on every send, so changes apply to the
next email with no restart.

## What to edit

| You want to… | Edit |
|---|---|
| Add your realmlist, modules, Discord link | `content.toml` |
| Change colors or fonts | `theme.toml` |
| Change the wording of an email | `<email>.html`, `<email>.txt` (both!) and `<email>.toml` (subject, button) |
| Change the card frame around every email | `base.html` |
| Change how a content block looks | `partials/<block>.html` / `.txt` |

`content.toml` and `theme.toml` are forgiving: a typo is logged and that part
falls back to its default, and the email still goes out. The other files are
checked when the backend starts, and it refuses to start if one is missing or
malformed, so a broken template is caught on your screen rather than in a
player's inbox.

## Where the files live

The Docker image ships its own copy of this folder. `docker-compose.yml`
mounts your `./templates` folder into the container as an **override**: for
each file, your copy wins if it exists, otherwise the shipped one is used. You
can therefore keep only `content.toml` in your override and delete the rest,
or copy everything and restyle it.

Outside Docker, set `PORTAL_EMAIL_TEMPLATE_DIR` to your override folder.

## Modules list

`[[module]]` entries are hand-maintained. AzerothCore does not expose a way
for the portal to ask the worldserver which modules are loaded, so this list
describes what you tell it, not what is running. Update it when you add or
remove a module.

## Placeholders

Files use `${name}` placeholders. A literal dollar sign is written `$$`.
Unknown placeholders are left as-is. Everything inserted into `.html` files is
HTML-escaped; `.txt` files receive raw text.

| Placeholder | Available in |
|---|---|
| `${server_name}` | every file |
| `${link}` | `<email>.html/.txt`, `partials/button.html` |
| `${expires_days}` | `invite.*` |
| `${expires_hours}` | `password_reset.*`, `email_change.*` |
| `${username}` | `password_reset.*` |
| `${button}` | `<email>.html` — the rendered `partials/button.html` |
| `${button_label}` | `partials/button.html` — from `<email>.toml` |
| `${blocks}` | `invite.html/.txt` — realm, steps, modules, links in that order |
| `${content}` | `base.html` — the rendered `<email>.html` |
| `${color_*}`, `${font_*}` | every `.html` file, from `theme.toml` |

### Partials and row variants

A partial is a wrapper followed by one or more row templates, separated by
marker lines. The wrapper contains `${rows}`; rows are rendered once per entry
and joined. A block with no entries renders nothing at all.

```html
<h2>Links</h2>
<table>
${rows}</table>
<!-- row -->
<tr><td><a href="${url}">${label}</a></td></tr>
<!-- row:note -->
<tr><td><a href="${url}">${label}</a> — ${note}</td></tr>
```

Optional fields pick the row variant. The variant name lists the optional
fields that are present, in this order:

| Block | Row fields | Optional | Required variants |
|---|---|---|---|
| `realm` | `${label}`, `${value}` | — | `row` |
| `steps` | `${n}`, `${text}` | — | `row` |
| `modules` | `${name}`, `${note}`, `${url}` | `note`, `url` | `row`, `row:note`, `row:url`, `row:note:url` |
| `links` | `${label}`, `${url}`, `${note}` | `note` | `row`, `row:note` |

The same markers are used in `.txt` partials.
````

- [ ] **Step 2: Add the setting**

In `backend/app/core/config.py`, after `session_ttl_days: int = 7`:

```python
    # Optional folder searched before the shipped templates/email; per-file override.
    email_template_dir: str = ""
```

Add to `backend/tests/test_config.py` (append; keep the file's existing style):

```python
def test_email_template_dir_defaults_empty(monkeypatch):
    # `Settings` is already imported at the top of this file.
    monkeypatch.setenv("PORTAL_EMAIL_TEMPLATE_DIR", "/srv/portal-templates/email")
    assert Settings(_env_file=None).email_template_dir == "/srv/portal-templates/email"
    monkeypatch.delenv("PORTAL_EMAIL_TEMPLATE_DIR")
    assert Settings(_env_file=None).email_template_dir == ""
```

- [ ] **Step 3: Write the failing `TemplateSet` tests**

```python
# backend/tests/test_template_set.py
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
    assert m == {"subject": "You're invited to join ${server_name}", "button_label": "Create your account"}


def test_meta_requires_both_keys(baked):
    (baked / "invite.toml").write_text('subject = "x"\n')
    with pytest.raises(ValueError, match="invite.toml"):
        TemplateSet((baked,)).meta("invite")


def test_split_partial():
    wrapper, rows = _split_partial("W\n${rows}\n<!-- row -->\nA\n<!-- row:note -->\nB\n")
    assert wrapper == "W\n${rows}\n"
    assert rows == {"": "A\n", "note": "B\n"}


def test_check_passes_on_shipped_templates():
    TemplateSet.default().check()


def test_check_reports_missing_file(baked):
    (baked / "partials" / "steps.txt").unlink()
    with pytest.raises(FileNotFoundError, match="partials/steps.txt"):
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


def test_block_and_email_registries():
    assert EMAILS == ("invite", "password_reset", "email_change")
    assert BLOCKS == {"realm": (), "steps": (), "modules": ("note", "url"), "links": ("note",)}
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_template_set.py --no-cov -q`
Expected: FAIL — `ImportError: cannot import name 'BLOCKS' from 'app.services.email_templates'`

- [ ] **Step 5: Add `TemplateSet` to `email_templates.py`**

Add these imports and definitions at the top of `backend/app/services/email_templates.py`, after the existing imports and `EmailContent`, leaving the existing `_LAYOUT`, `_paragraph`, `_render`, and builders in place for now (Task 3 replaces them):

```python
import itertools
import logging
import re
import tomllib
from pathlib import Path

from app.core.config import Settings

logger = logging.getLogger("portal.email")

EMAILS = ("invite", "password_reset", "email_change")
# block name -> optional row fields, in the order they appear in variant names
BLOCKS: dict[str, tuple[str, ...]] = {
    "realm": (),
    "steps": (),
    "modules": ("note", "url"),
    "links": ("note",),
}
_REQUIRED_FILES = (
    "base.html",
    "partials/button.html",
    *(f"{e}.{ext}" for e in EMAILS for ext in ("html", "txt")),
)
_ROW_MARKER = re.compile(r"^<!-- row(?::([a-z:]+))? -->\n", re.MULTILINE)
_REPO_TEMPLATES = Path(__file__).resolve().parents[3] / "templates" / "email"


def baked_dir() -> Path:
    """The templates shipped with the code: /app/templates/email in the image
    (WORKDIR /app), <repo>/templates/email when running from a checkout."""
    cwd_copy = Path.cwd() / "templates" / "email"
    return cwd_copy if cwd_copy.is_dir() else _REPO_TEMPLATES


def _required_variants(optional: tuple[str, ...]) -> list[str]:
    return [
        ":".join(c) for r in range(len(optional) + 1) for c in itertools.combinations(optional, r)
    ]


def _split_partial(text: str) -> tuple[str, dict[str, str]]:
    parts = _ROW_MARKER.split(text)
    wrapper, rest = parts[0], parts[1:]
    variants = {(rest[i] or ""): rest[i + 1] for i in range(0, len(rest), 2)}
    return wrapper, variants


@dataclass(frozen=True)
class TemplateSet:
    """Search path for template files: override dir(s) first, baked dir last."""

    dirs: tuple[Path, ...]

    @classmethod
    def default(cls) -> "TemplateSet":
        return cls((baked_dir(),))

    @classmethod
    def from_settings(cls, settings: Settings) -> "TemplateSet":
        override = (Path(settings.email_template_dir),) if settings.email_template_dir else ()
        return cls((*override, baked_dir()))

    def find(self, name: str) -> Path | None:
        for d in self.dirs:
            candidate = d / name
            if candidate.is_file():
                return candidate
        return None

    def read(self, name: str) -> str:
        path = self.find(name)
        if path is None:
            searched = ", ".join(str(d) for d in self.dirs)
            raise FileNotFoundError(f"email template {name} not found in: {searched}")
        return path.read_text(encoding="utf-8")

    def meta(self, name: str) -> dict[str, str]:
        raw = self.read(f"{name}.toml")
        try:
            data = tomllib.loads(raw)
            return {"subject": data["subject"], "button_label": data["button_label"]}
        except (tomllib.TOMLDecodeError, KeyError) as exc:
            raise ValueError(f"{name}.toml must define subject and button_label: {exc}") from exc

    def check(self) -> None:
        """Fail at boot on anything a send would trip over."""
        for name in _REQUIRED_FILES:
            self.read(name)
        for email in EMAILS:
            self.meta(email)
        for block, optional in BLOCKS.items():
            for ext in ("html", "txt"):
                file = f"partials/{block}.{ext}"
                _, variants = _split_partial(self.read(file))
                missing = [v for v in _required_variants(optional) if v not in variants]
                if missing:
                    raise ValueError(f"{file} is missing row variants: {missing}")
```

`from dataclasses import dataclass` is already imported for `EmailContent`; reuse it.

- [ ] **Step 6: Run the new tests and the whole suite**

Run: `cd backend && uv run pytest tests/test_template_set.py tests/test_config.py --no-cov -q`
Expected: PASS

Run: `cd backend && uv run pytest -q`
Expected: PASS at `TOTAL 100%`. The old builders are still exercised by the original tests and `TemplateSet` by the new ones, so nothing should be uncovered. If a line in `email_templates.py` is reported missed, add a test for it here rather than deferring to Task 3.

- [ ] **Step 7: Lint, format, commit**

```bash
cd backend && uv run ruff check . && uv run ruff format .
cd .. && git add templates backend/app/services/email_templates.py backend/app/core/config.py backend/tests/test_template_set.py backend/tests/test_config.py
git commit -m "feat(email): ship templates/email and resolve files through a search path

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: File-based rendering

Replace the Python-string builders with rendering from `TemplateSet`. The five existing tests in `test_email_templates.py` stay byte-for-byte as the regression net.

**Files:**
- Modify: `backend/app/services/email_templates.py` (remove `_LAYOUT`, `_paragraph`, old `_render`; rewrite builders)
- Test: `backend/tests/test_email_templates.py` (append tests)

**Interfaces:**
- Consumes: Task 1 `load_content`, `load_theme`, `EmailContentConfig`; Task 2 `TemplateSet`, `_split_partial`, `BLOCKS`.
- Produces:
  ```python
  def invite(issuer: str, link: str, expires_days: int, *, templates: TemplateSet | None = None) -> EmailContent
  def password_reset(issuer: str, username: str, link: str, expires_hours: int, *, templates: TemplateSet | None = None) -> EmailContent
  def email_change(issuer: str, link: str, expires_hours: int, *, templates: TemplateSet | None = None) -> EmailContent
  ```

- [ ] **Step 1: Add the failing tests**

Ruff's `E402` forbids imports after code, so put the imports in the file's top import block and append everything else at the end.

```python
# backend/tests/test_email_templates.py — add to the import block at the top:
import re
from pathlib import Path

import pytest

from app.services import email_templates
from app.services.email_templates import TemplateSet

# — then append below the existing tests:
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
    idx = [c.html.index(s) for s in ("How to connect", "Getting started", "What this realm runs", "Links", "expires in 7 days")]
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
        toml_value = re.search(rf'^{key}\s*=\s*"(#[0-9a-fA-F]{{6}})"', theme, re.M).group(1)
        assert css_value.lower() == toml_value.lower(), key
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_email_templates.py --no-cov -q`
Expected: the new tests FAIL with `TypeError: invite() got an unexpected keyword argument 'templates'`; the five original tests still PASS.

- [ ] **Step 3: Replace the builders**

In `backend/app/services/email_templates.py`, delete `_LAYOUT`, `_paragraph`, and the old `_render` and three builders. Replace the module docstring and add the rendering code below (keeping the Task 2 definitions):

```python
"""Portal emails, rendered from templates/email (see its README.md).

All wording, markup, and theming live in the template files; this module only
resolves files, escapes values, expands row variants, and assembles the parts.
Content and theme files are re-read on every send so host edits apply at once.
"""
```

```python
from html import escape
from string import Template

from app.services.email_content import EmailContentConfig, load_content, load_theme


def _block(
    ts: TemplateSet, name: str, ext: str, rows: list[dict[str, str]], base: dict[str, str]
) -> str:
    if not rows:
        return ""
    wrapper, variants = _split_partial(ts.read(f"partials/{name}.{ext}"))
    html = ext == "html"
    rendered = []
    for row in rows:
        variant = ":".join(f for f in BLOCKS[name] if row[f])
        values = {k: escape(v, quote=True) if html else v for k, v in row.items()}
        rendered.append(Template(variants[variant]).safe_substitute(base, **values))
    return Template(wrapper).safe_substitute(base, rows="".join(rendered))


def _rows(config: EmailContentConfig) -> list[tuple[str, list[dict[str, str]]]]:
    return [
        ("realm", [{"label": r.label, "value": r.value} for r in config.realm]),
        ("steps", [{"n": str(i), "text": s.text} for i, s in enumerate(config.steps, 1)]),
        ("modules", [{"name": m.name, "note": m.note, "url": m.url} for m in config.modules]),
        ("links", [{"label": lk.label, "url": lk.url, "note": lk.note} for lk in config.links]),
    ]


def _render(
    ts: TemplateSet, name: str, values: dict[str, str], config: EmailContentConfig | None
) -> EmailContent:
    meta = ts.meta(name)
    theme = load_theme(ts.find("theme.toml"))
    html_vars = {k: escape(v, quote=True) for k, v in {**theme, **values}.items()}
    text_vars = dict(values)

    html_vars["button"] = Template(ts.read("partials/button.html")).safe_substitute(
        html_vars, button_label=escape(meta["button_label"], quote=True)
    )
    blocks = _rows(config) if config is not None else []
    html_vars["blocks"] = "".join(_block(ts, n, "html", rows, html_vars) for n, rows in blocks)
    text_vars["blocks"] = "".join(_block(ts, n, "txt", rows, {}) for n, rows in blocks)

    content = Template(ts.read(f"{name}.html")).safe_substitute(html_vars)
    return EmailContent(
        subject=Template(meta["subject"]).safe_substitute(values),
        text=Template(ts.read(f"{name}.txt")).safe_substitute(text_vars),
        html=Template(ts.read("base.html")).safe_substitute(html_vars, content=content),
    )


def invite(
    issuer: str, link: str, expires_days: int, *, templates: TemplateSet | None = None
) -> EmailContent:
    ts = templates or TemplateSet.default()
    config = load_content(ts.find("content.toml"))
    values = {"server_name": issuer, "link": link, "expires_days": str(expires_days)}
    return _render(ts, "invite", values, config)


def password_reset(
    issuer: str,
    username: str,
    link: str,
    expires_hours: int,
    *,
    templates: TemplateSet | None = None,
) -> EmailContent:
    ts = templates or TemplateSet.default()
    values = {
        "server_name": issuer,
        "username": username,
        "link": link,
        "expires_hours": str(expires_hours),
    }
    return _render(ts, "password_reset", values, None)


def email_change(
    issuer: str, link: str, expires_hours: int, *, templates: TemplateSet | None = None
) -> EmailContent:
    ts = templates or TemplateSet.default()
    values = {"server_name": issuer, "link": link, "expires_hours": str(expires_hours)}
    return _render(ts, "email_change", values, None)
```

`from html import escape` and `from string import Template` are already imported at the top of the file; keep them. The comprehension variable in `_rows` is `lk`, not `l`, because ruff flags `l` as ambiguous (`E741`).

- [ ] **Step 4: Run the whole suite with coverage**

Run: `cd backend && uv run pytest -q`
Expected: PASS with `TOTAL 100%`. If `email_templates.py` shows a missed branch, the likely culprits are: `config is not None` (both arms covered by invite vs. reset tests), `templates or TemplateSet.default()` (covered by the original tests passing no `templates`), and `if not rows` (covered by `test_invite_omits_unconfigured_blocks`).

- [ ] **Step 5: Lint, format, commit**

```bash
cd backend && uv run ruff check . && uv run ruff format .
git add app/services/email_templates.py tests/test_email_templates.py
git commit -m "feat(email): render all emails from templates/email

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Wire `TemplateSet` into `Mailer` and app startup

**Files:**
- Modify: `backend/app/services/mailer.py`
- Modify: `backend/app/main.py:56-61`
- Test: `backend/tests/test_mailer.py`, `backend/tests/test_app.py`

**Interfaces:**
- Consumes: Task 2 `TemplateSet`; Task 3 builders' `templates=` kwarg.
- Produces: `Mailer(settings: Settings, templates: TemplateSet | None = None)`; `app.state.templates: TemplateSet`.

- [ ] **Step 1: Append the failing tests**

```python
# backend/tests/test_mailer.py — add to the top import block:
from app.services.email_templates import TemplateSet

# — then append below the existing tests:
async def test_mailer_uses_given_templates(tmp_path):
    override = tmp_path / "o"
    override.mkdir()
    (override / "invite.toml").write_text('subject = "Custom ${server_name}"\nbutton_label = "B"\n')
    settings = Settings(_env_file=None, server_name="RealmX", smtp_from="n@t.co")
    m = Mailer(settings, TemplateSet((override, TemplateSet.default().dirs[0])))
    with patch("app.services.mailer.aiosmtplib.send", new_callable=AsyncMock) as send:
        await m.send_invite("a@b.c", "http://l", 7)
    assert send.call_args.args[0]["Subject"] == "Custom RealmX"


def test_mailer_defaults_to_baked_templates():
    m = Mailer(Settings(_env_file=None))
    assert m._templates == TemplateSet.default()
```

```python
# backend/tests/test_app.py — add to the top import block (keep it sorted; ruff format
# does not sort imports, so place `import pytest` with the other bare imports and the
# app import with the other `from app...` lines):
import pytest

from app.services.email_templates import TemplateSet

# — then append below the existing tests:
def test_app_exposes_checked_templates(app):
    assert app.state.templates == TemplateSet.default()
    assert app.state.mailer._templates is app.state.templates


def test_create_app_refuses_to_start_without_templates(settings, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.main.TemplateSet.from_settings", classmethod(lambda cls, s: TemplateSet((tmp_path,)))
    )
    with pytest.raises(FileNotFoundError, match="base.html"):
        create_app(settings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_mailer.py tests/test_app.py --no-cov -q`
Expected: FAIL — `TypeError: Mailer.__init__() takes 2 positional arguments but 3 were given` and `AttributeError: ... has no attribute 'templates'`

- [ ] **Step 3: Implement**

`backend/app/services/mailer.py` — change the import line and constructor, and pass `templates=` in the three `send_*` methods:

```python
from app.services.email_templates import EmailContent, TemplateSet


class Mailer:
    def __init__(self, settings: Settings, templates: TemplateSet | None = None) -> None:
        self._settings = settings
        self._templates = templates or TemplateSet.default()

    async def send_invite(self, to_email: str, link: str, expires_days: int) -> None:
        content = email_templates.invite(
            self._settings.server_name, link, expires_days, templates=self._templates
        )
        await self._send(self._build(to_email, content))

    async def send_password_reset(
        self, to_email: str, username: str, link: str, expires_hours: int
    ) -> None:
        content = email_templates.password_reset(
            self._settings.server_name, username, link, expires_hours, templates=self._templates
        )
        await self._send(self._build(to_email, content))

    async def send_email_change(self, to_email: str, link: str, expires_hours: int) -> None:
        content = email_templates.email_change(
            self._settings.server_name, link, expires_hours, templates=self._templates
        )
        await self._send(self._build(to_email, content))
```

`backend/app/main.py` — add the import and replace the `app.state.mailer = Mailer(settings)` line:

```python
from app.services.email_templates import TemplateSet
```

```python
    # Fail at boot, not at the first invite, if the image or override dir is broken.
    app.state.templates = TemplateSet.from_settings(settings)
    app.state.templates.check()
    app.state.mailer = Mailer(settings, app.state.templates)
```

- [ ] **Step 4: Run the whole suite with coverage**

Run: `cd backend && uv run pytest -q`
Expected: PASS, `TOTAL 100%`

- [ ] **Step 5: Lint, format, commit**

```bash
cd backend && uv run ruff check . && uv run ruff format .
git add app/services/mailer.py app/main.py tests/test_mailer.py tests/test_app.py
git commit -m "feat(email): check templates at boot and thread them through Mailer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Docker build context, override mount, CI

**Files:**
- Modify: `backend/Dockerfile`
- Modify: `docker-compose.yml:2-5,24-26`
- Create: `.dockerignore`
- Modify: `.github/workflows/ci.yml:74-78`

**Interfaces:**
- Consumes: `templates/` folder (Task 2); `PORTAL_EMAIL_TEMPLATE_DIR` (Task 2).
- Produces: image with `/app/templates/email`; container env `PORTAL_EMAIL_TEMPLATE_DIR=/app/templates-override/email`.

- [ ] **Step 1: Root `.dockerignore`**

Create `.dockerignore` at the repo root. It applies only to root-context builds (the backend); the frontend keeps its own context and `frontend/.dockerignore`.

```
.git
.env
**/__pycache__
**/.pytest_cache
**/.ruff_cache
**/.venv
**/*.db
**/.coverage
backend/tests
frontend
tools
docs
.github
.playwright-mcp
.superpowers
```

- [ ] **Step 2: Dockerfile paths**

Replace `backend/Dockerfile` with:

```dockerfile
# Build context is the repo root (see docker-compose.yml) so templates/ can be copied in.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/app ./app
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY templates ./templates
EXPOSE 8000
CMD ["sh", "-c", "uv run --no-sync alembic upgrade head && uv run --no-sync uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8000"]
```

- [ ] **Step 3: Compose**

In `docker-compose.yml`, change the backend service's `build` and add the env var and mount:

```yaml
  backend:
    image: "${PORTAL_IMAGE_BACKEND:-uprightbass360/azerothcore-account-portal-backend:latest}"
    build:
      context: .
      dockerfile: backend/Dockerfile
    restart: unless-stopped
    environment:
      # ... existing entries unchanged ...
      PORTAL_ADMIN_USERNAMES: "${PORTAL_ADMIN_USERNAMES:-}"
      # Host ./templates overrides the image's copy file by file; an empty or
      # missing host folder falls through to the shipped templates.
      PORTAL_EMAIL_TEMPLATE_DIR: /app/templates-override/email
    volumes:
      - appdata:/data
      - ./templates:/app/templates-override:ro
```

- [ ] **Step 4: CI build context**

In `.github/workflows/ci.yml`, the backend build step's `with:` block becomes:

```yaml
        with:
          context: .
          file: backend/Dockerfile
          push: ${{ github.event_name == 'push' }}
```

(keep `tags`, `cache-from`, `cache-to` as they are).

- [ ] **Step 5: Verify the image builds and boots with templates**

Run from the repo root:

```bash
docker build -f backend/Dockerfile -t portal-backend-test . \
  && docker run --rm portal-backend-test ls /app/templates/email \
  && docker run --rm -e PORTAL_EMAIL_TEMPLATE_DIR=/app/templates-override/email \
       portal-backend-test uv run --no-sync python -c \
       "from app.core.config import Settings; from app.services.email_templates import TemplateSet; t=TemplateSet.from_settings(Settings()); t.check(); print('templates ok:', t.dirs)"
```

Expected: the `ls` lists `base.html content.toml ... theme.toml`; the last command prints `templates ok: (PosixPath('/app/templates-override/email'), PosixPath('/app/templates/email'))` — the override dir is absent in the container and correctly falls through.

Also confirm the context is small: `docker build` output's "transferring context" line should be well under 5 MB. If Docker is unavailable locally, say so in the commit and rely on the CI docker job; do not skip the check silently.

- [ ] **Step 6: Commit**

```bash
git add .dockerignore backend/Dockerfile docker-compose.yml .github/workflows/ci.yml
git commit -m "build: root build context, bake templates, mount host overrides separately

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Documentation

**Files:**
- Modify: `README.md` (new section after "First admin", ~line 117)
- Modify: `.env.template` (Portal section, after `PORTAL_SESSION_TTL_DAYS=7`)
- Modify: `docs/superpowers/specs/2026-09-21-email-templates-design.md` (status line)

- [ ] **Step 1: README section**

Insert after the "First admin" section:

````markdown
## Customising emails

Invite, password-reset, and email-change emails are built from the files in
`templates/email/`. The most useful file is `templates/email/content.toml`,
where you add your realmlist and client version, the modules your realm runs,
and links such as Discord or a client download. Each of those blocks appears
in invite emails only when it has entries.

Edit the files on the host; the backend re-reads them on every send, so
changes apply to the next email with no restart. Wording lives in
`<email>.html` / `.txt` / `.toml`, colors and fonts in `theme.toml`, and the
card frame in `base.html`. `templates/email/README.md` lists every
placeholder.

The image ships its own copy of the folder; `docker-compose.yml` mounts
`./templates` as a per-file override, so a fresh checkout works unchanged and
you only need to keep the files you actually edit. A malformed `content.toml`
or `theme.toml` falls back to defaults and is logged; a missing or malformed
template file stops the backend at startup with the path in the error.

The `[[module]]` list is hand-maintained — the portal cannot ask the
worldserver which modules are loaded — so update it when you add or remove a
module.
````

- [ ] **Step 2: `.env.template` note**

After `PORTAL_SESSION_TTL_DAYS=7`:

```
# Email wording, theme, realm details, module list and links live in
# ./templates/email (see README "Customising emails"); nothing to set here.
```

- [ ] **Step 3: Mark the spec implemented**

Change the spec's status line to `**Status:** Implemented (branch feat/email-templates-folder)`.

- [ ] **Step 4: Final verification and commit**

```bash
cd backend && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
cd .. && git add README.md .env.template docs/superpowers/specs/2026-09-21-email-templates-design.md
git commit -m "docs: describe templates/email and the override mount

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

Expected: tests PASS at 100%, ruff clean, commit succeeds. Then open the PR per `superpowers:finishing-a-development-branch`.
