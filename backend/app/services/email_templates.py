"""Portal emails, rendered from templates/email (see its README.md).

All wording, markup, and theming live in the template files; this module only
resolves files, escapes values, expands row variants, and assembles the parts.
Content and theme files are re-read on every send so host edits apply at once.
"""

import itertools
import re
import tomllib
from dataclasses import dataclass
from html import escape
from pathlib import Path
from string import Template

from app.core.config import Settings
from app.services.email_content import EmailContentConfig, load_content, load_theme

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


@dataclass(frozen=True)
class EmailContent:
    subject: str
    text: str
    html: str


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
