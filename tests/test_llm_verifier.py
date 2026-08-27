import json
from unittest import mock

import pytest
import requests
from pydantic import ValidationError

from pipeline import llm_verifier


def test_build_prompt_contains_sources_and_citation_directive() -> None:
    data = {
        "hotspot_id": 12,
        "articles": [
            {"title": "Article A", "url": "https://a.com/1", "domain": "a.com"},
            {"title": "Article B", "url": "https://b.com/2", "domain": "b.com"},
        ],
    }
    prompt = llm_verifier.build_prompt(data)
    assert "Act as an intelligence analyst" in prompt
    assert "exactly ONE citation" in prompt
    assert "[N]" in prompt
    assert "https://a.com/1" in prompt
    assert "https://b.com/2" in prompt


def test_validate_citations_passes_when_all_cited() -> None:
    valid = "Forces advanced 5km [1]. Fire was reported near the border [2]."
    # Returns None and does not raise when every sentence is cited.
    assert llm_verifier.validate_citations(valid) is None


def test_validate_citations_raises_listing_uncited_sentence() -> None:
    invalid = "Forces advanced 5km. Fire was reported near the border [2]."
    with pytest.raises(ValueError) as exc:
        llm_verifier.validate_citations(invalid)
    assert "Forces advanced 5km." in str(exc.value)


def test_call_nim_api_retries_on_429_then_returns_json(monkeypatch: pytest.MonkeyPatch) -> None:
    too_many = mock.Mock()
    too_many.status_code = 429
    too_many.raise_for_status.side_effect = requests.HTTPError(response=too_many)

    ok = mock.Mock()
    ok.raise_for_status.return_value = None
    ok.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"conflict_detected": false, "conflict_detail": "", '
                        '"summary": "Calm conditions persisted [1].", '
                        '"sources_cited": ["https://a.com/1"]}'
                    )
                }
            }
        ]
    }
    post_mock = mock.Mock(side_effect=[too_many, ok])
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "nim")
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post_mock)
    monkeypatch.setattr("pipeline.llm_providers.time.sleep", mock.Mock())

    result, model_used = llm_verifier.call_nim_api(
        prompt="test",
        endpoint="https://example.com/v1/chat/completions",
        api_key="secret",
        model="meta/llama-3.1-70b-instruct",
    )
    assert result["conflict_detected"] is False
    assert model_used == "nim:meta/llama-3.1-70b-instruct"
    assert post_mock.call_count == 2


