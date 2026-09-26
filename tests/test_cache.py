import asyncio
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from jev_chinesener import service
from jev_chinesener.api import create_app
from jev_chinesener.cache import (
    LocalLimitError,
    ProcessLimits,
    ResponseCache,
    fingerprint,
    response_key,
)
from jev_chinesener.candidates import rules
from jev_chinesener.config import Settings
from jev_chinesener.lexicon import Lexicon
from jev_chinesener.models import SegmentRequest
from jev_chinesener.providers import MockJudge, ProviderError
from jev_chinesener.service import Segmenter


class CountingJudge(MockJudge):
    def __init__(self):
        self.calls = 0

    async def evaluate(self, state, questions):
        self.calls += 1
        result = await super().evaluate(state, questions)
        result.usage = {"input_tokens": 10, "output_tokens": 2}
        return result


def engine_with_cache(**settings):
    return Segmenter(Settings(cache_enabled=True, **settings), judge=CountingJudge())


def semantic(response):
    return response.model_dump(exclude={"diagnostics"})


async def test_default_disabled_preserves_calls_and_diagnostics():
    engine = Segmenter(Settings(fast_path=False), judge=CountingJudge())
    request = SegmentRequest(text="星海路")
    first = await engine.segment(request)
    calls = engine.judge.calls
    second = await engine.segment(request)
    assert calls > 0 and engine.judge.calls == 2 * calls
    assert semantic(first) == semantic(second)
    assert "cache_hit" not in second.diagnostics
    assert engine.cache is None


async def test_cache_hit_skips_judge_preserves_semantics_and_current_usage():
    engine = engine_with_cache(fast_path=False)
    request = SegmentRequest(text="星海路")
    first = await engine.segment(request)
    calls = engine.judge.calls
    second = await engine.segment(request)
    assert calls > 0 and engine.judge.calls == calls
    assert semantic(first) == semantic(second)
    assert first.diagnostics["cache_hit"] is False
    assert second.diagnostics["cache_hit"] is True
    assert second.diagnostics["api_requests"] == second.diagnostics["rounds"] == 0
    assert second.diagnostics["questions"] == 0 and second.diagnostics["usage"] == {}
    assert second.diagnostics["cache_origin"]["usage"] == first.diagnostics["usage"]
    assert engine.cache.stats() == {
        "hits": 1,
        "misses": 1,
        "entries": 1,
        "evictions": 0,
        "expirations": 0,
    }


async def test_fast_path_caches_final_response_before_prepare(monkeypatch):
    engine = engine_with_cache()
    request = SegmentRequest(text="东莞市")
    first = await engine.segment(request)

    def never_prepare(request):
        raise AssertionError("缓存命中应跳过编排")

    monkeypatch.setattr(engine, "prepare", never_prepare)
    second = await engine.segment(request)
    assert first.diagnostics["fast_path"] and second.diagnostics["cache_hit"]
    assert engine.judge.calls == 0 and semantic(first) == semantic(second)


@pytest.mark.parametrize("backend", ["mock", "local"])
async def test_degraded_offline_results_remain_cacheable(backend):
    engine = Segmenter(Settings(backend=backend, cache_enabled=True))
    request = SegmentRequest(text="星海路")
    first = await engine.segment(request)
    second = await engine.segment(request)
    assert first.status == second.status == "degraded"
    assert second.diagnostics["cache_hit"] and semantic(first) == semantic(second)


@pytest.mark.parametrize(
    "changes",
    [
        {"text": "星海大道"},
        {"input_kind": "place_name"},
        {"granularity": "geographic_unit"},
        {"granularity": "name_component"},
        {"region_context": "江苏省"},
        {"region_context": ""},
        {"return_components": False},
        {"top_k": 1},
    ],
)
async def test_request_changes_miss(changes):
    engine = engine_with_cache(fast_path=False)
    request = SegmentRequest(text="星海路")
    await engine.segment(request)
    calls = engine.judge.calls
    result = await engine.segment(request.model_copy(update=changes))
    assert result.diagnostics["cache_hit"] is False and engine.judge.calls > calls
    assert engine.cache.stats()["misses"] == 2


@pytest.mark.parametrize(
    "name,value",
    [
        ("ambiguity_margin", 0.1),
        ("fast_path", False),
        ("max_candidate_length", 4),
        ("backend", "local"),
        ("batch_size", 10),
        ("concurrency", 1),
        ("timeout_seconds", 10),
    ],
)
async def test_settings_changes_miss(name, value):
    engine = engine_with_cache()
    request = SegmentRequest(text="星海路")
    await engine.segment(request)
    calls = engine.judge.calls
    setattr(engine.settings, name, value)
    result = await engine.segment(request)
    assert not result.diagnostics["cache_hit"] and engine.judge.calls > calls


