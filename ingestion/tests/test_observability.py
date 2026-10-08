from oddsmith_ingestion import observability


def test_no_dsn_means_sentry_stays_off(monkeypatch):
    calls = []
    monkeypatch.setattr(observability.sentry_sdk, "init", lambda **kw: calls.append(kw))
    assert observability.init_sentry("") is False
    assert calls == []


def test_dsn_initialises_sentry_without_pii_or_tracing(monkeypatch):
    calls = []
    monkeypatch.setattr(observability.sentry_sdk, "init", lambda **kw: calls.append(kw))
    assert observability.init_sentry("https://key@o1.ingest.sentry.io/1") is True
    (kwargs,) = calls
    assert kwargs["send_default_pii"] is False
    assert kwargs["traces_sample_rate"] == 0
    assert kwargs["server_name"] == "ingestion"
    assert kwargs["before_send"] is observability.scrub_event
    assert kwargs["before_breadcrumb"] is observability.scrub_breadcrumb


def test_breadcrumb_urls_lose_api_keys():
    crumb = {
        "category": "httplib",
        "data": {
            "url": "https://api.the-odds-api.com/v4/sports/soccer_epl/odds",
            "http.query": "apiKey=SECRET123&markets=h2h",
        },
        "message": "GET https://x/odds?apiKey=SECRET123&markets=h2h",
    }
    scrubbed = observability.scrub_breadcrumb(crumb, {})
    assert "SECRET123" not in repr(scrubbed)
    assert "markets=h2h" in scrubbed["data"]["http.query"]
    assert "SECRET123" in repr(crumb)  # original untouched


def test_event_text_and_headers_lose_secrets():
    event = {
        "exception": {"values": [{"value": "failed GET ...?apiKey=SECRET123"}]},
        "request": {"headers": {"x-apisports-key": "AFKEY", "accept": "json"}},
        "breadcrumbs": {"values": [{"message": "url?apiKey=SECRET123"}]},
    }
    scrubbed = observability.scrub_event(event, {})
    text = repr(scrubbed)
    assert "SECRET123" not in text
    assert "AFKEY" not in text
    assert scrubbed["request"]["headers"]["accept"] == "json"
