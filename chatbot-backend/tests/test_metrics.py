def _value(text, prefix):
    for line in text.splitlines():
        if line.startswith(prefix):
            return float(line.rsplit(" ", 1)[1])
    raise AssertionError(f"{prefix} not found")


def test_metrics_endpoint_exposes_series_from_the_start(client):
    text = client.get("/metrics").text
    # init_series 要讓這些序列一開始就存在(值 0),否則告警算不出第一次增量
    assert 'http_requests_total{method="POST",path="/chat",status="502"}' in text


def test_chat_request_is_counted_by_route_template(client):
    key = 'http_requests_total{method="POST",path="/chat",status="200"}'
    before = _value(client.get("/metrics").text, key)
    client.post("/chat", json={"user_id": "u", "message": "hi"})
    after = _value(client.get("/metrics").text, key)
    assert after == before + 1


def test_unknown_paths_collapse_into_one_label(client):
    client.get("/no-such-page-1")
    client.get("/no-such-page-2")
    text = client.get("/metrics").text
    assert 'path="unmatched"' in text
    assert "no-such-page" not in text  # 不能讓任意路徑變成無限多條時間序列


def test_llm_token_usage_is_recorded(client, stub_llm):
    key = 'llm_tokens_total{model="%s",type="output"}' % __import__("main").GEMINI_MODEL
    before = _value(client.get("/metrics").text, key)
    client.post("/chat", json={"user_id": "u", "message": "hi"})
    assert _value(client.get("/metrics").text, key) == before + 20
