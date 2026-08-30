"""Subject lines, wording, and the shared HTML design for every portal email.

To change an email's TEXT, edit its builder function below.
To change the DESIGN, edit _LAYOUT / _paragraph — every email renders inside them.

Email-client constraints: all styles must stay inline (clients strip <style>
blocks), no webfonts (Georgia stands in for the portal's Cinzel), no external
assets. Colors mirror frontend/src/routes/layout.css: night #07090f, panel
#0b0e17, gold border #8a6a14 / #e8c552, quest-gold headings #ffd100,
parchment body text #e8d9b0.
"""

from dataclasses import dataclass
from html import escape
from string import Template


@dataclass(frozen=True)
class EmailContent:
    subject: str
    text: str
    html: str


_LAYOUT = Template(
    '<body style="margin:0;padding:0;background-color:#07090f;">'
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"'
    ' style="background-color:#07090f;">'
    '<tr><td align="center" style="padding:32px 16px;">'
    '<table role="presentation" width="480" cellpadding="0" cellspacing="0"'
    ' style="max-width:480px;width:100%;background-color:#0b0e17;'
    'border:1px solid #8a6a14;border-top:3px solid #e8c552;">'
    '<tr><td style="padding:32px 36px;">'
    "<h1 style=\"margin:0 0 16px;font-family:Georgia,'Times New Roman',serif;"
    'font-size:22px;font-weight:700;color:#ffd100;">$title</h1>'
    "$body"
    '<table role="presentation" cellpadding="0" cellspacing="0" style="margin:24px 0;">'
    '<tr><td style="background-color:#e8c552;">'
    '<a href="$link" style="display:inline-block;padding:12px 28px;'
    "font-family:Georgia,serif;font-size:15px;font-weight:700;letter-spacing:1px;"
    'color:#1a1405;text-decoration:none;">$button_label</a>'
    "</td></tr></table>"
    '<p style="margin:0;font-family:Helvetica,Arial,sans-serif;font-size:12px;'
    'color:#8b8574;">$footer</p>'
    "</td></tr></table>"
    '<p style="margin:16px 0 0;font-family:Helvetica,Arial,sans-serif;font-size:11px;'
    'color:#55503f;">$issuer</p>'
    "</td></tr></table></body>"
)


def _paragraph(inner_html: str) -> str:
    return (
        '<p style="margin:0 0 12px;font-family:Helvetica,Arial,sans-serif;'
        f'font-size:14px;line-height:1.6;color:#e8d9b0;">{inner_html}</p>'
    )


def _render(
    issuer: str, title: str, paragraphs: list[str], link: str, button_label: str, footer: str
) -> str:
    return _LAYOUT.substitute(
        title=title,
        body="".join(_paragraph(p) for p in paragraphs),
        link=escape(link, quote=True),
        button_label=button_label,
        footer=footer,
        issuer=escape(issuer),
    )


def invite(issuer: str, link: str, expires_days: int) -> EmailContent:
    footer = f"This invite expires in {expires_days} days."
    return EmailContent(
        subject=f"You're invited to join {issuer}",
        text=(
            f"You've been invited to create a game account on {issuer}.\n\n"
            f"Register here: {link}\n\n"
            f"{footer}"
        ),
        html=_render(
            issuer,
            title="You're invited",
            paragraphs=[
                f"You've been invited to create a game account on <b>{escape(issuer)}</b>."
            ],
            link=link,
            button_label="Create your account",
            footer=footer,
        ),
    )


def password_reset(issuer: str, username: str, link: str, expires_hours: int) -> EmailContent:
    footer = f"This link expires in {expires_hours} hours."
    return EmailContent(
        subject=f"Set a new password for {username} on {issuer}",
        text=(
            f"An administrator reset the password for your {issuer} account {username}.\n"
            f"Your old password no longer works.\n\n"
            f"Choose a new password here: {link}\n\n"
            f"{footer}"
        ),
        html=_render(
            issuer,
            title="Set a new password",
            paragraphs=[
                (
                    f"An administrator reset the password for your <b>{escape(issuer)}</b> "
                    f"account <b>{escape(username)}</b>. Your old password no longer works."
                )
            ],
            link=link,
            button_label="Choose a new password",
            footer=footer,
        ),
    )


def email_change(issuer: str, link: str, expires_hours: int) -> EmailContent:
    footer = (
        f"This link expires in {expires_hours} hours. "
        "If you didn't request this, ignore this email."
    )
    return EmailContent(
        subject=f"Confirm your new email for {issuer}",
        text=(
            f"A request was made to use this address for a {issuer} game account.\n\n"
            f"Confirm the change here: {link}\n\n"
            f"{footer}"
        ),
        html=_render(
            issuer,
            title="Confirm your new email",
            paragraphs=[
                (
                    f"A request was made to use this address for a <b>{escape(issuer)}</b> "
                    "game account."
                )
            ],
            link=link,
            button_label="Confirm the email change",
            footer=footer,
        ),
    )
