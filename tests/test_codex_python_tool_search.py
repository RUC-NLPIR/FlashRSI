from __future__ import annotations

import asyncio
import json
import shutil
import struct
from pathlib import Path

import pytest
from codex_test_support import _events, _responses_server

from flashrsi.agents.codex.python_core.models import Model
from flashrsi.agents.codex.python_core.subagents import Subagents
from flashrsi.agents.codex.python_core.tool_search import (
    BM25,
    loadable_spec,
    search_spec,
    token_index,
    tokenize,
)
from flashrsi.agents.codex.python_core.tools import ToolRouter, function


def router(tmp_path, model="gpt-5.4", settings=None):
    settings = {"sandbox_mode": "danger-full-access", **(settings or {})}
    resolved = Model(model, settings)
    return ToolRouter(settings, tmp_path, resolved, lambda event: None)


def search_call(arguments):
    return {
        "type": "tool_search_call",
        "execution": "client",
        "call_id": "search",
        "arguments": arguments,
    }


def test_tokenization_hash_collisions_and_bm25_match_pinned_native_fixtures():
    fixture = json.loads(
        (Path(__file__).with_name("fixtures") / "codex_tool_search.json").read_text()
    )
    for item in fixture["tokenization"]:
        assert tokenize(item["text"]) == item["tokens"]
    for item in fixture["hashes"]:
        assert token_index(item["text"]) == item["hash32"]
    for case in fixture["search"]:
        engine = BM25(case["documents"])
        for query, expected in zip(case["queries"], case["results"], strict=True):
            actual = engine.search(query, 100)
            assert {index for index, _ in actual} == {index for index, _ in expected}
            assert [score for _, score in actual] == sorted(
                (score for _, score in actual), reverse=True
            )
            # Rust deliberately leaves equal-score order unspecified.
            assert {index: struct.pack("f", score) for index, score in actual} == {
                index: struct.pack("f", score) for index, score in expected
            }


def test_model_capability_defers_v1_and_preserves_dispatch(tmp_path):
    async def scenario():
        async def session(request, emit):
            return {"status": "finished", "output": "done", "history": []}

        r = router(tmp_path)
        settings = {"sandbox_mode": "danger-full-access", "_thread_id": "root"}
        manager = Subagents(
            r,
            {
                "settings": settings,
                "home": str(tmp_path),
                "cwd": str(tmp_path),
                "llm": {"model_name": "gpt-5.4"},
            },
            lambda event: None,
            session,
        )
        assert r.search_enabled
        assert not any(spec.get("name") == "multi_agent_v1" for spec in r.specs)
        discovery = next(spec for spec in r.specs if spec["type"] == "tool_search")
        assert discovery == search_spec(
            [
                {
                    "name": "Multi-agent tools",
                    "description": "Spawn and manage sub-agents.",
                }
            ]
        )
        output = await r.execute(
            search_call({"query": "fork model reasoning", "limit": 1})
        )
        assert (
            output["type"] == "tool_search_output"
            and output["status"] == "completed"
            and output["execution"] == "client"
        )
        namespace = output["tools"][0]
        assert namespace["name"] == "multi_agent_v1"
        assert [tool["name"] for tool in namespace["tools"]] == ["spawn_agent"]
        assert namespace["tools"][0]["defer_loading"] is True
        spawned = await r.execute(
            {
                "type": "function_call",
                "namespace": "multi_agent_v1",
                "name": "spawn_agent",
                "call_id": "spawn",
                "arguments": '{"message":"hello"}',
            }
        )
        assert "agent_id" in json.loads(spawned["output"])
        await manager.close()
        await r.close()

        for model, overrides in [
            ("gpt-5", {}),
            ("gpt-5.4", {"_provider_capabilities": {"namespace_tools": False}}),
        ]:
            r = router(tmp_path, model, overrides)
            manager = Subagents(
                r,
                {
                    "settings": settings,
                    "home": str(tmp_path),
                    "cwd": str(tmp_path),
                    "llm": {"model_name": model},
                },
                lambda event: None,
                session,
            )
            assert not any(spec["type"] == "tool_search" for spec in r.specs)
            assert any(spec.get("name") == "multi_agent_v1" for spec in r.specs)
            await manager.close()
            await r.close()

    asyncio.run(scenario())