@pytest.mark.parametrize("change", ["lexicon", "entry", "calibration", "verified", "rules"])
async def test_asset_and_version_changes_miss(change, monkeypatch):
    engine = engine_with_cache(fast_path=False)
    request = SegmentRequest(text="星海路")
    first = await engine.segment(request)
    calls = engine.judge.calls
    if change == "lexicon":
        engine.lexicon = Lexicon(engine.lexicon.entries[:-1])
    elif change == "entry":
        engine.lexicon.entries[0].version = "changed-test-entry"
    elif change == "calibration":
        monkeypatch.setattr(service, "BOUNDARY_CALIBRATION_VERSION", "test-version")
    elif change == "verified":
        engine.verified = []
    else:
        monkeypatch.setitem(rules(), "negative_surfaces", ["星海路"])
    result = await engine.segment(request)
    assert not result.diagnostics["cache_hit"] and engine.judge.calls > calls
    if change in {"lexicon", "entry"}:
        assert result.versions["lexicon_fingerprint"] != first.versions["lexicon_fingerprint"]
    if change == "calibration":
        assert result.versions["boundary_calibration"] == "test-version"


async def test_calendar_day_invalidates_lexicon_validity(monkeypatch):
    from datetime import UTC, datetime

    class NextDay:
        @staticmethod
        def now(tz):
            return datetime(2099, 1, 1, tzinfo=UTC)

    engine = engine_with_cache(fast_path=False)
    request = SegmentRequest(text="星海路")
    await engine.segment(request)
    monkeypatch.setattr(service, "datetime", NextDay)
    assert not (await engine.segment(request)).diagnostics["cache_hit"]


def test_key_canonical_order_full_versions_model_and_backend():
    request = SegmentRequest(text="南京市", region_context=None)
    settings = Settings()
    versions = {"lexicon": "demo", "boundary_calibration": "v1"}
    key = response_key(request, settings, versions, "mock")
    assert len(key) == 64 and request.text not in key
    assert key == response_key(request, settings, dict(reversed(list(versions.items()))), "mock")
    assert key != response_key(request, settings, versions, "local")
    # 正式 Settings 锁定模型；在键的单元边界模拟未来显式模型升级。
    upgraded = settings.model_copy(update={"model": "future-pinned-test-model"})
    assert key != response_key(request, upgraded, versions, "mock")
    for name in versions:
        assert key != response_key(request, settings, {**versions, name: "v2"}, "mock")
    assert fingerprint({"a": None, "b": ""}) == fingerprint({"b": "", "a": None})


async def test_judge_replacement_cannot_reuse_another_judges_result():
    engine = engine_with_cache(fast_path=False)
    request = SegmentRequest(text="星海路")
    await engine.segment(request)
    engine.judge = CountingJudge()
    result = await engine.segment(request)
    assert not result.diagnostics["cache_hit"] and engine.judge.calls > 0


async def test_cache_copies_on_write_and_read():
    engine = engine_with_cache(fast_path=False)
    request = SegmentRequest(text="星海路")
    first = await engine.segment(request)
    expected = semantic(first)
    first.units[0].text = "篡改首次响应"
    second = await engine.segment(request)
    assert semantic(second) == expected
    second.units[0].evidence.clear()
    second.diagnostics["cache_origin"]["usage"].clear()
    third = await engine.segment(request)
    assert semantic(third) == expected
    assert third.diagnostics["cache_origin"]["usage"]["input_tokens"] > 0


async def test_lru_ttl_and_stats_without_sleep_or_disk(tmp_path, monkeypatch, caplog):
    response = await Segmenter(Settings()).segment(SegmentRequest(text="东莞市"))
    monkeypatch.chdir(tmp_path)
    now = [0.0]
    cache = ResponseCache(2, 10, clock=lambda: now[0])
    keys = [fingerprint(text) for text in ["私人测试地址甲", "乙", "丙"]]
    cache.put(keys[0], response)
    cache.put(keys[1], response)
    assert cache.get(keys[0]) is not None
    cache.put(keys[2], response)
    assert cache.get(keys[1]) is None  # 最近未使用项被淘汰。
    now[0] = 9
    assert cache.get(keys[0]) is not None
    now[0] = 10
    assert cache.get(keys[0]) is None  # 读取不延长 TTL。
    assert cache.stats() == {"hits": 2, "misses": 2, "entries": 0, "evictions": 1, "expirations": 2}
    assert not list(tmp_path.iterdir())
    assert "私人测试地址甲" not in caplog.text and response.text not in caplog.text


async def test_ttl_expiration_calls_judge_again():
    engine = engine_with_cache(fast_path=False)
    request = SegmentRequest(text="星海路")
    await engine.segment(request)
    engine.cache = ResponseCache(2, 1, clock=lambda: 0)
    engine.settings.cache_max_entries = 2
    engine.settings.cache_ttl_seconds = 1
    await engine.segment(request)
    calls = engine.judge.calls
    engine.cache.clock = lambda: 1
    result = await engine.segment(request)
    assert not result.diagnostics["cache_hit"] and engine.judge.calls > calls
    assert engine.cache.stats()["expirations"] == 1


async def test_disabling_cache_bypasses_existing_entry():
    engine = engine_with_cache(fast_path=False)
    request = SegmentRequest(text="星海路")
    await engine.segment(request)
    calls = engine.judge.calls
    engine.settings.cache_enabled = False
    result = await engine.segment(request)
    assert engine.judge.calls > calls and "cache_hit" not in result.diagnostics