def test_ollama_fallback_triggered_on_429_exhaustion(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NIM returns 429 on every attempt, Ollama fallback is called."""
    too_many = mock.Mock()
    too_many.status_code = 429
    too_many.raise_for_status.side_effect = requests.HTTPError(response=too_many)

    # Mock Ollama response
    ollama_response = mock.Mock()
    ollama_response.raise_for_status.return_value = None
    ollama_response.json.return_value = {
        "response": (
            '{"conflict_detected": false, "conflict_detail": "", '
            '"summary": "Calm conditions persisted [1].", '
            '"sources_cited": ["https://a.com/1"]}'
        )
    }

    # Track which endpoint was called
    def post_side_effect(url, **kwargs):
        if "ollama" in url or "11434" in url:
            return ollama_response
        raise requests.HTTPError(response=too_many)

    post_mock = mock.Mock(side_effect=post_side_effect)
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "nim,ollama")
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post_mock)
    monkeypatch.setattr("pipeline.llm_providers.time.sleep", mock.Mock())

    result, model_used = llm_verifier.call_nim_api(
        prompt="test",
        endpoint="https://nim.example.com/v1/chat/completions",
        api_key="secret",
        model="meta/llama-3.1-70b-instruct",
        retries=3,
        ollama_endpoint="http://localhost:11434",
    )
    assert result["conflict_detected"] is False
    assert model_used == "llama-3-8b-ollama"
    # Should have been called 4+ times (3 NIM failures + 1 Ollama success)
    assert post_mock.call_count >= 4


def test_call_ollama_fallback_mocked() -> None:
    """call_ollama_fallback sends correct payload to Ollama endpoint."""
    with mock.patch("pipeline.llm_providers.requests.post") as post_mock:
        ollama_response = mock.Mock()
        ollama_response.raise_for_status.return_value = None
        ollama_response.json.return_value = {
            "response": (
                '{"conflict_detected": false, "conflict_detail": "", '
                '"summary": "Calm conditions persisted [1].", '
                '"sources_cited": ["https://a.com/1"]}'
            )
        }
        post_mock.return_value = ollama_response

        result, model_used = llm_verifier.call_ollama_fallback(
            prompt="test prompt",
            endpoint="http://localhost:11434",
        )
        assert result["conflict_detected"] is False
        assert model_used == "llama-3-8b-ollama"

        # Verify the correct endpoint and payload
        call_args, call_kwargs = post_mock.call_args
        assert call_args[0] == "http://localhost:11434/api/generate"
        payload = call_kwargs["json"]
        assert payload["model"] == "llama3:8b"
        assert payload["prompt"] == "test prompt"
        assert payload["stream"] is False
        assert payload["options"]["temperature"] == 0


def test_verify_hotspots_accepts_ollama_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """verify_hotspots_with_llm accepts and forwards ollama_endpoint parameter."""
    monkeypatch.setattr(
        "pipeline.llm_verifier.LLMRepository.candidate_hotspots",
        lambda self, threshold: [1],
    )
    monkeypatch.setattr(
        "pipeline.llm_verifier.LLMRepository.fetch_hotspot_articles",
        lambda self, hotspot_id: [{"title": "Test", "url": "https://example.com/a", "domain": "a.com"}],
    )
    monkeypatch.setattr(
        "pipeline.llm_verifier.LLMRepository.save_summary",
        lambda self, hotspot_id, result, model: None,
    )
    monkeypatch.setattr(
        "pipeline.consistency.run_consistency_engine",
        lambda conn, hotspot_id, **kwargs: None,
    )

    # Track what call_nim_api receives
    captured_kwargs = {}

    def fake_call_nim_api(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return {"conflict_detected": False, "conflict_detail": "", "summary": "Test [1].", "sources_cited": []}, "test-model"

    monkeypatch.setattr("pipeline.llm_verifier.call_nim_api", fake_call_nim_api)

    mock_cursor = mock.MagicMock()
    mock_cursor.__enter__.return_value.fetchone.return_value = [42]
    mock_conn = mock.MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    llm_verifier.verify_hotspots_with_llm(
        conn=mock_conn,
        endpoint="https://nim.example.com",
        api_key="secret",
        model="meta/llama-3.1-70b-instruct",
        threshold=40,
        ollama_endpoint="http://custom-ollama:11434",
    )
    assert captured_kwargs.get("ollama_endpoint") == "http://custom-ollama:11434"


def test_verify_hotspots_with_llm_skips_below_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pipeline.llm_verifier.LLMRepository.candidate_hotspots",
        lambda self, threshold: [],
    )
    call_mock = mock.Mock()
    monkeypatch.setattr("pipeline.llm_verifier.call_nim_api", call_mock)

    result = llm_verifier.verify_hotspots_with_llm(
        conn=object(),
        endpoint="https://example.com/v1/chat/completions",
        api_key="secret",
        model="meta/llama-3.1-70b-instruct",
        threshold=40,
    )
    assert result == {"candidates": 0, "processed": 0}
    call_mock.assert_not_called()


def test_validate_citations_all_cited() -> None:
    assert llm_verifier.validate_citations("Forces advanced 5km [1]. Artillery deployed [2].") is None


def test_validate_citations_missing_citation() -> None:
    with pytest.raises(ValueError):
        llm_verifier.validate_citations("Forces advanced 5km. Artillery deployed [2].")


def test_validate_citations_non_numeric_citation() -> None:
    with pytest.raises(ValueError):
        llm_verifier.validate_citations("Forces advanced [src1]. Artillery deployed [2].")


def test_validate_citations_empty() -> None:
    with pytest.raises(ValueError):
        llm_verifier.validate_citations("")


def test_validate_citations_abbreviation_is_not_sentence_boundary() -> None:
    assert llm_verifier.validate_citations(
        "The U.S. Senate blocked the resolution [1]. The U.K. and E.U. responded [2]."
    ) is None


def test_validate_citations_uncited_sentence_after_abbreviation_still_raises() -> None:
    with pytest.raises(ValueError):
        llm_verifier.validate_citations(
            "The U.S. Senate blocked the resolution. Artillery deployed [2]."
        )


def test_validate_citations_title_abbreviations_are_not_boundaries() -> None:
    assert llm_verifier.validate_citations(
        "A man was found near Mount St. Helens [1]. "
        "The Urban League of St. Louis and Gen. Smith responded [2]."
    ) is None


def test_llm_summary_model_accepts_valid_summary() -> None:
    model = llm_verifier.LLMSummary(
        conflict_detected=False,
        conflict_detail="",
        summary="Forces advanced 5km [1]. Artillery deployed [2].",
        sources_cited=["1", "2"],
    )
    assert model.summary.endswith("[2].")


def test_llm_summary_model_rejects_uncited_summary() -> None:
    with pytest.raises(ValueError):
        llm_verifier.LLMSummary(
            conflict_detected=False,
            conflict_detail="",
            summary="Forces advanced 5km. Artillery deployed [2].",
            sources_cited=["2"],
        )


def test_llm_summary_coerces_numeric_sources_cited() -> None:
    model = llm_verifier.LLMSummary(
        conflict_detected=True,
        conflict_detail="border activity",
        summary="Forces advanced 5km [1]. Artillery deployed [2].",
        sources_cited=[1, 2],
    )
    assert model.sources_cited == ["1", "2"]


def test_call_ollama_fallback_returns_validated_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    ollama_response = mock.Mock()
    ollama_response.raise_for_status.return_value = None
    # Note: no conflict_detail key, numeric sources_cited -> model must normalize both.
    ollama_response.json.return_value = {
        "response": (
            '{"conflict_detected": true, '
            '"summary": "Shelling resumed at dawn [1].", '
            '"sources_cited": [1]}'
        )
    }
    monkeypatch.setattr(
        "pipeline.llm_providers.requests.post",
        mock.Mock(return_value=ollama_response),
    )

    result, model_used = llm_verifier.call_ollama_fallback(
        prompt="test", endpoint="http://localhost:11434"
    )
    assert model_used == "llama-3-8b-ollama"
    assert result["conflict_detected"] is True
    assert result["conflict_detail"] == ""          # default filled by model
    assert result["sources_cited"] == ["1"]          # coerced to str


def test_call_nim_api_returns_validated_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    ok = mock.Mock()
    ok.raise_for_status.return_value = None
    # No conflict_detail, numeric sources_cited -> model normalizes both.
    ok.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"conflict_detected": false, '
                        '"summary": "Calm conditions persisted [1].", '
                        '"sources_cited": [1]}'
                    )
                }
            }
        ]
    }
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "nim")
    monkeypatch.setattr("pipeline.llm_providers.requests.post", mock.Mock(return_value=ok))

    result, model_used = llm_verifier.call_nim_api(
        prompt="test",
        endpoint="https://example.com/v1/chat/completions",
        api_key="secret",
        model="meta/llama-3.1-70b-instruct",
    )
    assert model_used == "nim:meta/llama-3.1-70b-instruct"
    assert result["conflict_detail"] == ""       # default filled by model
    assert result["sources_cited"] == ["1"]       # coerced to str


def test_call_nim_api_parses_markdown_fenced_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """NIM frequently wraps JSON in ```json fences / prose; it must still parse."""
    ok = mock.Mock()
    ok.raise_for_status.return_value = None
    ok.json.return_value = {
        "choices": [
            {
                "message": {
                    "content": (
                        "**Output JSON:**\n```json\n"
                        '{"conflict_detected": false, '
                        '"summary": "Calm conditions persisted [1].", '
                        '"sources_cited": [1]}\n```'
                    )
                }
            }
        ]
    }
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "nim")
    monkeypatch.setattr("pipeline.llm_providers.requests.post", mock.Mock(return_value=ok))

    result, model_used = llm_verifier.call_nim_api(
        prompt="test",
        endpoint="https://example.com/v1/chat/completions",
        api_key="secret",
        model="meta/llama-3.1-70b-instruct",
    )
    assert result["summary"] == "Calm conditions persisted [1]."
    assert result["sources_cited"] == ["1"]


