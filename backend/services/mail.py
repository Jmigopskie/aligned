"""Email through Resend's HTTP API (https://resend.com/docs/api-reference/emails/send-email)."""
import requests
from flask import current_app


class MailError(Exception):
    pass


def configured():
    return bool(current_app.config.get("RESEND_API_KEY"))


def send_email(to, subject, text, html=None):
    payload = {"from": current_app.config["MAIL_FROM"], "to": [to], "subject": subject, "text": text}
    if html:
        payload["html"] = html
    try:
        res = requests.post("https://api.resend.com/emails", json=payload, timeout=15,
                            headers={"Authorization": f"Bearer {current_app.config['RESEND_API_KEY']}"})
    except requests.RequestException as err:
        raise MailError(str(err)) from err
    if res.status_code >= 300:
        raise MailError(f"Resend {res.status_code}: {res.text[:200]}")
