from email.message import EmailMessage

from flight_radar.notifier import EmailNotifier


def test_email_notifier_sends_message_with_link(monkeypatch):
    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout, context):
            captured.update(host=host, port=port, timeout=timeout, context=context)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def login(self, username, password):
            captured.update(username=username, password=password)

        def send_message(self, message: EmailMessage):
            captured["message"] = message

    monkeypatch.setenv("FLIGHT_RADAR_SMTP_PASSWORD", "app-password")
    monkeypatch.setattr("flight_radar.notifier.smtplib.SMTP_SSL", FakeSMTP)
    notifier = EmailNotifier(
        "smtp.example.test", 465, True, "sender@example.test", "receiver@example.test", "FLIGHT_RADAR_SMTP_PASSWORD"
    )

    notifier.send("title", "content", "https://example.test/flight")

    assert notifier.configured is True
    assert captured["username"] == "sender@example.test"
    assert captured["password"] == "app-password"
    assert captured["message"]["Subject"] == "title"
    assert "https://example.test/flight" in captured["message"].get_content()
