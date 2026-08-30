from app.services import email_templates


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
