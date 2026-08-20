from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


class NotificationError(RuntimeError):
    pass


@dataclass
class PushPlusNotifier:
    endpoint: str
    channel: str
    token_env: str
    timeout_seconds: float = 15.0

    @property
    def configured(self) -> bool:
        return bool(os.getenv(self.token_env))

    def send(self, title: str, content: str, click_url: str | None = None) -> None:
        token = os.getenv(self.token_env)
        if not token:
            raise NotificationError(
                f"{self.token_env} is not set; install PushPlus and configure its token"
            )
        body: dict[str, str] = {
            "token": token,
            "title": title,
            "content": content,
            "template": "markdown",
            "channel": self.channel,
        }
        if click_url:
            body["content"] = f"{content}\n\n[打开航班页面]({click_url})"
        try:
            response = httpx.post(self.endpoint, json=body, timeout=self.timeout_seconds)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise NotificationError(f"PushPlus request failed: {exc}") from exc
        if str(payload.get("code", "0")) != "200":
            raise NotificationError(f"PushPlus rejected message: {payload}")


class ConsoleNotifier:
    def send(self, title: str, content: str, click_url: str | None = None) -> None:
        print(f"\n{title}\n{content}")
        if click_url:
            print(click_url)
