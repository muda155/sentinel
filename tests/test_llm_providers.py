"""Provider chain resolution and transport (FR-31)."""
from unittest.mock import Mock

import pytest
import requests

from pipeline.llm_providers import (
    PROVIDERS,
    NoProviderConfigured,
    ProviderFailed,
    call_llm,
    call_openai_compatible,
    resolve_chain,
)


@pytest.fixture(autouse=True)
def _clean_provider_env(monkeypatch):
    # Every provider key is cleared so a developer's real sentinel.env cannot
    # change which providers a test sees.
    for name in ("DEEPSEEK_API_KEY", "MOONSHOT_API_KEY", "NVIDIA_NIM_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("SENTINEL_LLM_PROVIDERS", raising=False)


def test_chain_follows_the_configured_order(monkeypatch):
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "kimi,deepseek,ollama")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setenv("MOONSHOT_API_KEY", "m")
    assert [p.name for p in resolve_chain()] == ["kimi", "deepseek", "ollama"]


def test_a_provider_without_a_key_is_dropped_not_failed(monkeypatch):
    # Only Kimi is configured; deepseek must vanish rather than be attempted
    # and error, which is how translate_enabled()/acled_credentials_configured()
    # already treat an unconfigured optional integration.
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "deepseek,kimi,ollama")
    monkeypatch.setenv("MOONSHOT_API_KEY", "m")
    assert [p.name for p in resolve_chain()] == ["kimi", "ollama"]


def test_ollama_needs_no_key(monkeypatch):
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "ollama")
    assert [p.name for p in resolve_chain()] == ["ollama"]


def test_unknown_provider_names_are_dropped(monkeypatch):
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "gpt5,ollama")
    assert [p.name for p in resolve_chain()] == ["ollama"]


def test_paid_providers_are_dropped_when_not_allowed(monkeypatch):
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "deepseek,kimi,ollama")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setenv("MOONSHOT_API_KEY", "m")
    assert [p.name for p in resolve_chain(paid_allowed=False)] == ["ollama"]


def test_an_empty_chain_raises_rather_than_returning_nothing(monkeypatch):
    # Distinct from "every provider was tried and failed" — nothing was tried.
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "deepseek")
    with pytest.raises(NoProviderConfigured):
        resolve_chain()


def test_the_default_chain_is_deepseek_kimi_ollama(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setenv("MOONSHOT_API_KEY", "m")
    assert [p.name for p in resolve_chain()] == ["deepseek", "kimi", "ollama"]


def test_nim_is_implemented_but_not_in_the_default_chain():
    # NIM currently times out on every call in this deployment; it stays
    # available by name, not by default.
    assert "nim" in PROVIDERS


def _ok(content="hello"):
    r = Mock()
    r.status_code = 200
    r.raise_for_status.return_value = None
    r.json.return_value = {"choices": [{"message": {"content": content}}]}
    return r


def _err(status):
    r = Mock()
    r.status_code = status
    r.headers = {}
    r.raise_for_status.side_effect = requests.HTTPError(response=r)
    return r


def test_a_successful_call_returns_provider_colon_model(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setattr("pipeline.llm_providers.requests.post", Mock(return_value=_ok()))
    text, used = call_openai_compatible("p", provider=PROVIDERS["deepseek"])
    assert text == "hello"
    assert used == "deepseek:deepseek-v4-flash"


def test_the_key_is_sent_as_a_bearer_token(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "secret")
    post = Mock(return_value=_ok())
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post)
    call_openai_compatible("p", provider=PROVIDERS["deepseek"])
    assert post.call_args.kwargs["headers"]["Authorization"] == "Bearer secret"


def test_auth_failures_are_not_retried(monkeypatch):
    # A rejected key or an exhausted quota does not clear within a tick;
    # retrying one only burns the single-threaded worker. Assert the CALL
    # COUNT — a test that only checks the exception cannot tell one attempt
    # from three, which is the whole behaviour being specified.
    for status in (401, 402, 403):
        post = Mock(return_value=_err(status))
        monkeypatch.setattr("pipeline.llm_providers.requests.post", post)
        with pytest.raises(ProviderFailed):
            call_openai_compatible("p", provider=PROVIDERS["deepseek"], retries=3)
        assert post.call_count == 1, f"status {status} was retried"


def test_a_400_is_a_provider_failure_and_falls_through(monkeypatch,
                                                       caplog: pytest.LogCaptureFixture):
    # Some 4xx are our bug, but some are provider-scoped (a temperature
    # constraint, a retired model id) and must not take down every hotspot
    # with no fallback. The WARNING keeps the rejection observable.
    post = Mock(return_value=_err(400))
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post)
    with caplog.at_level("WARNING", logger="sentinel.llm_providers"):
        with pytest.raises(ProviderFailed):
            call_openai_compatible("p", provider=PROVIDERS["deepseek"], retries=3)
    assert post.call_count == 1
    assert any("rejected the request" in r.getMessage() for r in caplog.records)


