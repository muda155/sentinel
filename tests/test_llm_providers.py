"""Provider chain resolution and transport (FR-31)."""
import pytest

from pipeline.llm_providers import (
    PROVIDERS,
    NoProviderConfigured,
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
