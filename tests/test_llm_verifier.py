from unittest import mock

import pytest
import requests

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
    assert "must end with a citation bracket" in prompt
    assert "https://a.com/1" in prompt
    assert "https://b.com/2" in prompt


def test_validate_summary_requires_citation_per_sentence() -> None:
    valid = "Forces advanced 5km [1]. Fire was reported near the border [2]."
    invalid = "Forces advanced 5km. Fire was reported near the border [2]."
    assert llm_verifier.validate_citations(valid) is True
    assert llm_verifier.validate_citations(invalid) is False


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
    monkeypatch.setattr("pipeline.llm_verifier.requests.post", post_mock)
    monkeypatch.setattr("pipeline.llm_verifier.time.sleep", mock.Mock())

    result = llm_verifier.call_nim_api(
        prompt="test",
        endpoint="https://example.com/v1/chat/completions",
        api_key="secret",
        model="meta/llama-3.1-70b-instruct",
    )
    assert result["conflict_detected"] is False
    assert post_mock.call_count == 2


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
