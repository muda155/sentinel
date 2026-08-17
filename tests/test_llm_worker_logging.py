import logging

import pytest

from pipeline.workers.llm_worker import configure_logging


@pytest.fixture(autouse=True)
def _restore_log_levels():
    """configure_logging mutates process-wide logger state; put it back."""
    root = logging.getLogger()
    saved = [(root, root.level)] + [
        (logging.getLogger(n), logging.getLogger(n).level)
        for n in ("httpx", "httpcore", "sentinel.llm_verifier")
    ]
    yield
    for logger, level in saved:
        logger.setLevel(level)


def test_our_loggers_reach_info() -> None:
    # The root logger with no handler falls back to lastResort (WARNING only),
    # which silently discarded every logger.info in the SITREP path.
    configure_logging()
    assert logging.getLogger("sentinel.llm_verifier").isEnabledFor(logging.INFO)


def test_httpx_is_quieted() -> None:
    # Raising the root level switches on httpx too: one line per HuggingFace
    # request, which buries the 429-recovery signal the level was raised for.
    configure_logging()
    for noisy in ("httpx", "httpcore"):
        assert not logging.getLogger(noisy).isEnabledFor(logging.INFO)


def test_level_is_env_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_LEVEL", "WARNING")
    configure_logging()
    assert not logging.getLogger("sentinel.llm_verifier").isEnabledFor(logging.INFO)