def test_search_source_budget_deduplication_and_loadable_namespace():
    source = search_spec(
        [
            {"name": "z", "description": None},
            {"name": "z", "description": "last"},
            {"name": "a", "description": "🦀" * 200000},
        ]
    )
    listing = (
        source["description"]
        .split("following sources:\n", 1)[1]
        .split("\nSome of the tools", 1)[0]
    )
    assert len(listing.encode()) <= 512 * 1024
    assert listing.startswith("- a: 🦀") and "\n- z" in listing
    assert (
        "- z: last"
        in search_spec(
            [{"name": "z", "description": None}, {"name": "z", "description": "last"}]
        )["description"]
    )
    assert "following sources" not in search_spec([], omit_sources=True)["description"]
    tool = function("sample", "test", {}, [])
    tool["output_schema"] = {"type": "string"}
    output = loadable_spec(tool)
    assert output["name"] == "functions" and output["description"] == ""
    assert output["tools"][0]["defer_loading"] is True
    assert "output_schema" not in output["tools"][0]
    assert "defer_loading" not in tool
    assert (
        loadable_spec(
            {
                "type": "namespace",
                "name": "mcp__example",
                "description": " ",
                "tools": [tool],
            }
        )["description"]
        == "Tools in the mcp__example namespace."
    )


def test_search_validation_empty_results_coalescing_and_resource_order(tmp_path):
    async def scenario():
        r = router(tmp_path)
        for name in ("first", "second"):
            r.register(
                "example." + name,
                {
                    "type": "namespace",
                    "name": "example",
                    "description": "Example",
                    "tools": [function(name, "", {}, [])],
                },
                lambda arguments: "ok",
                deferred=True,
                search_text="shared " + name,
            )
        for name in (
            "read_mcp_resource",
            "list_mcp_resource_templates",
            "list_mcp_resources",
        ):
            r.register(name, function(name, "", {}, []), lambda arguments: "ok")
        assert [spec.get("name") for spec in r.specs][:6] == [
            "exec_command",
            "write_stdin",
            "list_mcp_resources",
            "list_mcp_resource_templates",
            "read_mcp_resource",
            "update_plan",
        ]
        output = await r.execute(search_call({"query": "shared"}))
        assert len(output["tools"]) == 1
        assert {tool["name"] for tool in output["tools"][0]["tools"]} == {
            "first",
            "second",
        }
        assert (await r.execute(search_call({"query": "unmatched"})))["tools"] == []
        for arguments, expected in [
            ({"query": " "}, "query must not be empty"),
            ({"query": "x", "limit": 0}, "limit must be greater than zero"),
            ({}, "missing field `query`"),
            ({"query": "x", "limit": -1}, "nonnegative integer"),
        ]:
            assert expected in (await r.execute(search_call(arguments)))["output"]
        with pytest.raises(ValueError, match="unsupported payload"):
            await r.execute(
                {
                    "type": "function_call",
                    "name": "tool_search",
                    "call_id": "wrong",
                    "arguments": "{}",
                }
            )
        await r.close()

    asyncio.run(scenario())


def test_real_session_retains_discovered_tools_in_next_request(tmp_path):
    from flashrsi.agents.codex.python_core.loop import run_session

    shutil.copytree(
        Path(__file__).parents[1] / "flashrsi/agents/codex/python_core/resource_assets",
        tmp_path / "python_core/resource_assets",
    )
    item = {
        **search_call({"query": "fork model reasoning", "limit": 1}),
        "id": "tsc_search",
    }
    events = [
        {"type": "response.created", "response": {"id": "resp_search"}},
        {"type": "response.output_item.done", "item": item},
        {"type": "response.completed", "response": {"id": "resp_search"}},
    ]
    stream = "".join(
        f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
    ).encode()
    with _responses_server() as replay:
        replay.reset([(200, stream), (200, _events(text="DONE"))])
        result = asyncio.run(
            run_session(
                {
                    "home": str(tmp_path),
                    "cwd": str(tmp_path),
                    "prompt": "discover a worker",
                    "settings": {
                        "sandbox_mode": "danger-full-access",
                        "features": {"plugins": False},
                    },
                    "llm": {
                        "model_name": "gpt-5.4",
                        "api_key": "local-test-key",
                        "base_url": replay.base_url,
                    },
                    "environment": {},
                },
                lambda event: None,
            )
        )
        assert result["status"] == "finished" and result["output"] == "DONE"
        assert len(replay.requests) == 2 and not replay.errors and not replay.steps
        first, second = (request["body"] for request in replay.requests)
        assert any(spec["type"] == "tool_search" for spec in first["tools"])
        assert not any(spec.get("name") == "multi_agent_v1" for spec in first["tools"])
        output = next(
            item for item in second["input"] if item.get("type") == "tool_search_output"
        )
        assert output["tools"][0]["tools"][0]["name"] == "spawn_agent"
        assert output["tools"][0]["tools"][0]["defer_loading"] is True
