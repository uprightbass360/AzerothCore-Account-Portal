# Email Templates — File-Based, Themed, Content-Rich

**Date:** 2026-09-21
**Status:** Approved design, pre-implementation
**Supersedes:** the inline-Python email builders in
`backend/app/services/email_templates.py`

## Purpose

Move every portal email out of Python string literals and into an editable
`templates/` folder at the repo root, so a realm admin can change wording,
theming, and content without touching code or rebuilding an image. Along the
way, give the invite email the information a new player actually needs —
realm connection details, getting-started steps, the modules the realm runs,
and an optional list of community links.

### Goals

- All subjects, plain-text bodies, and HTML live in editable files.
- One theme file mirrors `frontend/src/routes/layout.css`, with a test that
  catches drift between the two.
- Invite emails carry realm details, setup steps, module list, and links —
  each optional, each omitted cleanly when unconfigured.
- Admins edit content on the host and see the change on the next send, with no
  container restart.
- No new Python dependency.

### Non-goals

- Admin-UI editing of email content (files only; a DB-backed editor is a much
  larger change and is not in scope).
- Live realm status or player counts in emails (adds a send-time SOAP failure
  path for little gain).
- Pulling the module list from the worldserver. AzerothCore exposes no SOAP
  command that lists module names — `server info` returns a revision string
  and, on some builds, a count without names. The list is admin-declared.
- Per-locale / multi-language templates.

## Constraints

Carried over from the current implementation and still binding:

- **All CSS inline.** Mail clients strip `<style>` blocks.
- **No webfonts, no external assets.** Georgia stands in for the portal's
  Cinzel; no remote images.
- **Table-based layout.** Required for Outlook.
- **Everything interpolated is HTML-escaped.** Admin-authored TOML content is
  as untrusted as user input for escaping purposes.
- **Python 3.12+** (`requires-python = ">=3.12"`, image is `python3.12`), so
  `tomllib` is stdlib. `string.Template` stays the substitution engine.

## Architecture

### Folder layout

```
templates/email/
├── README.md                 # what admins may edit, placeholder reference,
│                             # and the caveat that [[module]] is hand-maintained
├── content.toml              # realm details, steps, modules, links
├── theme.toml                # colors + fonts, mirrored from layout.css
├── base.html                 # shared chrome: body, table, card, footer
├── partials/
│   ├── button.html
│   ├── realm.html            # realmlist + client version
│   ├── steps.html            # numbered getting-started block
│   ├── modules.html          # module name / note / optional link
│   └── links.html            # community + dependency links
├── invite.html
├── invite.txt
├── invite.subject.txt
├── password_reset.html
├── password_reset.txt
├── password_reset.subject.txt
├── email_change.html
├── email_change.txt
└── email_change.subject.txt
```

Each partial file contains one wrapper plus, where it repeats, a single row
fragment the loader repeats per entry. `string.Template` has no loops, so
repetition happens in Python and the file supplies the markup for one item.

### Modules

**`backend/app/services/email_content.py`** (new) owns *data*:

- Reads `content.toml` and `theme.toml` with `tomllib`.
- Normalizes into frozen dataclasses: `RealmInfo`, `Step`, `Module`, `Link`,
  `Theme`, bundled as `EmailContentConfig`.
- Caches by directory mtime so a bind-mounted edit applies on the next send
  without a restart, and without re-parsing on every send.
- Degrades rather than fails: unreadable or malformed TOML logs a warning and
  falls back to built-in defaults; an individual entry missing its required
  field is skipped with a warning.

**`backend/app/services/email_templates.py`** (rewritten) owns *rendering*:

- Loads template files, escapes all interpolated values, renders optional
  partials, substitutes theme tokens, and returns the existing
  `EmailContent(subject, text, html)`.
- Public functions `invite()`, `password_reset()`, `email_change()` keep their
  current positional signatures. New data arrives from
  `email_content.load()`, not from new required arguments, so `Mailer` and
  `backend/app/api/admin.py` need no behavior change.

The split keeps parsing/validation testable without rendering, and rendering
testable with hand-built config objects.

### Data flow

```
content.toml ─┐
theme.toml  ──┤→ email_content.load(dir) → EmailContentConfig (mtime-cached)
              │                                      │
*.html/.txt ──┴→ email_templates.invite(...) ────────┘
                          │
                          └→ EmailContent(subject, text, html) → Mailer → SMTP
```

### Optional blocks

Every content block collapses to an empty string when its data is absent — no
orphan headings, no empty bullets. Which blocks each email includes:

| Block   | invite | password_reset | email_change |
|---------|--------|----------------|--------------|
| realm   | yes    | no             | no           |
| steps   | yes    | no             | no           |
| modules | yes    | no             | no           |
| links   | yes    | no             | no           |

Password-reset and email-change go to people who already have accounts and are
mid-task; a realm pitch does not belong there. They keep the current layout,
now file-based.

Order within the invite: invitation → button → realm details → getting-started
steps → modules → links → expiry footer. Reader's path is *you're invited →
create account → how to connect → what's special here → where to find us*.

### content.toml

