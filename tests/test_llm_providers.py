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


def test_a_400_raises_and_is_not_a_provider_failure(monkeypatch):
    # A malformed request is our bug; every provider rejects it identically.
    # ProviderFailed would send it down the chain and end at Ollama, which
    # would answer a prompt the paid providers refused — a successful-looking
    # run built on a request we know is wrong.
    post = Mock(return_value=_err(400))
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post)
    with pytest.raises(requests.HTTPError):
        call_openai_compatible("p", provider=PROVIDERS["deepseek"], retries=3)
    assert post.call_count == 1


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


def test_a_400_stops_the_chain_dead(monkeypatch):
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "deepseek,kimi")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "d")
    monkeypatch.setenv("MOONSHOT_API_KEY", "m")
    calls = []

    def _fake(prompt, *, provider, retries=3, timeout=None):
        calls.append(provider.name)
        raise requests.HTTPError("bad request")

    monkeypatch.setattr("pipeline.llm_providers.call_openai_compatible", _fake)
    with pytest.raises(requests.HTTPError):
        call_llm("p")
    assert calls == ["deepseek"], "a malformed request must not reach the next provider"


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
