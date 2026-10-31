"""A damaged evolvable core must still yield a framework error trajectory."""

import asyncio
import time

import pytest

from flashrsi.agents import Codex
from flashrsi.agents.codex import _python
from flashrsi.agents.codex.python_core.loop import close_session


@pytest.fixture
def source(tmp_path):
    (tmp_path / "components.yaml").write_text("code: [python_core/**]\n")
    (tmp_path / "python_core").mkdir()
    (tmp_path / "python_core/__init__.py").write_text("")
    return tmp_path


def agent(source, **options):
    return Codex(
        {
            "source_dir": source,
            "llm": {"model_name": "gpt-5", "api_key": "local-test-key"},
            **options,
        }
    )


@pytest.mark.parametrize(
    "change",
    [
        {"usage": "bad"},
        {"usage": {"input_tokens": "bad"}},
        {"output": 42},
        {"error_message": ["bad"]},
    ],
)
def test_invalid_completion_becomes_error_trajectory(source, change):
    payload = {"status": "finished", "output": "answer", "usage": {}, **change}
    (source / "python_core/loop.py").write_text(
        f"async def run_session(request, emit):\n    return {payload!r}\n"
    )
    result = asyncio.run(agent(source).run("Do not contact a model."))
    assert result.status == "error"
    assert "Invalid Python Codex completion" in result.error_message
    assert not result.output and not result.usage


def test_expired_preparation_does_not_start_a_process(source, monkeypatch):
    (source / "python_core/loop.py").write_text("")
    original = _python.shutil.copytree

    def copy(*args, **kwargs):
        time.sleep(0.03)
        return original(*args, **kwargs)

    async def spawn(*args, **kwargs):
        pytest.fail("An expired call must not spawn the selected core")

    monkeypatch.setattr(_python.shutil, "copytree", copy)
    monkeypatch.setattr(_python.asyncio, "create_subprocess_exec", spawn)
    result = asyncio.run(agent(source, timeout=0.01).run("No process."))
    assert result.status == "error" and "timed out" in result.error_message


def test_cleanup_error_does_not_skip_other_actors():
    async def scenario():
        closed = []

        class Actor:
            def __init__(self, name):
                self.name = name

            async def close(self):
                closed.append(self.name)
                if self.name == "resources":
                    raise RuntimeError("resource closer failed")

        cache = {name: Actor(name) for name in ("subagents", "resources", "router")}
        with pytest.raises(RuntimeError, match="resource closer"):
            await close_session(cache)
        assert closed == ["subagents", "resources", "router"]
        assert cache == {}

    asyncio.run(scenario())