async def test_transient_provider_failure_is_not_cached():
    class RecoveringJudge(CountingJudge):
        async def evaluate(self, state, questions):
            if self.calls == 0:
                self.calls += 1
                raise ProviderError("test_unavailable")
            return await super().evaluate(state, questions)

    engine = Segmenter(Settings(cache_enabled=True, fast_path=False), judge=RecoveringJudge())
    request = SegmentRequest(text="星海路")
    first = await engine.segment(request)
    assert first.status == "degraded" and engine.cache.stats()["entries"] == 0
    assert not (await engine.segment(request)).diagnostics["cache_hit"]
    assert (await engine.segment(request)).diagnostics["cache_hit"]


async def test_inflight_setting_change_does_not_populate_old_key():
    entered, resume = asyncio.Event(), asyncio.Event()

    class PausedJudge(CountingJudge):
        async def evaluate(self, state, questions):
            entered.set()
            await resume.wait()
            return await super().evaluate(state, questions)

    engine = Segmenter(Settings(cache_enabled=True, fast_path=False), judge=PausedJudge())
    task = asyncio.create_task(engine.segment(SegmentRequest(text="星海路")))
    await entered.wait()
    engine.settings.ambiguity_margin = 0.1
    resume.set()
    await task
    assert engine.cache.stats()["entries"] == 0


@pytest.mark.parametrize(
    "setting,code",
    [
        ("rate_limit_requests", "rate_limit_exceeded"),
        ("request_budget", "request_budget_exhausted"),
    ],
)
async def test_limits_reject_before_cache_or_judge(setting, code):
    limits = ProcessLimits()
    engine = Segmenter(
        Settings(cache_enabled=True, fast_path=False, **{setting: 2}),
        judge=CountingJudge(),
        limits=limits,
    )
    request = SegmentRequest(text="私人测试地址甲")
    await engine.segment(request)
    await engine.segment(request)  # 命中也计入入站准入上限。
    calls = engine.judge.calls
    with pytest.raises(LocalLimitError, match=code) as exc:
        await engine.segment(request)
    assert request.text not in str(exc.value)
    assert engine.judge.calls == calls
    assert engine.cache.stats()["hits"] == 1
    assert limits.stats() == {"accepted": 2, "rejected": 1}


def test_sliding_window_recovers_at_exact_boundary():
    now = [0.0]
    limits = ProcessLimits(clock=lambda: now[0])
    settings = Settings(rate_limit_requests=1, rate_limit_window_seconds=10)
    limits.admit(settings)
    now[0] = 9.99
    with pytest.raises(LocalLimitError, match="rate_limit_exceeded"):
        limits.admit(settings)
    now[0] = 10
    limits.admit(settings)
    assert limits.stats() == {"accepted": 2, "rejected": 1}


def test_request_budget_is_atomic_across_threads():
    limits = ProcessLimits()
    settings = Settings(request_budget=3)

    def admit(_):
        try:
            limits.admit(settings)
            return True
        except LocalLimitError:
            return False

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(admit, range(20))) == 3
    assert limits.stats() == {"accepted": 3, "rejected": 17}


def test_default_engines_share_process_limits():
    assert Segmenter(Settings()).limits is Segmenter(Settings()).limits


def test_limits_disabled_do_not_consume_budget():
    limits = ProcessLimits()
    for _ in range(3):
        limits.admit(Settings())
    assert limits.stats() == {"accepted": 0, "rejected": 0}


@pytest.mark.parametrize(
    "setting,code",
    [
        ("rate_limit_requests", "rate_limit_exceeded"),
        ("request_budget", "request_budget_exhausted"),
    ],
)
def test_api_limit_error_is_local_and_contains_no_text(setting, code, caplog):
    engine = Segmenter(Settings(**{setting: 1}), limits=ProcessLimits())
    client = TestClient(create_app(engine))
    request = {"text": "私人测试地址甲"}
    assert client.post("/v1/toponyms/segment", json=request).status_code == 200
    result = client.post("/v1/toponyms/segment", json=request)
    assert result.status_code == 429 and result.json() == {"detail": {"code": code}}
    assert request["text"] not in caplog.text


def test_cache_and_limit_environment(monkeypatch):
    values = {
        "JEV_CACHE_ENABLED": "1",
        "JEV_CACHE_MAX_ENTRIES": "7",
        "JEV_CACHE_TTL_SECONDS": "2.5",
        "JEV_RATE_LIMIT_REQUESTS": "4",
        "JEV_RATE_LIMIT_WINDOW_SECONDS": "12",
        "JEV_REQUEST_BUDGET": "30",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)
    settings = Settings.from_env()
    assert settings.cache_enabled and settings.cache_max_entries == 7
    assert settings.cache_ttl_seconds == 2.5 and settings.rate_limit_requests == 4
    assert settings.rate_limit_window_seconds == 12 and settings.request_budget == 30
    monkeypatch.setenv("JEV_CACHE_ENABLED", "0")
    assert not Settings.from_env().cache_enabled