def test_5xx_is_retried_then_reported_as_a_provider_failure(monkeypatch):
    post = Mock(return_value=_err(503))
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post)
    monkeypatch.setattr("pipeline.llm_providers.time.sleep", Mock())
    with pytest.raises(ProviderFailed):
        call_openai_compatible("p", provider=PROVIDERS["deepseek"], retries=3)
    assert post.call_count == 3


def test_a_timeout_is_a_provider_failure(monkeypatch):
    post = Mock(side_effect=requests.Timeout())
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post)
    with pytest.raises(ProviderFailed):
        call_openai_compatible("p", provider=PROVIDERS["deepseek"], retries=3)
    assert post.call_count == 1


def test_429_falls_through_when_the_wait_exceeds_the_cap(monkeypatch):
    # The worker is single-threaded: parking it past the cap stalls every
    # other hotspot queued behind this one.
    monkeypatch.setenv("SENTINEL_LLM_RATELIMIT_MAX_WAIT_S", "5")
    r = _err(429)
    r.headers = {"Retry-After": "600"}
    post = Mock(return_value=r)
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post)
    with pytest.raises(ProviderFailed):
        call_openai_compatible("p", provider=PROVIDERS["deepseek"], retries=3)
    assert post.call_count == 1


def test_the_chain_tries_the_next_provider_after_a_failure(monkeypatch):
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "deepseek,kimi")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setenv("MOONSHOT_API_KEY", "m")
    calls = []

    def _fake(prompt, *, provider, retries=3, timeout=None):
        calls.append(provider.name)
        if provider.name == "deepseek":
            raise ProviderFailed("down")
        return "from kimi", f"{provider.name}:x"

    monkeypatch.setattr("pipeline.llm_providers.call_openai_compatible", _fake)
    text, used = call_llm("p")
    assert calls == ["deepseek", "kimi"]
    assert (text, used) == ("from kimi", "kimi:x")


def test_a_400_does_not_stop_the_chain(monkeypatch):
    # A provider-scoped 400 (temperature constraint, retired model id) must
    # fall through like any ProviderFailed — one provider's rejection must
    # not end the run for every hotspot behind it.
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "deepseek,kimi")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setenv("MOONSHOT_API_KEY", "m")
    calls = []

    def _fake(prompt, *, provider, retries=3, timeout=None):
        calls.append(provider.name)
        if provider.name == "deepseek":
            raise ProviderFailed("deepseek rejected the request (400)")
        return "from kimi", f"{provider.name}:x"

    monkeypatch.setattr("pipeline.llm_providers.call_openai_compatible", _fake)
    text, used = call_llm("p")
    assert calls == ["deepseek", "kimi"], "a 400 must fall through to the next provider"
    assert (text, used) == ("from kimi", "kimi:x")


def test_the_paid_gate_keeps_a_low_score_off_the_paid_providers(monkeypatch):
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "deepseek,ollama")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setenv("SENTINEL_LLM_PAID_MIN_CONF", "70")
    paid = Mock(side_effect=AssertionError("paid provider must not be called"))
    monkeypatch.setattr("pipeline.llm_providers.call_openai_compatible", paid)
    monkeypatch.setattr("pipeline.llm_providers.call_ollama_raw",
                        Mock(return_value=("local", "llama-3-8b-ollama")))
    assert call_llm("p", conf_score=69.9) == ("local", "llama-3-8b-ollama")


