"""Fixed native/Python differential regressions for delegated task mechanisms."""

from __future__ import annotations

import asyncio
import copy
import json
import shlex
import sys

import pytest
from test_codex_core_parity import _events, _normalize, _responses_server
from test_codex_core_parity import parity_source as parity_source
from test_codex_core_parity import upstream_codex as upstream_codex

from flashrsi.agents import Codex

MARKER = "ONLY_CHILD_DEVELOPER_MUST_BE_INHERITED_8739"


def tool(name, args, tag, v2=False):
    payload = _events(call=(name, args), response_id=tag)
    if v2:
        payload = payload.replace(
            json.dumps({"name": name})[1:-1].encode(),
            json.dumps({"name": name, "namespace": "collaboration"})[1:-1].encode(),
        )
    elif name in {"spawn_agent", "wait_agent"}:
        payload = payload.replace(
            json.dumps({"name": name})[1:-1].encode(),
            json.dumps({"name": name, "namespace": "multi_agent_v1"})[1:-1].encode(),
        )
    return 200, payload


def cell(source, tag):
    item = {
        "type": "custom_tool_call",
        "id": "ct_" + tag,
        "call_id": "cell_" + tag,
        "name": "exec",
        "input": source,
    }
    payload = [
        {"type": "response.created", "response": {"id": tag}},
        {"type": "response.output_item.done", "item": item},
        {
            "type": "response.completed",
            "response": {
                "id": tag,
                "usage": {"input_tokens": 20, "output_tokens": 3, "total_tokens": 23},
            },
        },
    ]
    return 200, b"".join(
        ("data: " + json.dumps(value) + "\n\n").encode() for value in payload
    )


def messages(items, recipient=None, kind=None):
    return [
        item
        for item in items
        if item.get("type") == "agent_message"
        and (recipient is None or item.get("recipient") == recipient)
        and (
            kind is None
            or any(
                entry.get("text", "").startswith("Message Type: " + kind + "\n")
                for entry in item.get("content", [])
            )
        )
    ]


def output_for(items, call_id):
    return next(
        (
            item.get("output", "")
            for item in reversed(items)
            if item.get("type") == "function_call_output"
            and item.get("call_id") == call_id
        ),
        None,
    )


