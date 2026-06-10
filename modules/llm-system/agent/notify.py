import os
import smtplib
from email.mime.text import MIMEText

import yaml

_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../.."))


def send_notification(result, pr_url=None):
    with open(os.path.join(_ROOT, "config/notify.yml")) as f:
        cfg = yaml.safe_load(f)

    smtp_host = cfg["smtp_host"]
    smtp_port = cfg["smtp_port"]
    from_addr = cfg["from"]
    to_addr = cfg["to"]
    password = os.environ["NOTIFY_PASSWORD"]

    if result["status"] == "success":
        subject = "[project-red] Fix applied — PR ready"
        body = f"PR åpnet: {pr_url}. Løst i forsøk {result['attempt']}/5."
    else:
        subject = "[project-red] Agent gave up — manual action required"
        body = (
            "Agenten klarte ikke å fikse feilen etter 5 forsøk. "
            f"Siste feilmelding:\n\n{result['last_error']}"
        )

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        smtp.starttls()
        smtp.login(from_addr, password)
        smtp.sendmail(from_addr, to_addr, msg.as_string())
