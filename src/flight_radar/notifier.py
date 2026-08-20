from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage


class NotificationError(RuntimeError):
    pass


@dataclass
class EmailNotifier:
    host: str
    port: int
    use_ssl: bool
    username: str
    recipient: str
    password_env: str
    timeout_seconds: float = 15.0

    @property
    def configured(self) -> bool:
        return bool(self.host and self.username and self.recipient and os.getenv(self.password_env))

    def send(self, title: str, content: str, click_url: str | None = None) -> None:
        password = os.getenv(self.password_env)
        if not self.username or not password:
            raise NotificationError(
                f"{self.password_env} is not set; configure the SMTP authorization password"
            )
        message = EmailMessage()
        message["Subject"] = title
        message["From"] = self.username
        message["To"] = self.recipient
        body = content
        if click_url:
            body = f"{content}\n\n打开航班页面：{click_url}"
        message.set_content(body)
        try:
            context = ssl.create_default_context()
            if self.use_ssl:
                with smtplib.SMTP_SSL(
                    self.host, self.port, timeout=self.timeout_seconds, context=context
                ) as smtp:
                    smtp.login(self.username, password)
                    smtp.send_message(message)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=self.timeout_seconds) as smtp:
                    smtp.starttls(context=context)
                    smtp.login(self.username, password)
                    smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise NotificationError(f"SMTP request failed: {exc}") from exc


class ConsoleNotifier:
    def send(self, title: str, content: str, click_url: str | None = None) -> None:
        print(f"\n{title}\n{content}")
        if click_url:
            print(click_url)
