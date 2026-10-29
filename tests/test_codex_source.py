"""Execute selected Python core candidates and preserve Snapshot isolation."""

import asyncio
import json

from codex_test_support import _events, _responses_server
from codex_test_support import parity_source as parity_source

from flashrsi.agents import Codex
from flashrsi.core import Snapshot, Task


def test_snapshot_python_source_candidate_executes_and_roundtrips(
    parity_source, tmp_path
):
    relative = "python_core/loop.py"
    source_file = parity_source / relative
    original = source_file.read_bytes()
    marker = "PARITY_PYTHON_CORE_CANDIDATE:"
    declaration = 'output = last_message or ""'
    assert original.decode().count(declaration) == 1
    replacement = "output = " + json.dumps(marker) + ' + (last_message or "")'

    with _responses_server() as replay:
        agent = Codex(
            {
                "source_dir": parity_source,
                "llm": {
                    "model_name": "gpt-5",
                    "api_key": "local-parity-test-key",
                    "base_url": replay.base_url,
                },
                "sandbox": "danger-full-access",
                "timeout": 60,
            }
        )
        agent.set_scope({"code": "rw"})
        baseline = agent.snapshot
        assert baseline.files[relative].component == "code"
        with baseline.check_out() as directory:
            candidate_source = directory / relative
            candidate_source.write_text(
                original.decode().replace(declaration, replacement)
            )
            candidate = baseline.commit(directory)
        assert baseline.changed_paths(candidate) == (relative,)
        saved = tmp_path / "candidate.json"
        candidate.save(saved)
        restored = Snapshot.load(saved)
        assert restored.id == candidate.id

        async def request_instructions(snapshot=None):
            replay.reset([(200, _events())])
            task = Task("source-proof", "Return the scripted answer.")
            (result,) = await agent.rollout([task], snapshot=snapshot)
            assert result.status == "finished", result.error_message
            assert result.output in {"PARITY_ANSWER", marker + "PARITY_ANSWER"}
            assert not replay.errors and not replay.steps
            assert len(replay.requests) == 1
            return result.output

        assert marker not in asyncio.run(request_instructions())
        assert marker in asyncio.run(request_instructions(candidate))
        assert agent.snapshot.id == baseline.id
        assert marker not in asyncio.run(request_instructions())
        agent.update(restored)
        assert marker in asyncio.run(request_instructions())
        agent.update(baseline)
        assert marker not in asyncio.run(request_instructions())

        with baseline.check_out() as directory:
            (directory / relative).write_bytes(
                original + b"\nthis is invalid Python;\n"
            )
            invalid = baseline.commit(directory)
        replay.reset([(200, _events())])
        (failed,) = asyncio.run(
            agent.rollout(
                [Task("invalid-source", "Answer only if selected Python compiles.")],
                snapshot=invalid,
            )
        )
        assert failed.status == "error"
        assert "invalid syntax" in failed.error_message
        assert replay.requests == [], "Invalid Python must fail before calling a model"
        assert agent.snapshot.id == baseline.id
        assert marker not in asyncio.run(request_instructions())

    assert source_file.read_bytes() == original
    assert baseline.files[relative].content == original
    assert marker.encode() in restored.files[relative].content