def test_a_score_above_the_gate_reaches_the_paid_provider(monkeypatch):
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "deepseek,ollama")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setenv("SENTINEL_LLM_PAID_MIN_CONF", "70")
    monkeypatch.setattr("pipeline.llm_providers.call_openai_compatible",
                        Mock(return_value=("paid", "deepseek:deepseek-v4-flash")))
    assert call_llm("p", conf_score=70.1)[1] == "deepseek:deepseek-v4-flash"


def test_an_unknown_score_is_treated_as_paid_allowed(monkeypatch):
    # conf_score=None means the caller did not scope the call (the /report
    # endpoint is one). Refusing to spend there would silently downgrade a
    # user-triggered request that has its own 4/min bucket already.
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "deepseek,ollama")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setattr("pipeline.llm_providers.call_openai_compatible",
                        Mock(return_value=("paid", "deepseek:m")))
    assert call_llm("p", conf_score=None)[0] == "paid"


def test_ollama_keeps_its_fr12_audit_tag(monkeypatch):
    monkeypatch.setenv("SENTINEL_OLLAMA_MODEL", "llama3:8b")
    r = Mock()
    r.raise_for_status.return_value = None
    r.json.return_value = {"response": "text"}
    monkeypatch.setattr("pipeline.llm_providers.requests.post", Mock(return_value=r))
    from pipeline.llm_providers import call_ollama_raw
    assert call_ollama_raw("p")[1] == "llama-3-8b-ollama"


def test_openai_compatible_payloads_carry_no_thinking_param(monkeypatch):
    # Reasoning stays ON for the SITREP quality; neither provider may receive
    # a thinking toggle NIM might reject.
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setenv("NVIDIA_NIM_API_KEY", "n")
    post = Mock(return_value=_ok())
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post)

    call_openai_compatible("p", provider=PROVIDERS["deepseek"])
    assert "thinking" not in post.call_args.kwargs["json"]

    call_openai_compatible("p", provider=PROVIDERS["nim"])
    assert "thinking" not in post.call_args.kwargs["json"]


def test_kimi_uses_the_model_required_temperature(monkeypatch):
    # kimi-k2.6 only accepts temperature 1 with reasoning on (the default) —
    # the pipeline's SENTINEL_LLM_TEMPERATURE (0.3) would 400 and kill the
    # chain.
    monkeypatch.setenv("MOONSHOT_API_KEY", "m")
    post = Mock(return_value=_ok())
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post)

    call_openai_compatible("p", provider=PROVIDERS["kimi"])
    payload = post.call_args.kwargs["json"]
    assert "thinking" not in payload
    assert payload["temperature"] == 1.0


def test_empty_content_on_a_2xx_is_a_provider_failure(monkeypatch):
    # Reasoning models answer 200 with empty content when the reasoning
    # exhausts max_tokens. That is not an answer — it must fail over, and a
    # deterministic failure is not worth retrying.
    post = Mock(return_value=_ok(content=""))
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post)
    with pytest.raises(ProviderFailed):
        call_openai_compatible("p", provider=PROVIDERS["deepseek"], retries=3)
    assert post.call_count == 1


def test_malformed_2xx_body_is_a_provider_failure_not_a_keyerror(monkeypatch):
    # A 2xx whose body is not the chat shape must fall through, not abort the
    # chain with an uncaught KeyError/IndexError.
    r = Mock()
    r.status_code = 200
    r.raise_for_status.return_value = None
    r.json.return_value = {"unexpected": True}
    post = Mock(return_value=r)
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post)
    with pytest.raises(ProviderFailed):
        call_openai_compatible("p", provider=PROVIDERS["deepseek"], retries=3)
    assert post.call_count == 1


def test_default_max_tokens_budget_covers_reasoning(monkeypatch):
    # Reasoning stays ON; the default budget must exceed the measured
    # reasoning output (~6k deepseek, ~9k kimi completion tokens) or every
    # paid call returns empty content and silently downgrades to Ollama.
    monkeypatch.delenv("SENTINEL_LLM_MAX_TOKENS", raising=False)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    post = Mock(return_value=_ok())
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post)
    call_openai_compatible("p", provider=PROVIDERS["deepseek"])
    assert post.call_args.kwargs["json"]["max_tokens"] == 20000