class _DelegatedTask:
    def __init__(self, case, replay, task):
        self.case, self.replay, self.task = case, replay, task
        self.counts = {}
        self.observations = {}
        self.initial_requests = {}

    def __bool__(self):
        return True

    def pop(self, _index):
        body = copy.deepcopy(self.replay.requests[-1]["body"])
        items = body["input"]
        if self.case == "v1_capacity":
            return self.capacity(body, items)
        tasks = messages(items, kind="NEW_TASK")
        path = tasks[-1]["recipient"] if tasks else "/root"
        self.initial_requests.setdefault(path, body)
        self.counts[path] = self.counts.get(path, 0) + 1
        assert self.counts[path] < 35, (self.case, path, self.counts)
        if self.case == "v2_depth":
            return self.depth(path, items)
        return self.developer(path, items)

    def capacity(self, body, items):
        child = next(
            (
                entry["text"]
                for item in items
                if item.get("type") == "message" and item.get("role") == "user"
                for entry in item.get("content", [])
                if entry.get("type") == "input_text"
                and entry.get("text", "").startswith("CAPACITY_CHILD_")
            ),
            None,
        )
        self.initial_requests.setdefault(child or "/root", body)
        if child:
            self.counts[child] = self.counts.get(child, 0) + 1
            if self.counts[child] == 1:
                command = (
                    "printf "
                    + shlex.quote(child)
                    + " > "
                    + shlex.quote(str(self.task / (child + ".txt")))
                )
                return tool("shell_command", {"command": command}, child + "_write")
            return 200, _events(child + "_DONE", response_id=child + "_done")
        index = self.counts["/root"] = self.counts.get("/root", 0) + 1
        if index == 1:
            return tool("spawn_agent", {"message": "CAPACITY_CHILD_ONE"}, "spawn_one")
        if index == 2:
            first = json.loads(output_for(items, "call_spawn_one"))["agent_id"]
            return tool(
                "wait_agent", {"targets": [first], "timeout_ms": 10000}, "wait_one"
            )
        if index == 3:
            return tool("spawn_agent", {"message": "CAPACITY_CHILD_TWO"}, "spawn_two")
        second = output_for(items, "call_spawn_two")
        self.observations["second_spawn_feedback"] = second
        ids = []
        for call_id in ("call_spawn_one", "call_spawn_two"):
            value = output_for(items, call_id)
            if value:
                try:
                    decoded = json.loads(value)
                    if isinstance(decoded, dict) and decoded.get("agent_id"):
                        ids.append(decoded["agent_id"])
                except (TypeError, ValueError):
                    pass
        second_exists = (self.task / "CAPACITY_CHILD_TWO.txt").exists()
        if len(ids) > 1 and not second_exists:
            assert index < 15
            return tool(
                "wait_agent",
                {"targets": ids, "timeout_ms": 10000},
                "wait_capacity_" + str(index),
            )
        return 200, _events(
            "SECOND_CHILD_EXECUTED" if second_exists else "SECOND_CHILD_REJECTED",
            response_id="capacity_final",
        )

    def depth(self, path, items):
        count = self.counts[path]
        if path == "/root/worker/grand":
            if count == 1:
                command = "printf GRANDCHILD_EXECUTED > grandchild-proof.txt"
                return cell(
                    "text(await tools.exec_command({cmd:"
                    + json.dumps(command)
                    + "}));",
                    "grand_write",
                )
            return 200, _events("GRANDCHILD_DONE", response_id="grand_done")
        if path == "/root/worker":
            if count == 1:
                return tool(
                    "spawn_agent",
                    {
                        "task_name": "grand",
                        "message": "Write delegated evidence.",
                        "fork_turns": "none",
                    },
                    "spawn_grand",
                    True,
                )
            result = output_for(items, "call_spawn_grand")
            self.observations["grandchild_spawn_feedback"] = result
            if result and "task_name" not in str(result):
                return 200, _events(
                    "GRANDCHILD_REJECTED", response_id="worker_rejected"
                )
            if messages(items, recipient=path, kind="FINAL_ANSWER"):
                return 200, _events("WORKER_VERIFIED_GRAND", response_id="worker_done")
            return tool(
                "wait_agent", {"timeout_ms": 1000}, "worker_wait_" + str(count), True
            )
        if count == 1:
            return tool(
                "spawn_agent",
                {
                    "task_name": "worker",
                    "message": "Delegate the proof file creation to a grandchild.",
                    "fork_turns": "none",
                },
                "spawn_worker",
                True,
            )
        if messages(items, recipient="/root", kind="FINAL_ANSWER"):
            return 200, _events(
                "NESTED_TASK_EXECUTED"
                if (self.task / "grandchild-proof.txt").exists()
                else "NESTED_TASK_REJECTED",
                response_id="root_done",
            )
        return tool("wait_agent", {"timeout_ms": 1000}, "root_wait_" + str(count), True)

    def developer(self, path, items):
        count = self.counts[path]
        if path == "/root/worker":
            if count == 1:
                found = any(
                    MARKER in entry.get("text", "")
                    for item in items
                    if item.get("role") == "developer"
                    for entry in item.get("content", [])
                )
                self.observations["child_developer_override_present"] = found
                value = (
                    "CHILD_DEVELOPER_PRESENT" if found else "CHILD_DEVELOPER_MISSING"
                )
                return tool(
                    "shell_command",
                    {"command": "printf " + value + " > child-developer-proof.txt"},
                    "directive_write",
                )
            return 200, _events("CHILD_COMPLETED", response_id="child_done")
        if count == 1:
            return tool(
                "spawn_agent",
                {
                    "task_name": "worker",
                    "message": "Perform the delegated verification.",
                    "fork_turns": "all",
                },
                "spawn_worker",
                True,
            )
        if messages(items, recipient="/root", kind="FINAL_ANSWER"):
            return 200, _events(
                (self.task / "child-developer-proof.txt").read_text(),
                response_id="root_done",
            )
        return tool("wait_agent", {"timeout_ms": 1000}, "root_wait_" + str(count), True)


