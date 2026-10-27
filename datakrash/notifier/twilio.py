"""
Copyright (c) 2026 Apache-2.0 license

@file
@brief  SMS through the Twilio REST API
"""

from __future__ import annotations

import httpx

from datakrash.notifier.base import Notifier, NotifyFailed

API = "https://api.twilio.com/2010-04-01"


class Twilio(Notifier):
    address_field = "phone"

    def send(self, to: str, subject: str, body: str) -> None:
        account = self.setting("account_sid")
        try:
            response = self.http.post(
                f"{API}/Accounts/{account}/Messages.json",
                auth=(account, self.setting("token")),
                data={"From": self.setting("sender"), "To": to, "Body": body},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise NotifyFailed(
                f"SMS: Twilio answered {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise NotifyFailed(f"SMS: {type(exc).__name__}: {exc}") from exc
