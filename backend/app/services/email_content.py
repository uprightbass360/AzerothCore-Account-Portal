"""Admin-editable email content and theme.

content.toml supplies the optional blocks of the invite email (install and
configure tables, modules, links); theme.toml supplies the colors and
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
class Entry:
    """One label/value row of the [install] or [configure] table. `url` is the
    value again when it is a link, so the partial can render it as one."""

    label: str
    value: str
    url: str = ""


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
    install: tuple[Entry, ...] = ()
    configure: tuple[Entry, ...] = ()
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


_URL_SCHEMES = ("http://", "https://", "mailto:")


def _url(entry: dict, key: str) -> str:
    """Like _str, but only http(s)/mailto URLs pass; anything else is
    treated as absent (empty string), the caller decides what that means."""
    value = _str(entry, key)
    return value if not value or value.startswith(_URL_SCHEMES) else ""


def _entries(raw: dict, key: str, required: tuple[str, ...]) -> list[dict]:
    items = raw.get(key, [])
    if not isinstance(items, list):
        logger.warning(
            "content.toml: [[%s]] must be an array of tables, ignoring",
            key,
        )
        return []
    kept = []
    for entry in items:
        valid = isinstance(entry, dict) and all(
            _url(entry, k) if k == "url" else _str(entry, k) for k in required
        )
        if not valid:
            logger.warning(
                "content.toml: skipping [[%s]] entry missing or with a rejected %s",
                key,
                "/".join(required),
            )
            continue
        kept.append(entry)
    return kept


def _table(raw: dict, key: str) -> tuple[Entry, ...]:
    table = raw.get(key, {})
    if not isinstance(table, dict):
        logger.warning("content.toml: [%s] must be a table, ignoring", key)
        return ()
    return tuple(
        Entry(k, v, v if v.startswith(_URL_SCHEMES) else "")
        for k, v in table.items()
        if isinstance(v, str) and v
    )


def load_content(path: Path | None) -> EmailContentConfig:
    raw = _read_toml(path, "content.toml")

    def module(e: dict) -> Module:
        url = _url(e, "url")
        if _str(e, "url") and not url:
            logger.warning(
                "content.toml: [[module]] %s has an unsupported url scheme, dropping it: %s",
                _str(e, "name"),
                _str(e, "url"),
            )
        return Module(_str(e, "name"), _str(e, "note"), url)

    return EmailContentConfig(
        install=_table(raw, "install"),
        configure=_table(raw, "configure"),
        modules=tuple(module(e) for e in _entries(raw, "module", ("name",))),
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
