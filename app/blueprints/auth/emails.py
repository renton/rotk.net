"""Email-sending helper for the auth blueprint.

Wraps Flask-Mail with two niceties:

1. If MAIL_SUPPRESS_SEND is on (the default when no MAIL_SERVER is configured),
   the message is logged to app.logger instead of dropped silently. This makes
   local development possible without any SMTP setup.
2. Renders both `<template>.txt` and `<template>.html` so every email is sent
   as a multipart message.
"""

from threading import Thread

from flask import current_app, render_template
from flask_mail import Message

from app import mail


def _send_async(app, msg):
    with app.app_context():
        mail.send(msg)


def send_email(to, subject, template, **kwargs):
    app = current_app._get_current_object()
    subject_prefix = f"[{app.config['APP_NAME']}] "

    msg = Message(
        subject_prefix + subject,
        sender=app.config['MAIL_DEFAULT_SENDER'],
        recipients=[to],
    )
    msg.body = render_template(template + '.txt', **kwargs)
    msg.html = render_template(template + '.html', **kwargs)

    if app.config.get('MAIL_SUPPRESS_SEND'):
        app.logger.info(
            "Email send suppressed (no MAIL_SERVER configured).\n"
            "  to: %s\n  subject: %s\n  body:\n%s",
            to, msg.subject, msg.body,
        )
        return None

    thread = Thread(target=_send_async, args=(app, msg))
    thread.start()
    return thread
