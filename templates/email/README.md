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
