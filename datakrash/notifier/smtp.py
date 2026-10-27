"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  Email over SMTP
"""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from datakrash.notifier.base import HTTP_TIMEOUT, Notifier, NotifyFailed


class Smtp(Notifier):
    address_field = "email"

    def _connect(self) -> smtplib.SMTP:
        host = self.setting("host")
        port = int(self.settings.get("port", 587))
        security = self.settings.get("security", "starttls")
        context = ssl.create_default_context()

        if security == "ssl":
            return smtplib.SMTP_SSL(host, port, timeout=HTTP_TIMEOUT, context=context)
        if security != "starttls":
            raise NotifyFailed(
                f"notifier.{self.channel}.security must be starttls or ssl"
            )

        server = smtplib.SMTP(host, port, timeout=HTTP_TIMEOUT)
        server.starttls(context=context)
        return server

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.setting("sender")
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        try:
            with self._connect() as server:
                if self.settings.get("username"):
                    server.login(self.settings["username"], self.setting("password"))
                server.send_message(message)
        except (smtplib.SMTPException, OSError) as exc:
            raise NotifyFailed(f"email: {type(exc).__name__}: {exc}") from exc