```toml
[realm]
realmlist = "set realmlist logon.example.com"
client_version = "3.3.5a (12340)"

[[steps]]
text = "Click the button above and pick a username and password."

[[steps]]
text = "Open your WoW folder → Data/enUS/realmlist.wtf and paste the realmlist line."

[[steps]]
text = "Launch the game and log in with your new account."

# Modules this realm runs. Hand-maintained — see README.md.
# [[module]]
# name = "Solo Craft"
# note = "Scales dungeons and raids for solo or small-group play"
# url = "https://github.com/azerothcore/mod-solocraft"

# [[link]]
# label = "Discord"
# url = "https://discord.gg/xxxx"
# note = "Get help and find groups"
```

Field rules:

- `[realm]` — both keys optional; the block renders if either is set.
- `[[steps]]` — `text` required.
- `[[module]]` — `name` required; `note` and `url` optional. With a `url` the
  name renders as a link, otherwise as plain text.
- `[[link]]` — `label` and `url` required; `note` optional.

Ships with `[realm]` and `[[steps]]` populated with working examples, and
`[[module]]` / `[[link]]` commented out, so a fresh install sends something
sensible rather than placeholder content.

### theme.toml

```toml
[color]
night = "#07090f"
panel = "#0b0e17"
gold_deep = "#8a6a14"
gold_corner = "#e8c552"
questgold = "#ffd100"
parchment = "#e8d9b0"
muted = "#8b8574"
faint = "#55503f"
button_text = "#1a1405"

[font]
display = "Georgia,'Times New Roman',serif"
body = "Helvetica,Arial,sans-serif"
```

Values are substituted into the HTML as `${color_questgold}`,
`${font_display}`, etc., so `theme.toml` is the single place email colors
live. A test asserts the shared values still match
`frontend/src/routes/layout.css`, catching drift when the site theme changes.

### Configuration

One new setting in `backend/app/core/config.py`:

```python
email_template_dir: str = "templates/email"
```

(`PORTAL_EMAIL_TEMPLATE_DIR`.) Resolved relative to the app root when not
absolute, so tests and local dev find it without Docker. Realm details and
links live in `content.toml`, not in env vars — a deliberate choice to keep
email content in one editable place rather than split across two.

### Deployment

The build context moves to the repo root so the Dockerfile can COPY a
directory outside `backend/`:

```yaml
backend:
  build:
    context: .
    dockerfile: backend/Dockerfile
  volumes:
    - appdata:/data
    - ./templates:/app/templates:ro
```

`backend/Dockerfile` COPY paths gain a `backend/` prefix, and a
`COPY templates ./templates` line bakes a working default into the image. The
read-only bind mount then lets admins override it on the host and edit live;
the mtime cache means the next send picks the change up.

`.env.template` and `README.md` document the folder, the `[[module]]`
maintenance caveat, and `PORTAL_EMAIL_TEMPLATE_DIR`.

## Error handling

| Condition | Behavior |
|-----------|----------|
| Template dir missing | Log error once; render from built-in fallback strings. Email still sends. |
| A template file missing | Log error; fall back to the built-in string for that email. |
| `content.toml` malformed | Log warning; use built-in defaults for all content blocks. |
| `theme.toml` malformed | Log warning; use built-in default theme. |
| Entry missing a required field | Skip that entry with a warning; render the rest. |
| Unknown `${placeholder}` in a file | `Template.safe_substitute` leaves it literal; a test asserts none remain in shipped templates. |

The governing rule: **a content error must never block an invite from being
sent.** A player locked out by a typo in a TOML file is a worse failure than
an email missing its links section.

## Testing

Extending `backend/tests/test_email_templates.py`, plus a new
`backend/tests/test_email_content.py`:

**Content loading**
- Valid `content.toml` parses into the expected dataclasses.
- Malformed TOML falls back to defaults and logs, without raising.
- Entry missing a required field is skipped; siblings still render.
- mtime cache returns a fresh parse after a file is touched.

**Rendering**
- All three emails render with no template dir present (fallback path).
- Each optional block appears when configured and vanishes when not — with no
  empty heading left behind.
- Module with `url` renders a link; module without renders plain text.
- Every existing assertion in `test_email_templates.py` still passes; the
  current tests are the regression net for the rewrite.

**Safety**
- Labels, notes, URLs, realmlist, and server name are HTML-escaped; the
  plain-text part is not.
- No literal `${` remains in any rendered output.

**Theme**
- The six colors shared with the site — `night`, `panel`, `gold_deep`,
  `gold_corner`, `questgold`, `parchment` — match the corresponding custom
  properties in `frontend/src/routes/layout.css`. The remaining three
  (`muted`, `faint`, `button_text`) are email-only, have no counterpart in
  `layout.css`, and are excluded from the drift check.

## Risks

- **Build context change** is the one structural ripple; it touches the
  Dockerfile and both compose files. Verified by building the image and
  confirming the CI workflow still passes.
- **Hand-maintained module list** will drift from the running server. Mitigated
  by documenting it plainly in `templates/email/README.md`; accepted because
  the alternative (SOAP scraping) is build-dependent and unreliable.
- **Rewriting a working module** risks regressing the three live emails. The
  existing test file is kept intact as the regression net.
