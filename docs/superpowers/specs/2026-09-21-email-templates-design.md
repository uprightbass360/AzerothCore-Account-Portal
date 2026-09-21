# Email Templates — File-Based, Themed, Content-Rich

**Date:** 2026-09-21
**Status:** Implemented (branch feat/email-templates-folder)
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
  container restart. Files are re-read per send; there is no cache to invalidate.
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
├── partials/                 # each block has an .html and a .txt sibling
│   ├── button.html
│   ├── realm.html    realm.txt      # realmlist + client version
│   ├── steps.html    steps.txt      # numbered getting-started block
│   ├── modules.html  modules.txt    # module name / note / optional link
│   └── links.html    links.txt      # community + dependency links
├── invite.html               # card body: heading, paragraphs, ${button}, ${blocks}, footer
├── invite.txt                # plain-text part
├── invite.toml               # subject = "...", button_label = "..."
├── password_reset.html
├── password_reset.txt
├── password_reset.toml
├── email_change.html
├── email_change.txt
└── email_change.toml
```

`base.html` is chrome only (night background, gold-framed card, realm name
under the card) with a `${content}` slot; each `<email>.html` is the card body
and holds every word of that email, including the heading and the expiry
footer. `<email>.toml` holds the two strings that are not markup: the subject
and the button label.

Each partial file holds a wrapper followed by one or more **row templates**,
separated by marker lines. `string.Template` has no loops or conditionals,
so repetition and optional fields are handled by choosing a row template per
entry, in Python, while the file supplies all markup and wording:

```html
<h2 ...>Links</h2>
<table ...>
${rows}</table>
<!-- row -->
<tr><td><a href="${url}">${label}</a></td></tr>
<!-- row:note -->
<tr><td><a href="${url}">${label}</a> — ${note}</td></tr>
```

The variant name lists the optional fields that are present, in the block's
declared order: `modules` (optional `note`, `url`) needs `row`, `row:note`,
`row:url`, `row:note:url`; `links` (optional `note`) needs `row`, `row:note`;
`realm` and `steps` need only `row`. The same marker syntax is used in `.txt`
partials. Every block has a `.txt` sibling so the plain-text part is fully
file-based too; no wording lives in Python. A literal dollar sign in any
template file is written `$$` (documented in the README).

### Modules

**`backend/app/services/email_content.py`** (new) owns *data*:

- Reads `content.toml` and `theme.toml` with `tomllib`.
- Normalizes into frozen dataclasses: `RealmEntry`, `Step`, `Module`, `Link`,
  bundled as `EmailContentConfig`; the theme is a flat `dict[str, str]` of
  `${placeholder}` names (`color_night`, `font_body`, ...) to values.
- Re-reads the files on every send. There is no cache: a directory's mtime
  does not change on in-place edits, so mtime caching would silently miss the
  exact edits the bind mount exists for. The cost is a handful of small file
  reads per invite, which is negligible at invite volume.
- Degrades rather than fails: unreadable or malformed TOML logs a warning and
  falls back to built-in defaults; an individual entry missing its required
  field is skipped with a warning.

**`backend/app/services/email_templates.py`** (rewritten) owns *rendering*:

- Resolves each template file through a **search path** — override dir first,
  baked dir second — so an admin can override a single file (typically just
  `content.toml`) without copying the rest.
- Loads template files, escapes all interpolated values, renders optional
  partials, substitutes theme tokens, and returns the existing
  `EmailContent(subject, text, html)`.
- Public functions `invite()`, `password_reset()`, `email_change()` keep their
  current positional signatures and gain one optional keyword argument,
  `templates: TemplateSet | None`. `Mailer` builds the `TemplateSet` from
  settings once and passes it; tests pass hand-built ones. When omitted, the
  functions resolve the default search path themselves, so existing callers
  and tests keep working unchanged.
- `TemplateSet.check()` verifies every required file resolves, every
  `<email>.toml` defines `subject` and `button_label`, and every partial
  defines all the row variants its block needs. It is called from
  `create_app`, so a broken deployment fails at boot with the offending path
  rather than at the first invite.

The split keeps parsing/validation testable without rendering, and rendering
testable with hand-built config objects.

### Data flow

```
override dir ─┐ (per-file, first match wins)
baked dir   ──┴→ TemplateSet.resolve(name) ─→ file path

content.toml ─┐
theme.toml  ──┤→ email_content.load(templates) → EmailContentConfig (per send)
              │                                         │
*.html/.txt ──┴→ email_templates.invite(..., templates) ┘
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
# Connection details: any label → value pairs. Shipped commented out.
# [realm]
# Realmlist = "set realmlist logon.example.com"
# "Client version" = "3.3.5a (12340)"

[[steps]]
text = "Click the button above and pick a username and password."

[[steps]]
text = "Open your WoW folder, edit Data/enUS/realmlist.wtf, and set it to this realm's address."

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

- `[realm]` — a free-form table of label → value strings, rendered in file
  order. Labels are admin content, so admins can add rows (`Expansion`,
  `Discord`) without a code change. Empty or absent → block omitted.
- `[[steps]]` — `text` required.
- `[[module]]` — `name` required; `note` and `url` optional. With a `url` the
  name renders as a link, otherwise as plain text.