@pytest.mark.parametrize(
    "case,parent_instructions",
    [
        ("v1_capacity", None),
        ("v2_developer", None),
        ("v2_developer", "PARENT_DEVELOPER_REPLACED_IN_FORK"),
        ("v2_depth", None),
    ],
)
def test_delegated_task_mechanisms_match_pinned_native(
    case, parent_instructions, parity_source, upstream_codex, tmp_path
):
    # Native full forks need an isolated rollout store; the production adapter
    # otherwise requests --ephemeral. The fixture pins the binary to 0.147.0.
    wrapper = tmp_path / "native-with-rollouts"
    wrapper.write_text(
        f"#!{sys.executable}\nimport os,sys\nbinary={upstream_codex!r}\nos.execv(binary,[binary,*[arg for arg in sys.argv[1:] if arg!='--ephemeral']])\n"
    )
    wrapper.chmod(0o755)
    settings = "[features]\nplugins=false\nremote_plugin=false\nshell_snapshot=false\ngoals=false\n"
    if parent_instructions is not None:
        settings = (
            "developer_instructions="
            + json.dumps(parent_instructions)
            + "\n"
            + settings
        )
    if case == "v1_capacity":
        settings += (
            "unified_exec=false\n[agents]\nmax_concurrent_threads_per_session=1\n"
        )
    else:
        settings += "unified_exec=" + ("true" if case == "v2_depth" else "false")
        settings += "\n[features.multi_agent_v2]\nenabled=true\nmin_wait_timeout_ms=0\n"
        if case == "v2_developer":
            settings += "subagent_developer_instructions=" + json.dumps(MARKER) + "\n"
    (parity_source / "config.toml").write_text(settings)
    task = tmp_path / "task"
    task.mkdir()
    observations = []
    with _responses_server() as replay:
        for engine in (str(wrapper), None):
            for path in task.glob("*.txt"):
                path.unlink()
            replay.reset([])
            scenario = _DelegatedTask(case, replay, task)
            replay.steps = scenario
            config = {
                "source_dir": parity_source,
                "sandbox": "danger-full-access",
                "timeout": 40,
                "llm": {
                    "model_name": "gpt-5.6-sol" if case == "v2_depth" else "gpt-5",
                    "api_key": "local-fidelity-test-key",
                    "base_url": replay.base_url,
                },
            }
            if engine:
                config["cli_path"] = engine
            result = asyncio.run(
                Codex(config).run(
                    "Perform the requested local delegated task.", working_dir=task
                )
            )
            assert result.status == "finished", result.error_message
            assert not replay.errors, replay.errors
            files = {path.name: path.read_text() for path in task.glob("*.txt")}
            label = "native" if engine else "python"
            (tmp_path / f"{case}-{label}-requests.json").write_text(
                json.dumps(replay.requests, indent=2)
            )
            if case == "v1_capacity":
                assert result.output == "SECOND_CHILD_REJECTED"
                assert files == {"CAPACITY_CHILD_ONE.txt": "CAPACITY_CHILD_ONE"}
                assert (
                    scenario.observations["second_spawn_feedback"]
                    == "collab spawn failed: agent thread limit reached"
                )
            elif case == "v2_developer":
                assert result.output == "CHILD_DEVELOPER_PRESENT"
                assert files == {"child-developer-proof.txt": "CHILD_DEVELOPER_PRESENT"}
                assert scenario.observations["child_developer_override_present"]
            else:
                assert result.output == "NESTED_TASK_EXECUTED"
                assert files == {"grandchild-proof.txt": "GRANDCHILD_EXECUTED"}
                assert json.loads(
                    scenario.observations["grandchild_spawn_feedback"]
                ) == {"task_name": "/root/worker/grand"}
            observations.append(
                _normalize(
                    {
                        "output": result.output,
                        "files": files,
                        "initial_requests": scenario.initial_requests,
                        "feedback": scenario.observations,
                    },
                    tmp_path,
                )
            )
    # Compare all fields of the initial model request at every delegation
    # level, in addition to feedback and files made by actual shell tools.
    assert observations[0] == observations[1]
