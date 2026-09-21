"""Run an existing FlashRSI Agent inside one native tau2 simulation.

tau2 owns the conversation loop, the simulated customer, the tool
implementations, the database and the reward. This integration only bridges
two directions: a FlashRSI Agent is presented to tau2 as one of its agents,
and the resulting SimulationRun is translated back into a Trajectory.

The Agent speaks through text, so tau2's tool schemas are rendered into the
prompt and a ``TOOL: {...}`` line in the reply becomes a tau2 tool call. This
keeps every harness usable without a native tool-calling interface.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import threading
import uuid
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import replace
from pathlib import Path

try:
    from tau2.agent.base_agent import HalfDuplexAgent
    from tau2.data_model.message import AssistantMessage, ToolCall
    from tau2.registry import registry
    from tau2.run import TextRunConfig, run_single_task
except ImportError as exc:
    raise ImportError("Install flashrsi-lite[tau2] for tau3 Banking execution") from exc

from flashrsi._records import _config_record, _redact, _secrets
from flashrsi.core import Trajectory

_AGENT_NAME = "flashrsi-lite"
_DOMAIN = "banking_knowledge"
# tau2 builds the agent through a registered factory, which receives no
# reference to the caller; this carries the running Agent into it.
_CURRENT: ContextVar[dict] = ContextVar("tau2_agent")
_PREFIX = "TOOL:"
_PROTOCOL = (
    f"Reply with one line starting with {_PREFIX} followed by JSON "
    '{"name": ..., "arguments": {...}} to call a tool. Any other reply is '
    "spoken to the customer."
)


def bind(agent, user_simulator: Mapping) -> None:
    """Connect an Agent to tau2; CLI runs do this in the runner.

    The simulated customer is played by its own model, configured under
    ``benchmark.user_simulator.llm``. It must never share the evolution
    worker's configuration: the worker edits the Agent being measured.
    """
    llm = dict((user_simulator or {}).get("llm") or {})
    model = llm.get("model_name")
    if not isinstance(model, str) or not model.strip():
        raise ValueError(
            "tau3 Banking needs its own user simulator model; set "
            "benchmark.user_simulator.llm.model_name"
        )

    async def run(target, task):
        return await _run(target, task, llm)

    agent._env_runner = run


async def _run(agent, task, simulator: Mapping) -> Trajectory:
    """The caller's rollout has already pinned its Snapshot and configuration."""
    config = copy.deepcopy(agent.config)
    secrets = sorted(
        set(_secrets(config) + _secrets(simulator) + _secrets(os.environ)),
        key=len,
        reverse=True,
    )
    record = {
        "type": "RunConfig",
        "config": _config_record(config),
        "snapshot_id": agent.snapshot.id,
    }
    event = {
        "type": "Tau2Simulator",
        "task_id": task.task_id,
        "task_checksum": task.metadata["task_checksum"],
    }
    trajectory = Trajectory(messages=(record,))
    try:
        domain = Path(task.env)
        if not (domain / "db.json").is_file():
            raise ValueError(f"tau3 Banking task has no domain directory: {domain}")
        run = await asyncio.to_thread(_simulate, agent, task, domain, simulator, config)
        reward = run.reward_info.reward if run.reward_info is not None else None
        if reward is None:
            raise ValueError("tau2 simulation ended without a reward")
        event["reward"] = reward
        event["termination_reason"] = str(run.termination_reason)
        trajectory = Trajectory(
            status="finished",
            output=_last_reply(run),
            messages=(record, *(_message(item) for item in run.messages)),
            usage={"agent_cost": run.agent_cost, "user_cost": run.user_cost},
        )
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        event["error"] = error
        trajectory = replace(trajectory, status="error", error_message=error)
    return replace(
        trajectory,
        output=_redact(trajectory.output, secrets),
        messages=_redact((*trajectory.messages, event), secrets),
        usage=_redact(trajectory.usage, secrets),
        error_message=_redact(trajectory.error_message, secrets),
    )