def test_call_nim_api_uses_env_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default read timeout is env-configurable via SENTINEL_LLM_TIMEOUT_S."""
    monkeypatch.setenv("SENTINEL_LLM_TIMEOUT_S", "60")
    ok = mock.Mock()
    ok.raise_for_status.return_value = None
    ok.json.return_value = {
        "choices": [
            {"message": {"content": '{"conflict_detected": false, "summary": "Quiet [1].", "sources_cited": [1]}'}}
        ]
    }
    post_mock = mock.Mock(return_value=ok)
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "nim")
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post_mock)

    llm_verifier.call_nim_api(
        prompt="test",
        endpoint="https://example.com/v1/chat/completions",
        api_key="secret",
        model="meta/llama-3.1-70b-instruct",
    )
    assert post_mock.call_args.kwargs["timeout"] == 60


def test_fetch_hotspot_articles_order_is_deterministic():
    class _Cur:
        sql = ""
        def execute(self, sql, params=None):
            _Cur.sql = " ".join(sql.split())
        def fetchall(self):
            return []
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    class _Conn:
        def cursor(self):
            return _Cur()

    from pipeline.llm_verifier import LLMRepository
    LLMRepository(_Conn()).fetch_hotspot_articles(1)
    assert "ORDER BY e.event_date DESC, e.event_id DESC" in _Cur.sql


def test_validate_citations_accepts_dispute_double_index():
    from pipeline.llm_verifier import validate_citations
    validate_citations("Forces advanced 5km [1]. Sources disagree on casualties [2][5].")


def test_validate_citations_rejects_triple_index():
    from pipeline.llm_verifier import validate_citations
    with pytest.raises(ValueError):
        validate_citations("Sources disagree [1][2][3].")


def test_build_claims_sitrep_prompt_contains_statuses():
    from pipeline.consistency import ClaimVerdict, EngineResult, EvidenceJudgment
    from pipeline.llm_verifier import build_claims_sitrep_prompt

    result = EngineResult(
        verdicts=[
            ClaimVerdict(text="Army advanced north.", status="corroborated",
                         support=1.5, dispute=0.0, weight=1.5,
                         evidence=[EvidenceJudgment(1, 1, "a.com", "supports", 0.9),
                                   EvidenceJudgment(2, 2, "b.com", "supports", 0.9)]),
            ClaimVerdict(text="Ten casualties reported.", status="disputed",
                         support=0.7, dispute=0.6, weight=1.3,
                         evidence=[EvidenceJudgment(1, 1, "a.com", "supports", 0.8),
                                   EvidenceJudgment(3, 3, "c.com", "contradicts", 0.9)]),
        ],
        score=57.7, insufficient_sources=False,
    )
    prompt = build_claims_sitrep_prompt(99, result)
    assert "CORROBORATED" in prompt and "DISPUTED" in prompt
    assert "Army advanced north." in prompt
    assert "[1][3]" in prompt  # dispute citation pair supporter+contradictor


def test_call_llm_raw_retries_on_500_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    # A transient NIM 500 must be retried with backoff, not instantly dumped
    # onto the (possibly absent) Ollama fallback.
    err = mock.Mock()
    err.status_code = 500
    err.raise_for_status.side_effect = requests.HTTPError(response=err)
    ok = mock.Mock()
    ok.raise_for_status.return_value = None
    ok.json.return_value = {"choices": [{"message": {"content": "hello"}}]}
    post_mock = mock.Mock(side_effect=[err, ok])
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "nim")
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post_mock)
    monkeypatch.setattr("pipeline.llm_providers.time.sleep", mock.Mock())

    content, model_used = llm_verifier.call_llm_raw(
        "p", endpoint="https://nim.example.com/v1/chat", api_key="k", model="m",
    )
    assert content == "hello" and model_used == "nim:m"
    assert post_mock.call_count == 2


def test_call_llm_raw_500_exhaustion_falls_back_to_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    err = mock.Mock()
    err.status_code = 502
    err.raise_for_status.side_effect = requests.HTTPError(response=err)
    ollama_ok = mock.Mock()
    ollama_ok.raise_for_status.return_value = None
    ollama_ok.json.return_value = {"response": "fallback text"}

    def post_side_effect(url, **kwargs):
        if "11434" in url:
            return ollama_ok
        raise requests.HTTPError(response=err)

    post_mock = mock.Mock(side_effect=post_side_effect)
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "nim,ollama")
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post_mock)
    monkeypatch.setattr("pipeline.llm_providers.time.sleep", mock.Mock())

    content, model_used = llm_verifier.call_llm_raw(
        "p", endpoint="https://nim.example.com/v1/chat", api_key="k", model="m",
        retries=3, ollama_endpoint="http://localhost:11434",
    )
    assert content == "fallback text"
    assert model_used == "llama-3-8b-ollama"
    assert post_mock.call_count == 4  # 3 NIM attempts + 1 Ollama


def test_call_llm_raw_skips_nim_when_endpoint_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    # An Ollama-only host has endpoint="" but OLLAMA_ENDPOINT set. Posting to ""
    # would raise MissingSchema, which is neither Timeout nor HTTPError, so the
    # fallback was unreachable and every report 503'd with Ollama healthy.
    post_mock = mock.Mock()
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post_mock)

    def fake_ollama(prompt, endpoint="http://localhost:11434", timeout=None):
        return "ollama text", "llama-3-8b-ollama"

    monkeypatch.setattr("pipeline.llm_providers.call_ollama_raw", fake_ollama)
    content, model_used = llm_verifier.call_llm_raw(
        "p", endpoint="", api_key="k", model="m", ollama_endpoint="http://localhost:11434",
    )
    assert content == "ollama text"
    assert model_used == "llama-3-8b-ollama"
    post_mock.assert_not_called()


def test_ollama_model_env_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SENTINEL_OLLAMA_MODEL", "llama3.2:3b")
    ok = mock.Mock()
    ok.raise_for_status.return_value = None
    ok.json.return_value = {"response": "hi"}
    post_mock = mock.Mock(return_value=ok)
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post_mock)

    content, model_used = llm_verifier.call_ollama_raw("p")
    assert content == "hi"
    assert post_mock.call_args.kwargs["json"]["model"] == "llama3.2:3b"
    assert model_used == "llama3.2:3b-ollama"


def _rate_limited(retry_after: object = None) -> mock.Mock:
    """A 429 response; `retry_after` sets the header NIM uses to state its quota reset."""
    resp = mock.Mock()
    resp.status_code = 429
    resp.headers = {} if retry_after is None else {"Retry-After": retry_after}
    resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
    return resp


def test_429_backoff_outlasts_the_5xx_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    # A 429 is a quota clock, not a transient fault: the 2**attempt 5xx schedule
    # (2s, 4s) retries inside the same rate-limit window, so all three attempts
    # burn and the hotspot lands on the Ollama fallback that cannot cite.
    ok = mock.Mock()
    ok.raise_for_status.return_value = None
    ok.json.return_value = {"choices": [{"message": {"content": "hello"}}]}
    post_mock = mock.Mock(side_effect=[_rate_limited(), _rate_limited(), ok])
    sleeps: list[float] = []
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "nim")
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post_mock)
    monkeypatch.setattr("pipeline.llm_providers.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.delenv("SENTINEL_LLM_RATELIMIT_BACKOFF_S", raising=False)

    content, _model = llm_verifier.call_llm_raw(
        "p", endpoint="https://nim.example.com/v1/chat", api_key="k", model="m",
    )
    assert content == "hello"
    assert post_mock.call_count == 3
    assert sleeps == [15.0, 30.0]


def test_5xx_keeps_the_short_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    # The rate-limit schedule must not slow the transient-fault path.
    err = mock.Mock()
    err.status_code = 503
    err.headers = {}
    err.raise_for_status.side_effect = requests.HTTPError(response=err)
    ok = mock.Mock()
    ok.raise_for_status.return_value = None
    ok.json.return_value = {"choices": [{"message": {"content": "hello"}}]}
    post_mock = mock.Mock(side_effect=[err, err, ok])
    sleeps: list[float] = []
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "nim")
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post_mock)
    monkeypatch.setattr("pipeline.llm_providers.time.sleep", lambda s: sleeps.append(s))

    content, _model = llm_verifier.call_llm_raw(
        "p", endpoint="https://nim.example.com/v1/chat", api_key="k", model="m",
    )
    assert content == "hello"
    assert sleeps == [2, 4]


def test_429_honours_retry_after_header(monkeypatch: pytest.MonkeyPatch) -> None:
    # When NIM states its reset explicitly, guessing is strictly worse.
    ok = mock.Mock()
    ok.raise_for_status.return_value = None
    ok.json.return_value = {"choices": [{"message": {"content": "hello"}}]}
    post_mock = mock.Mock(side_effect=[_rate_limited("7"), ok])
    sleeps: list[float] = []
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "nim")
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post_mock)
    monkeypatch.setattr("pipeline.llm_providers.time.sleep", lambda s: sleeps.append(s))

    content, _model = llm_verifier.call_llm_raw(
        "p", endpoint="https://nim.example.com/v1/chat", api_key="k", model="m",
    )
    assert content == "hello"
    assert sleeps == [7.0]


def test_429_retry_after_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    # An hour-long Retry-After would park the single-threaded worker for an hour
    # and stall every other hotspot behind it; past the cap, fall back instead.
    ollama_ok = mock.Mock()
    ollama_ok.raise_for_status.return_value = None
    ollama_ok.json.return_value = {"response": "fallback text"}

    def post_side_effect(url, **kwargs):
        if "11434" in url:
            return ollama_ok
        raise requests.HTTPError(response=_rate_limited("3600"))

    sleeps: list[float] = []
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "nim,ollama")
    monkeypatch.setattr("pipeline.llm_providers.requests.post",
                        mock.Mock(side_effect=post_side_effect))
    monkeypatch.setattr("pipeline.llm_providers.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.setenv("SENTINEL_LLM_RATELIMIT_MAX_WAIT_S", "60")

    content, model_used = llm_verifier.call_llm_raw(
        "p", endpoint="https://nim.example.com/v1/chat", api_key="k", model="m",
        ollama_endpoint="http://localhost:11434",
    )
    assert content == "fallback text"
    assert model_used == "llama-3-8b-ollama"
    assert sleeps == []  # never waited; a reset beyond the cap is not worth blocking on


def test_429_ignores_unparseable_retry_after(monkeypatch: pytest.MonkeyPatch) -> None:
    # Retry-After may be an HTTP-date rather than seconds; fall back to the schedule.
    ok = mock.Mock()
    ok.raise_for_status.return_value = None
    ok.json.return_value = {"choices": [{"message": {"content": "hello"}}]}
    post_mock = mock.Mock(side_effect=[_rate_limited("Wed, 21 Oct 2026 07:28:00 GMT"), ok])
    sleeps: list[float] = []
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "nim")
    monkeypatch.setattr("pipeline.llm_providers.requests.post", post_mock)
    monkeypatch.setattr("pipeline.llm_providers.time.sleep", lambda s: sleeps.append(s))
    monkeypatch.delenv("SENTINEL_LLM_RATELIMIT_BACKOFF_S", raising=False)

    content, _model = llm_verifier.call_llm_raw(
        "p", endpoint="https://nim.example.com/v1/chat", api_key="k", model="m",
    )
    assert content == "hello"
    assert sleeps == [15.0]


def test_429_recovery_is_logged(monkeypatch: pytest.MonkeyPatch,
                                caplog: pytest.LogCaptureFixture) -> None:
    # A retry that succeeds logs nothing, so the only visible 429s were the ones
    # that exhausted anyway — leaving the backoff unfalsifiable in production.
    ok = mock.Mock()
    ok.raise_for_status.return_value = None
    ok.json.return_value = {"choices": [{"message": {"content": "hello"}}]}
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "nim")
    monkeypatch.setattr("pipeline.llm_providers.requests.post",
                        mock.Mock(side_effect=[_rate_limited("5"), _rate_limited("5"), ok]))
    monkeypatch.setattr("pipeline.llm_providers.time.sleep", mock.Mock())

    with caplog.at_level("INFO", logger="sentinel.llm_providers"):
        content, _model = llm_verifier.call_llm_raw(
            "p", endpoint="https://nim.example.com/v1/chat", api_key="k", model="m",
        )
    assert content == "hello"
    recovered = [r.getMessage() for r in caplog.records if "cleared" in r.getMessage()]
    assert len(recovered) == 1
    assert "2 retries" in recovered[0]
    assert "10s" in recovered[0]  # 5s stated twice


def test_no_recovery_log_when_no_ratelimit(monkeypatch: pytest.MonkeyPatch,
                                           caplog: pytest.LogCaptureFixture) -> None:
    # The common path must stay silent; a per-call INFO on every success would
    # bury the signal this log exists to carry.
    ok = mock.Mock()
    ok.raise_for_status.return_value = None
    ok.json.return_value = {"choices": [{"message": {"content": "hello"}}]}
    monkeypatch.setenv("SENTINEL_LLM_PROVIDERS", "nim")
    monkeypatch.setattr("pipeline.llm_providers.requests.post", mock.Mock(return_value=ok))

    with caplog.at_level("INFO", logger="sentinel.llm_providers"):
        llm_verifier.call_llm_raw(
            "p", endpoint="https://nim.example.com/v1/chat", api_key="k", model="m",
        )
    assert [r.getMessage() for r in caplog.records if "cleared" in r.getMessage()] == []


def _summary_json(summary: str, conflict_detail: object = "") -> str:
    return json.dumps({
        "conflict_detected": False,
        "conflict_detail": conflict_detail,
        "summary": summary,
        "sources_cited": ["1"],
    })


def test_summary_list_is_coerced_to_string() -> None:
    # The model intermittently returns summary/conflict_detail as a JSON list;
    # sources_cited already had a coercion validator and these did not, so the
    # whole hotspot was discarded on a formatting quirk.
    parsed = json.loads(_summary_json(""))
    parsed["summary"] = ["Forces advanced north [1].", "Fire was reported [2]."]
    result = llm_verifier.LLMSummary(**parsed)
    assert isinstance(result.summary, str)
    assert "Forces advanced north [1]." in result.summary
    assert "Fire was reported [2]." in result.summary


def test_conflict_detail_list_is_coerced_to_string() -> None:
    parsed = json.loads(_summary_json("Forces advanced north [1]."))
    parsed["conflict_detail"] = ["Sources disagree on the toll [1][2]"]
    result = llm_verifier.LLMSummary(**parsed)
    assert result.conflict_detail == "Sources disagree on the toll [1][2]"


def test_coerced_summary_list_still_validates_citations() -> None:
    # Coercion must not become a way to smuggle uncited text past FR-11.
    parsed = json.loads(_summary_json(""))
    parsed["summary"] = ["Forces advanced north.", "Fire was reported [2]."]
    with pytest.raises(ValueError, match="Forces advanced north."):
        llm_verifier.LLMSummary(**parsed)


def test_uncited_summary_triggers_one_repair_call(monkeypatch: pytest.MonkeyPatch) -> None:
    # The first call is 100% wasted on a format violation, so one re-prompt is
    # nearly free next to discarding the hotspot.
    prompts: list[str] = []

    def fake_raw(prompt, **kwargs):
        prompts.append(prompt)
        if len(prompts) == 1:
            return _summary_json("Forces advanced north."), "m"
        return _summary_json("Forces advanced north [1]."), "m"

    monkeypatch.setattr(llm_verifier, "call_llm_raw", fake_raw)
    result, model_used = llm_verifier.call_nim_api(
        "ORIGINAL PROMPT", endpoint="https://nim/x", api_key="k", model="m",
    )
    assert result["summary"] == "Forces advanced north [1]."
    assert model_used == "m"
    assert len(prompts) == 2
    # The repair prompt must carry both the original task and what was wrong.
    assert "ORIGINAL PROMPT" in prompts[1]
    assert "Forces advanced north." in prompts[1]


def test_valid_summary_makes_no_repair_call(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []

    def fake_raw(prompt, **kwargs):
        prompts.append(prompt)
        return _summary_json("Forces advanced north [1]."), "m"

    monkeypatch.setattr(llm_verifier, "call_llm_raw", fake_raw)
    llm_verifier.call_nim_api("p", endpoint="https://nim/x", api_key="k", model="m")
    assert len(prompts) == 1


def test_repair_failure_propagates_without_looping(monkeypatch: pytest.MonkeyPatch) -> None:
    # Exactly one repair: a model that cannot cite must not be retried forever.
    prompts: list[str] = []

    def fake_raw(prompt, **kwargs):
        prompts.append(prompt)
        return _summary_json("Forces advanced north."), "m"

    monkeypatch.setattr(llm_verifier, "call_llm_raw", fake_raw)
    with pytest.raises(ValidationError):
        llm_verifier.call_nim_api("p", endpoint="https://nim/x", api_key="k", model="m")
    assert len(prompts) == 2


def test_citation_repair_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts: list[str] = []

    def fake_raw(prompt, **kwargs):
        prompts.append(prompt)
        return _summary_json("Forces advanced north."), "m"

    monkeypatch.setattr(llm_verifier, "call_llm_raw", fake_raw)
    monkeypatch.setenv("SENTINEL_LLM_CITATION_REPAIR", "false")
    with pytest.raises(ValidationError):
        llm_verifier.call_nim_api("p", endpoint="https://nim/x", api_key="k", model="m")
    assert len(prompts) == 1


def test_call_llm_raw_delegates_to_the_chain(monkeypatch):
    from unittest.mock import Mock

    import pipeline.llm_verifier as lv

    chain = Mock(return_value=("text", "deepseek:m"))
    monkeypatch.setattr("pipeline.llm_verifier.call_llm", chain)
    out = lv.call_llm_raw("p", endpoint="", api_key="", model="")
    assert out == ("text", "deepseek:m")
    assert chain.call_count == 1


def test_call_llm_raw_passes_explicit_nim_config_through_as_overrides(monkeypatch):
    import os

    import pipeline.llm_verifier as lv

    captured = {}

    def _chain(prompt, **kwargs):
        captured["nim_endpoint"] = os.environ.get("NVIDIA_NIM_ENDPOINT")
        captured["nim_model"] = os.environ.get("NVIDIA_NIM_MODEL")
        return "t", "nim:m"

    monkeypatch.setattr("pipeline.llm_verifier.call_llm", _chain)
    lv.call_llm_raw("p", endpoint="https://nim.example/v1/chat/completions",
                    api_key="k", model="some-model")
    assert captured["nim_endpoint"] == "https://nim.example/v1/chat/completions"
    assert captured["nim_model"] == "some-model"


def test_extraction_and_sitrep_share_one_bound_llm(monkeypatch):
    from unittest.mock import MagicMock

    import pipeline.llm_verifier as lv

    seen = {}

    def _engine(conn, hotspot_id, *, llm=None, judge=None):
        seen["engine_llm"] = llm
        return None                      # forces the headline-prompt path

    repo_articles = [{"title": "t", "url": "https://e.com/1", "domain": "e.com"}]
    monkeypatch.setattr(lv.LLMRepository, "fetch_hotspot_articles",
                        lambda self, hid: repo_articles)
    monkeypatch.setattr(lv.LLMRepository, "fetch_conf_score", lambda self, hid: 75.0)
    monkeypatch.setattr(lv.LLMRepository, "save_summary", lambda *a, **k: None)

    def _llm_call(prompt, **kwargs):
        seen["sitrep_kwargs"] = kwargs
        return {"summary": "S [1].", "conflict_detected": False}, "deepseek:m"

    conn = MagicMock()
    # The final summary_id SELECT must read as "no row" on the mock connection.
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = None

    lv.generate_sitrep(conn, 1, endpoint="", api_key="", model="",
                       engine=_engine, llm_call=_llm_call)

    # the engine must receive a bound callable, not None
    assert seen["engine_llm"] is not None
    # and the SITREP must be told the same score
    assert seen["sitrep_kwargs"].get("conf_score") == 75.0


def test_null_conf_score_is_bound_as_local_only(monkeypatch):
    # A hotspot with NULL conf_score has never been scored; spending a paid
    # provider on it is not the gate's intent. conf_score=None inside
    # generate_sitrep must resolve to local-only (0.0), not the unscoped
    # paid-allowed meaning that /report's caller deliberately uses.
    from unittest.mock import MagicMock

    import pipeline.llm_verifier as lv

    seen = {}

    def _engine(conn, hotspot_id, *, llm=None, judge=None):
        seen["engine_llm"] = llm
        return None

    repo_articles = [{"title": "t", "url": "https://e.com/1", "domain": "e.com"}]
    monkeypatch.setattr(lv.LLMRepository, "fetch_hotspot_articles",
                        lambda self, hid: repo_articles)
    monkeypatch.setattr(lv.LLMRepository, "fetch_conf_score", lambda self, hid: None)
    monkeypatch.setattr(lv.LLMRepository, "save_summary", lambda *a, **k: None)

    def _llm_call(prompt, **kwargs):
        seen["sitrep_kwargs"] = kwargs
        return {"summary": "S [1].", "conflict_detected": False}, "deepseek:m"

    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = None

    lv.generate_sitrep(conn, 1, endpoint="", api_key="", model="",
                       engine=_engine, llm_call=_llm_call)

    assert seen["engine_llm"].keywords["conf_score"] == 0.0
    assert seen["sitrep_kwargs"].get("conf_score") == 0.0


def test_main_requires_a_configured_provider(monkeypatch):
    # The CLI used to hard-fail on missing NVIDIA_NIM_* even though the
    # default chain needs no NIM; it now gates on the resolved chain.
    import sys

    import pipeline.llm_providers as lp

    monkeypatch.setattr(sys, "argv", ["llm_verifier", "--threshold", "40"])
    monkeypatch.setattr(
        lp, "resolve_chain",
        lambda **kw: (_ for _ in ()).throw(lp.NoProviderConfigured("none")),
    )
    with pytest.raises(RuntimeError, match="no LLM provider configured"):
        llm_verifier.main()


def test_verify_hotspots_continues_after_a_failing_hotspot(monkeypatch):
    # One bad hotspot (every provider failing on it) must not end the run
    # for all the rest — the monolith/CLI loop isolates per hotspot like the
    # worker does.
    from unittest.mock import Mock

    import pipeline.llm_verifier as lv

    attempted = []

    def _sitrep(conn, hid, **kwargs):
        attempted.append(hid)
        if hid == 1:
            raise RuntimeError("every provider in the chain failed")
        return 99, "deepseek:m"

    monkeypatch.setattr(lv, "generate_sitrep", _sitrep)
    monkeypatch.setattr(lv.LLMRepository, "candidate_hotspots",
                        lambda self, threshold: [1, 2])
    monkeypatch.setattr(lv.LLMRepository, "fetch_hotspot_articles",
                        lambda self, hid: [{"title": "t", "url": "https://e.com/1", "domain": "e.com"}])

    result = lv.verify_hotspots_with_llm(
        Mock(), endpoint="", api_key="", model="", threshold=40,
    )
    assert attempted == [1, 2], "the loop must continue past a failing hotspot"
    assert result == {"candidates": 2, "processed": 1}


def test_shim_leaves_configured_ollama_endpoint_alone(monkeypatch):
    # The old truthy localhost default clobbered a configured OLLAMA_ENDPOINT
    # whenever a caller omitted the argument; None now means "leave it alone".
    import os

    import pipeline.llm_verifier as lv

    monkeypatch.setenv("OLLAMA_ENDPOINT", "http://host.docker.internal:11434")
    seen = {}

    def _chain(prompt, **kwargs):
        seen["ollama_env"] = os.environ.get("OLLAMA_ENDPOINT")
        return "t", "m"

    monkeypatch.setattr(lv, "call_llm", _chain)
    lv.call_llm_raw("p", endpoint="", api_key="", model="")
    assert seen["ollama_env"] == "http://host.docker.internal:11434"


def test_verify_hotspots_rolls_back_a_failed_hotspot(monkeypatch):
    # generate_sitrep writes and commits; a DB error partway through leaves the
    # transaction aborted. The loop reuses the same connection, so without a
    # rollback every remaining hotspot dies of InFailedSqlTransaction and the
    # run reports processed=0 while looking like N independent LLM failures.
    from unittest.mock import Mock

    import pipeline.llm_verifier as lv

    conn = Mock()
    calls = []

    def _sitrep(_conn, hid, **kwargs):
        calls.append(("sitrep", hid))
        if hid == 1:
            raise RuntimeError("current transaction is aborted")
        return 99, "deepseek:m"

    conn.rollback.side_effect = lambda: calls.append(("rollback", None))

    monkeypatch.setattr(lv, "generate_sitrep", _sitrep)
    monkeypatch.setattr(lv.LLMRepository, "candidate_hotspots",
                        lambda self, threshold: [1, 2])

    result = lv.verify_hotspots_with_llm(
        conn, endpoint="", api_key="", model="", threshold=40,
    )
    assert calls == [("sitrep", 1), ("rollback", None), ("sitrep", 2)], (
        "the rollback must land between the failing hotspot and the next one"
    )
    assert result == {"candidates": 2, "processed": 1}


def test_verify_hotspots_survives_a_failing_rollback(monkeypatch):
    # A connection dead enough that rollback() itself raises must not turn a
    # per-hotspot failure back into a run-ending one.
    from unittest.mock import Mock

    import pipeline.llm_verifier as lv

    conn = Mock()
    conn.rollback.side_effect = RuntimeError("connection already closed")
    attempted = []

    def _sitrep(_conn, hid, **kwargs):
        attempted.append(hid)
        raise RuntimeError("boom")

    monkeypatch.setattr(lv, "generate_sitrep", _sitrep)
    monkeypatch.setattr(lv.LLMRepository, "candidate_hotspots",
                        lambda self, threshold: [1, 2])

    result = lv.verify_hotspots_with_llm(
        conn, endpoint="", api_key="", model="", threshold=40,
    )
    assert attempted == [1, 2]
    assert result == {"candidates": 2, "processed": 0}


# FR-11 accepts the citation on either side of the terminal punctuation. Every
# case below is a real llm-worker rejection from 2026-08-27, where a fully
# cited SITREP was discarded purely for putting "[N]" after the full stop.
def test_validate_citations_accepts_citation_after_the_full_stop():
    from pipeline.llm_verifier import validate_citations
    validate_citations(
        "Verified claims indicate a significant flash flood event in Nepal "
        "with multiple fatalities and injuries.[3]"
    )


def test_validate_citations_accepts_trailing_dispute_pair():
    from pipeline.llm_verifier import validate_citations
    validate_citations(
        "Verified claims indicate escalating trade tensions between the US "
        "and Canada.[2][3]"
    )


def test_trailing_citation_still_splits_multiple_sentences():
    # "escorts.[2] US Democrats..." has no whitespace directly after the
    # period, so the pre-fix splitter saw one sentence, not two, and the whole
    # summary failed as a single uncited unit.
    from pipeline.llm_verifier import validate_citations
    validate_citations(
        "Israeli forces stormed a site with military escorts.[2] "
        "US Democrats called on Netanyahu to stop West Bank settler violence.[1]"
    )


def test_trailing_citation_does_not_excuse_an_uncited_neighbour():
    from pipeline.llm_verifier import validate_citations
    with pytest.raises(ValueError, match="Artillery deployed"):
        validate_citations(
            "Forces advanced 5km.[1] Artillery deployed."
        )


def test_trailing_triple_index_stays_invalid():
    # Only the first two indices are canonicalised, so FR-23's "exactly two"
    # rule survives in the trailing form as well.
    from pipeline.llm_verifier import validate_citations
    with pytest.raises(ValueError):
        validate_citations("Sources disagree.[1][2][3]")


def test_both_citation_orders_may_be_mixed_in_one_summary():
    from pipeline.llm_verifier import validate_citations
    validate_citations(
        "Forces advanced 5km [1]. Artillery deployed.[2] "
        "Sources disagree on casualties [3][4]."
    )


def test_uncited_boilerplate_is_still_rejected():
    # The other live failure shape: the model had nothing to report and
    # emitted a bare sentence with no citation at all. Still invalid.
    from pipeline.llm_verifier import validate_citations
    with pytest.raises(ValueError, match="No factual conflicts detected"):
        validate_citations("No factual conflicts detected regarding the provided information")
