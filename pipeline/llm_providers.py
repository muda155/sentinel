"""FR-31: ordered multi-provider LLM chain.

NIM, DeepSeek and Kimi all speak the OpenAI /chat/completions shape, so one
adapter serves three; Ollama's /api/generate keeps its own. Providers are tried
in the order SENTINEL_LLM_PROVIDERS names them.

A provider with no credential is dropped when the chain is BUILT, before any
request — the same treatment translate_enabled() and acled_credentials_configured()
give an unconfigured optional integration. An empty chain raises, because
"nothing was configured" and "everything was tried and failed" are different
failures and only one of them is worth an alert.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("sentinel.llm_providers")


class NoProviderConfigured(RuntimeError):
    """SENTINEL_LLM_PROVIDERS resolved to nothing usable."""


@dataclass(frozen=True)
class Provider:
    name: str
    kind: str                 # "openai" | "ollama"
    endpoint_env: str
    endpoint_default: str
    key_env: str | None       # None => no credential needed
    model_env: str
    model_default: str
    paid: bool


PROVIDERS: dict[str, Provider] = {
    "deepseek": Provider(
        "deepseek", "openai", "DEEPSEEK_ENDPOINT",
        "https://api.deepseek.com/v1/chat/completions",
        "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "deepseek-v4-flash", True,
    ),
    "kimi": Provider(
        "kimi", "openai", "MOONSHOT_ENDPOINT",
        "https://api.moonshot.ai/v1/chat/completions",
        "MOONSHOT_API_KEY", "MOONSHOT_MODEL", "kimi-k2.5", True,
    ),
    "nim": Provider(
        "nim", "openai", "NVIDIA_NIM_ENDPOINT",
        "https://integrate.api.nvidia.com/v1/chat/completions",
        "NVIDIA_NIM_API_KEY", "NVIDIA_NIM_MODEL",
        "meta/llama-3.3-70b-instruct", True,
    ),
    "ollama": Provider(
        "ollama", "ollama", "OLLAMA_ENDPOINT", "http://localhost:11434",
        None, "SENTINEL_OLLAMA_MODEL", "llama3:8b", False,
    ),
}

DEFAULT_CHAIN = "deepseek,kimi,ollama"


def endpoint_of(provider: Provider) -> str:
    return os.getenv(provider.endpoint_env, "").strip() or provider.endpoint_default


def model_of(provider: Provider) -> str:
    return os.getenv(provider.model_env, "").strip() or provider.model_default


def api_key_of(provider: Provider) -> str:
    return "" if provider.key_env is None else os.getenv(provider.key_env, "").strip()


def resolve_chain(*, paid_allowed: bool = True) -> list[Provider]:
    names = [n.strip() for n in
             os.getenv("SENTINEL_LLM_PROVIDERS", DEFAULT_CHAIN).split(",") if n.strip()]
    chain: list[Provider] = []
    for name in names:
        provider = PROVIDERS.get(name)
        if provider is None:
            logger.warning("unknown LLM provider %r in SENTINEL_LLM_PROVIDERS", name)
            continue
        if provider.paid and not paid_allowed:
            continue
        if provider.key_env is not None and not api_key_of(provider):
            continue
        chain.append(provider)
    if not chain:
        raise NoProviderConfigured(
            f"no usable provider in SENTINEL_LLM_PROVIDERS={names!r} "
            f"(paid_allowed={paid_allowed})"
        )
    return chain
