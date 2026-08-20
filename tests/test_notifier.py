from flight_radar.notifier import PushPlusNotifier


def test_pushplus_payload(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"code": "200"}

    def fake_post(endpoint, json, timeout):
        captured.update(endpoint=endpoint, json=json, timeout=timeout)
        return Response()

    monkeypatch.setenv("TEST_PUSHPLUS_TOKEN", "secret")
    monkeypatch.setattr("flight_radar.notifier.httpx.post", fake_post)
    notifier = PushPlusNotifier("https://example.test/send", "app", "TEST_PUSHPLUS_TOKEN")
    notifier.send("title", "content", "https://example.test/flight")
    assert captured["json"]["token"] == "secret"
    assert captured["json"]["channel"] == "app"
    assert "https://example.test/flight" in captured["json"]["content"]
