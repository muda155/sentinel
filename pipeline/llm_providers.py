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
import time
from dataclasses import dataclass

import requests

from pipeline.llm_verifier import (
    _llm_timeout,
    _ratelimit_backoff,
    _ratelimit_max_wait,
    _retry_after_seconds,
)

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


class ProviderFailed(RuntimeError):
    """This provider cannot answer; the chain should try the next one."""


# Statuses that will not clear on their own. Falling through immediately is the
# same conclusion _fetch_page_with_retry reached for ACLED's 403.
_NO_RETRY_STATUSES = (401, 402, 403)


def call_openai_compatible(
    prompt: str, *, provider: Provider, retries: int = 3, timeout: int | None = None,
) -> tuple[str, str]:
    timeout = _llm_timeout(timeout)
    model = model_of(provider)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": float(os.getenv("SENTINEL_LLM_TEMPERATURE", "0")),
        "max_tokens": int(os.getenv("SENTINEL_LLM_MAX_TOKENS", "500")),
    }
    headers = {
        "Authorization": f"Bearer {api_key_of(provider)}",
        "Content-Type": "application/json",
    }
    endpoint = endpoint_of(provider)
    waited: list[float] = []
    for attempt in range(1, retries + 1):
        try:
            response = requests.post(endpoint, headers=headers, json=payload,
                                     timeout=timeout)
            response.raise_for_status()
            if waited:
                # A retry that succeeds is otherwise silent, so only the 429s
                # that exhausted anyway reach the log and the backoff cannot be
                # told apart from a no-op in production.
                logger.info(
                    "%s 429 cleared after %d retr%s (%.0fs waited)",
                    provider.name, len(waited),
                    "y" if len(waited) == 1 else "ies", sum(waited),
                )
            return response.json()["choices"][0]["message"]["content"], \
                f"{provider.name}:{model}"
        except requests.Timeout as error:
            raise ProviderFailed(f"{provider.name} timed out after {timeout}s") from error
        except requests.HTTPError as error:
            status = error.response.status_code if error.response is not None else None
            if status in _NO_RETRY_STATUSES:
                logger.warning(
                    "%s rejected the request (%s) — key or quota, not retrying",
                    provider.name, status,
                )
                raise ProviderFailed(f"{provider.name} auth/quota {status}") from error
            if status == 429:
                stated = _retry_after_seconds(error.response)
                wait = stated if stated is not None else _ratelimit_backoff(attempt)
                if wait > _ratelimit_max_wait() or attempt >= retries:
                    raise ProviderFailed(f"{provider.name} rate limited") from error
                time.sleep(wait)
                waited.append(wait)
                continue
            if status is not None and status >= 500:
                if attempt < retries:
                    time.sleep(2 ** attempt)
                    continue
                raise ProviderFailed(f"{provider.name} server error {status}") from error
            # 4xx that is not auth, quota or rate limiting: our request is
            # wrong and every provider will say so. Let it escape.
            raise
        except requests.RequestException as error:
            raise ProviderFailed(f"{provider.name} unreachable: {error}") from error
    raise ProviderFailed(f"{provider.name} exhausted {retries} attempts")