def _simulate(agent, task, domain, simulator, config):
    """Run tau2's own loop on a worker thread, with our Agent inside it."""
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    # tau2 resolves the domain from its data directory, so point it at the
    # verified copy this Task came from rather than the installed package.
    previous = os.environ.get("TAU2_DATA_DIR")
    os.environ["TAU2_DATA_DIR"] = str(domain.parents[2])
    _register_once()
    token = _CURRENT.set({"agent": agent, "loop": loop})
    try:
        return run_single_task(
            TextRunConfig(
                domain=_DOMAIN,
                agent=_AGENT_NAME,
                user="user_simulator",
                llm_user=simulator["model_name"],
                llm_args_user=_llm_args(simulator),
                max_steps=config.get("max_steps", 30),
                retrieval_config=task.metadata["variant"],
            ),
            _native_task(domain, task),
        )
    finally:
        _CURRENT.reset(token)
        if previous is None:
            os.environ.pop("TAU2_DATA_DIR", None)
        else:
            os.environ["TAU2_DATA_DIR"] = previous
        loop.call_soon_threadsafe(loop.stop)
        thread.join()
        loop.close()


def _register_once() -> None:
    """tau2 keeps factories by name and has no API to replace one, so register
    a single factory that reads whichever Agent is running this task."""
    if _AGENT_NAME not in registry.get_agents():
        registry.register_agent_factory(
            lambda tools, domain_policy, **kwargs: _AgentBridge(
                tools, domain_policy, **_CURRENT.get()
            ),
            _AGENT_NAME,
        )


def _llm_args(simulator: Mapping) -> dict:
    """Pass connection details through under the names litellm expects."""
    names = {"api_key": "api_key", "base_url": "api_base", "max_tokens": "max_tokens"}
    return {
        target: simulator[source]
        for source, target in names.items()
        if simulator.get(source) is not None
    }


def _native_task(domain: Path, task):
    from tau2.data_model.tasks import Task as NativeTask

    path = domain / task.metadata["task_path"]
    return NativeTask.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _last_reply(run) -> str:
    for message in reversed(run.messages):
        if message.role == "assistant" and message.content:
            return message.content
    return ""


def _message(item) -> dict:
    return {
        "type": type(item).__name__,
        **item.model_dump(mode="json", exclude_none=True),
    }


class _AgentBridge(HalfDuplexAgent):
    """Present a FlashRSI Agent to tau2 as one of its turn-based agents."""

    def __init__(self, tools, domain_policy, *, agent, loop):
        super().__init__(tools, domain_policy)
        self._agent = agent
        self._loop = loop
        self._prompt = "\n\n".join(
            (
                domain_policy,
                "## Tools",
                *(tool.to_str() for tool in tools),
                _PROTOCOL,
            )
        )

    def get_init_state(self, message_history=None):
        return list(message_history or ())

    def generate_next_message(self, message, state):
        """tau2 drives this synchronously, so hand the turn to the Agent's loop."""
        state = [*state, message]
        prompt = "\n\n".join(
            [self._prompt, "## Conversation", *(_turn(item) for item in state)]
        )
        trajectory = asyncio.run_coroutine_threadsafe(
            self._agent.run(prompt), self._loop
        ).result()
        if trajectory.status != "finished":
            raise RuntimeError(trajectory.error_message or "agent run failed")
        reply = _reply(trajectory.output)
        return reply, [*state, reply]


def _turn(message) -> str:
    content = getattr(message, "content", None) or ""
    calls = getattr(message, "tool_calls", None) or ()
    for call in calls:
        content = f"{content}\n{_PREFIX} {json.dumps({'name': call.name, 'arguments': call.arguments})}"
    return f"{message.role}: {content.strip()}"


def _reply(output: str) -> AssistantMessage:
    """A parsable TOOL line is a tool call; anything else is spoken."""
    text = output.strip()
    if not text.startswith(_PREFIX):
        return AssistantMessage(role="assistant", content=output)
    try:
        value = json.loads(text[len(_PREFIX) :].split("\n", 1)[0])
        name, arguments = value["name"], value.get("arguments", {})
        if not isinstance(name, str) or not isinstance(arguments, dict):
            raise ValueError("tool call needs a name and object arguments")
    except (ValueError, KeyError, TypeError):
        # Report the malformed attempt instead of silently speaking it.
        return AssistantMessage(
            role="assistant",
            content=f"[unparsable tool call, treated as speech] {output}",
        )
    return AssistantMessage(
        role="assistant",
        content=None,
        tool_calls=[
            ToolCall(
                id=f"call_{uuid.uuid4().hex[:8]}",
                name=name,
                arguments=arguments,
                requestor="assistant",
            )
        ],
    )
