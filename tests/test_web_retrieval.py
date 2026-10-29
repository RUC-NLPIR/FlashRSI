"""Provider wire formats, credential boundaries and custom Judge provenance."""

import asyncio
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from flashrsi._records import _redact_config
from flashrsi.benchmarks.deepsearchqa import DeepSearchQA
from flashrsi.benchmarks.deepsearchqa._official import REVISION
from flashrsi.core import Trajectory
from flashrsi.integrations import _browsecomp_web as web
from flashrsi.integrations import _deepsearchqa_judge, _web_tools


def settings(**values):
    agent = SimpleNamespace(name="miniagent", config={"source_dir": "custom"})
    return _web_tools.settings(agent, {"retrieval": values}, "DeepSearchQA")


@pytest.mark.parametrize("provider", ["tavily", "serper", "json"])
def test_search_provider_wire_format(provider):
    config = settings(
        provider=provider, api_key="search-secret", url="https://search.example/"
    )
    item = {"title": "Title", "url": "https://example.org/", "content": "snippet"}
    payload = {"results": [item]}
    if provider == "serper":
        payload = {
            "organic": [{"title": "Title", "link": item["url"], "snippet": "snippet"}]
        }
    with patch.object(web, "build_opener") as build:
        build.return_value.open.return_value.__enter__.return_value = io.BytesIO(
            json.dumps(payload).encode()
        )
        assert web.search(config, "query", 2) == {"results": [item]}
        request = build.return_value.open.call_args.args[0]
    body = json.loads(request.data)
    if provider == "serper":
        assert body == {"q": "query", "num": 2}
        assert request.get_header("X-api-key") == "search-secret"
        assert request.get_header("Authorization") is None
    else:
        assert body["query"] == "query"
        assert request.get_header("Authorization") == "Bearer search-secret"


def test_jina_uses_separate_credential_and_truncates():
    config = settings(
        provider="serper",
        api_key="search-secret",
        max_page_chars=5,
        reader={"provider": "jina", "api_key": "reader-secret"},
    )
    with patch.object(web, "_public_url"), patch.object(web, "build_opener") as build:
        build.return_value.open.return_value.__enter__.return_value = io.BytesIO(
            b"page content"
        )
        assert web.read(config, "https://example.org/") == {
            "url": "https://example.org/",
            "content": "page ",
            "truncated": True,
        }
        request = build.return_value.open.call_args.args[0]
        assert json.loads(request.data) == {"url": "https://example.org/"}
        assert request.get_header("Authorization") == "Bearer reader-secret"
        assert request.get_header("X-api-key") is None
    saved = _redact_config(config)
    assert saved["api_key"] is None
    assert saved["reader"]["api_key"] is None


@pytest.mark.parametrize(
    "values",
    [
        {"provider": "serper"},
        {"provider": "serper", "api_key": "x", "reader": {"provider": "jina"}},
        {"provider": "serper", "api_key": "x", "reader": {"provider": "unknown"}},
    ],
)
def test_invalid_provider_configuration(values):
    with pytest.raises(ValueError):
        settings(**values)


def test_provider_redirects_rejected():
    with pytest.raises(ValueError, match="redirects"):
        web._NoRedirect().redirect_request(
            None, None, 302, None, None, "https://other.example/"
        )


def test_jina_rejects_private_target_before_api_request():
    config = settings(
        provider="serper", api_key="x", reader={"provider": "jina", "api_key": "y"}
    )
    with (
        patch.object(
            web.socket, "getaddrinfo", return_value=[(2, 1, 6, "", ("127.0.0.1", 80))]
        ),
        patch.object(web, "build_opener") as build,
    ):
        with pytest.raises(ValueError, match="public address"):
            web.read(config, "http://private.example/")
        build.assert_not_called()


@pytest.mark.parametrize("finish", ["stop", "length"])
def test_custom_judge_keeps_pinned_protocol_and_usage(finish):
    rating = {
        "Answer Correctness": {
            "Explanation": "matched",
            "Correctness Details": {"answer": True},
            "Excessive Answers": [],
        }
    }
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=AsyncMock(
                    return_value=SimpleNamespace(
                        choices=[
                            SimpleNamespace(
                                finish_reason=finish,
                                message=SimpleNamespace(content=json.dumps(rating)),
                            )
                        ],
                        usage=SimpleNamespace(
                            model_dump=lambda **_: {"total_tokens": 12}
                        ),
                    )
                )
            )
        )
    )
    with patch("openai.AsyncOpenAI") as factory:
        factory.return_value.__aenter__ = AsyncMock(return_value=client)
        factory.return_value.__aexit__ = AsyncMock(return_value=False)
        call = _deepsearchqa_judge.judge(
            {"problem": "question", "answer": "answer", "answer_type": "Single Answer"},
            "prediction",
            {
                "provider": "openai",
                "timeout": 30,
                "llm": {
                    "model_name": "deepseek-flash",
                    "api_key": "judge-secret",
                    "base_url": "https://api.deepseek.com",
                },
            },
        )
        if finish == "length":
            with pytest.raises(ValueError, match="Incomplete"):
                asyncio.run(call)
        else:
            counts, usage = asyncio.run(call)
            assert counts == {
                "true_positives": 1,
                "false_positives": 0,
                "false_negatives": 0,
            }
            assert usage == {"total_tokens": 12}
        kwargs = client.chat.completions.create.call_args.kwargs
        assert kwargs["model"] == "deepseek-flash"
        assert "Correct Answer" in kwargs["messages"][0]["content"]


def test_custom_judge_provenance_must_match_configured_model(tmp_path):
    data = tmp_path / "records.json"
    data.write_text(
        json.dumps(
            [
                {
                    "problem": "q",
                    "answer": "a",
                    "answer_type": "Single Answer",
                    "problem_category": "test",
                }
            ]
        )
    )
    bench = DeepSearchQA(
        {
            "data_path": str(data),
            "split_counts": {"train": 1, "dev": 0, "test": 0},
            "judge": {"provider": "openai", "llm": {"model_name": "deepseek-flash"}},
        }
    )
    task = bench.load()["train"][0]
    event = {
        "type": "DeepSearchQAVerifier",
        "task_id": task.task_id,
        "task_checksum": task.metadata["task_checksum"],
        "judge_revision": REVISION,
        "judge_provider": "openai",
        "judge_model": "deepseek-flash",
        "judge_profile": "custom",
        "counts": {"true_positives": 1, "false_positives": 0, "false_negatives": 0},
    }
    assert (
        bench.grade((Trajectory(task=task, messages=(event,)),))[0].metrics["f1_score"]
        == 1
    )
    for changed in ({"judge_provider": "google"}, {"judge_model": "gemini-2.5-flash"}):
        with pytest.raises(ValueError, match="matching"):
            bench.grade((Trajectory(task=task, messages=({**event, **changed},)),))