- `[[link]]` — `label` and `url` required; `note` optional.

Ships with `[[steps]]` populated (they are generic and true for any realm)
and `[realm]`, `[[module]]`, `[[link]]` commented out with examples. A fresh
install therefore sends a correct, if plain, invite; it never mails a
placeholder realmlist to a real player.

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
email_template_dir: str = ""   # PORTAL_EMAIL_TEMPLATE_DIR — optional override dir
```

The **baked dir** is always searched and is located relative to the code, not
to the setting: the first existing candidate of `<cwd>/templates/email` (the
Docker layout, `WORKDIR /app`) and `<repo>/templates/email` (found from the
package path, for local dev and tests). The **override dir** is searched first
when the setting is non-empty. This keeps the baked copy reachable no matter
what the host mounts, which is what makes the bind mount safe (see Deployment).

Realm details and links live in `content.toml`, not in env vars — a
deliberate choice to keep email content in one editable place rather than
split across two.

### Deployment

The build context moves to the repo root so the Dockerfile can COPY a
directory outside `backend/`:

```yaml
backend:
  build:
    context: .
    dockerfile: backend/Dockerfile
  environment:
    PORTAL_EMAIL_TEMPLATE_DIR: /app/templates-override/email
  volumes:
    - appdata:/data
    - ./templates:/app/templates-override:ro
```

`backend/Dockerfile` COPY paths gain a `backend/` prefix, and a
`COPY templates ./templates` line bakes a working default into the image at
`/app/templates`.

**The host folder mounts to a separate override path, never over the baked
copy.** A bind mount of a non-existent host path makes Docker create an empty
directory and mount it, so mounting onto `/app/templates` would hide the baked
templates for anyone deploying from the prebuilt image with only
`docker-compose.yml` and `.env` — exactly the deployment `PORTAL_IMAGE_BACKEND`
exists for. With the override path, an empty or missing `./templates` simply
falls through to the baked copy, and a populated one wins file by file.

Moving the build context has two side effects the change must carry:

- **Root `.dockerignore`.** `backend/.dockerignore` stops applying when the
  context is `.`; without a root one the build would upload
  `frontend/node_modules`, `backend/.venv`, `.git`, and `frontend/build` on
  every build. The root file excludes those plus the current `backend/`
  entries, re-expressed as root-relative paths.
- **CI.** `.github/workflows/ci.yml` builds the backend image with
  `context: backend`; it becomes `context: .` with
  `file: backend/Dockerfile`. The frontend job is unchanged.

`.env.template` and `README.md` document the folder, the override cascade,
the `[[module]]` maintenance caveat, `$$` for literal dollar signs, and
`PORTAL_EMAIL_TEMPLATE_DIR`.

## Error handling

Two classes of failure, handled differently:

**Template files** (`*.html`, `*.txt`, `partials/*`) are part of the
deployment. The baked copy is always in the image, so one being unresolvable
means the image or the search path is broken. That is caught at boot:
`TemplateSet.check()` runs in `create_app` and raises with the missing path.
There are no Python fallback strings — they would be a second copy of every
template, and they would rot.

**Content files** (`content.toml`, `theme.toml`) are admin-edited and may be
wrong at any moment. They degrade:

| Condition | Behavior |
|-----------|----------|
| `content.toml` missing or malformed | Log warning; use built-in defaults for all content blocks. |
| `theme.toml` missing or malformed | Log warning; use built-in default theme. |
| Entry missing a required field | Skip that entry with a warning; render the rest. |
| Unknown `${placeholder}` in a file | `Template.safe_substitute` leaves it literal; a test asserts none remain in shipped templates. |

The governing rule: **a content error must never block an invite from being
sent, and a missing template must never reach a send.** A player locked out
by a typo in a TOML file is a worse failure than an email missing its links
section; a template missing from the image is a failure that belongs on the
operator's screen at startup, not in a player's inbox.

## Testing

Extending `backend/tests/test_email_templates.py`, plus a new
`backend/tests/test_email_content.py`:

**Template resolution**
- A file present in the override dir wins; one absent there falls through to
  the baked dir; an empty override dir resolves everything from baked.
- `TemplateSet.check()` raises naming the path when a required file is
  missing from both dirs.
- An in-place edit to `content.toml` is reflected on the next render with no
  restart or cache step.

**Content loading**
- Valid `content.toml` parses into the expected dataclasses.
- Missing or malformed TOML falls back to defaults and logs, without raising.
- Entry missing a required field is skipped; siblings still render.

**Rendering**
- All three emails render from the baked dir with no override configured.
- Each optional block appears when configured and vanishes when not — with no
  empty heading left behind.
- Module with `url` renders a link; module without renders plain text.
- Text and HTML parts of the invite both carry every configured block.
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
  Dockerfile, `docker-compose.yml`, the CI workflow, and adds a root
  `.dockerignore`. Verified by building the image locally and by the CI
  docker job.
- **Hand-maintained module list** will drift from the running server. Mitigated
  by documenting it plainly in `templates/email/README.md`; accepted because
  the alternative (SOAP scraping) is build-dependent and unreliable.
- **Rewriting a working module** risks regressing the three live emails. The
  existing test file is kept intact as the regression net.
