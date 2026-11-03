"""重試策略:有上限、有退避、有期限、429 不重試。用假的 sleep/clock,測試不會真的等。"""
import pytest

from llm_client import RetryPolicy, invoke_with_retry
from metrics import LLM_ATTEMPTS


class Flaky:
    def __init__(self, fail_times, exc=RuntimeError("boom")):
        self.fail_times, self.exc, self.calls = fail_times, exc, 0

    def invoke(self, messages):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return "ok"


def run(llm, policy, clock=None):
    sleeps = []
    kwargs = {"sleep": sleeps.append, "rand": lambda: 1.0}
    if clock:
        kwargs["clock"] = clock
    return sleeps, lambda: invoke_with_retry(llm, [], policy, "m", **kwargs)


def test_success_first_try_no_sleep():
    llm = Flaky(0)
    sleeps, call = run(llm, RetryPolicy())
    assert call() == "ok" and llm.calls == 1 and sleeps == []


def test_retries_then_succeeds():
    llm = Flaky(1)
    sleeps, call = run(llm, RetryPolicy(max_attempts=3, backoff_base=1, backoff_cap=10))
    assert call() == "ok" and llm.calls == 2 and sleeps == [1.0]


def test_attempts_are_capped():
    llm = Flaky(99)
    sleeps, call = run(llm, RetryPolicy(max_attempts=3, backoff_base=1, backoff_cap=10))
    with pytest.raises(RuntimeError):
        call()
    assert llm.calls == 3 and len(sleeps) == 2  # 最後一次失敗後不再等


def test_backoff_grows_then_is_capped():
    llm = Flaky(99)
    sleeps, call = run(llm, RetryPolicy(max_attempts=6, backoff_base=1, backoff_cap=4, deadline=999))
    with pytest.raises(RuntimeError):
        call()
    assert sleeps == [1.0, 2.0, 4.0, 4.0, 4.0]


def test_rate_limit_is_not_retried():
    llm = Flaky(99, exc=RuntimeError("429 RESOURCE_EXHAUSTED quota"))
    sleeps, call = run(llm, RetryPolicy(max_attempts=5))
    with pytest.raises(RuntimeError):
        call()
    assert llm.calls == 1 and sleeps == []


def test_deadline_stops_retrying():
    llm = Flaky(99)
    t = iter([0, 29, 29, 29])  # 第一次失敗時已過 29 秒,再等會超過 30 秒期限
    sleeps, call = run(llm, RetryPolicy(max_attempts=5, backoff_base=5, deadline=30), clock=lambda: next(t))
    with pytest.raises(RuntimeError):
        call()
    assert llm.calls == 1 and sleeps == []


def test_attempt_metric_counts_every_try():
    before = LLM_ATTEMPTS.labels("m2", "error")._value.get()
    llm = Flaky(2)
    invoke_with_retry(llm, [], RetryPolicy(max_attempts=3, backoff_base=0), "m2", sleep=lambda s: None)
    assert LLM_ATTEMPTS.labels("m2", "error")._value.get() - before == 2
