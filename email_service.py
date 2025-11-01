"""Email sending functionality using SMTP."""

import mimetypes
import os
import smtplib
from email.message import EmailMessage


def send_email(subject: str, body: str, to_addrs, attachments: list[str] | None = None) -> bool:
    """
    Send email with subject, body text and optionally attachments.
    Uses SMTP_* and MAIL_* environment variables for configuration.

    subject:    Email subject
    body:       Message text (sent as plain text)
    to_addrs:   Recipient(s). Can be a string ("a@x.com") or list.
    attachments: List of file paths to attach (CSV, MD, etc.)
    Returns True if sent successfully, False if error.
    """
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "465"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    from_addr = os.getenv("MAIL_FROM", user)

    if isinstance(to_addrs, str):
        to_addrs_list = [a.strip() for a in to_addrs.split(",") if a.strip()]
    else:
        to_addrs_list = to_addrs or []

    if not all([host, port, user, password, from_addr]) or not to_addrs_list:
        print("❌ Faltan SMTP_HOST/PORT/USER/PASS/MAIL_FROM o MAIL_TO en .env")
        return False

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = ", ".join(to_addrs_list)
    msg["Subject"] = subject
    msg.set_content(body)

    for path in (attachments or []):
        try:
            ctype, _ = mimetypes.guess_type(path)
            if not ctype:
                ctype = "application/octet-stream"
            maintype, subtype = ctype.split("/", 1)

            with open(path, "rb") as f:
                msg.add_attachment(
                    f.read(),
                    maintype=maintype,
                    subtype=subtype,
                    filename=os.path.basename(path)
                )
        except Exception as e:
            print(f"⚠️ No pude adjuntar {path}: {e}")

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=60) as s:
                s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=60) as s:
                s.starttls()
                s.login(user, password)
                s.send_message(msg)

        print("✉️  Email enviado correctamente.")
        return True

    except Exception as e:
        print(f"❌ Error enviando email: {e}")
        return False

