"""Pinned Codex v2 task paths, mailbox delivery, residency and turn lifecycle.

Ported from core/src/tools/handlers/multi_agents_v2*, agent/control/{spawn,
residency,execution}.rs, protocol/src/agent_path.rs and session_prefix.rs at
rust-v0.147.0 (be6e8eac). Child turns use the same Python session loop.
"""

from __future__ import annotations

import asyncio
import copy
import re
import uuid

from .shell import ToolError, truncate
from .subagents import (
    Agent,
    Subagents,
    _assets,
    _format_models,
    _role_description,
    fork_history,
)
from .tools import function, schema


def configuration(settings):
    feature = settings.get("features", {}).get("multi_agent_v2", {})
    configured = feature if isinstance(feature, dict) else {}
    # ``multi_agent_v2`` is also the resolved config shape used by sessions.
    configured = {**settings.get("multi_agent_v2", {}), **configured}
    maximum = settings.get("agents", {}).get("max_concurrent_threads_per_session")
    defaults = {
        "max_concurrent_threads_per_session": 4 if maximum is None else maximum + 1,
        "min_wait_timeout_ms": 10000,
        "max_wait_timeout_ms": 3600000,
        "default_wait_timeout_ms": 30000,
        "tool_namespace": "collaboration",
        "hide_spawn_agent_metadata": True,
        "expose_spawn_agent_model_overrides": True,
        "wait_agent_enabled": True,
        "non_code_mode_only": True,
    }
    result = {**defaults, **configured}
    assets = _assets("subagents_v2.json")
    for name in ("root_agent", "subagent"):
        key = name + "_usage_hint_text"
        text = assets[key] + "\n" + assets["shared_usage_hint_text"] + "\n"
        if result["wait_agent_enabled"]:
            text += assets["wait_agent_usage_hint_text"] + "\n\n"
        maximum = result["max_concurrent_threads_per_session"]
        text += f"There are {maximum} available concurrency slots, meaning that up to {maximum} agents can be active at once, including you."
        if result["expose_spawn_agent_model_overrides"]:
            text += "\n\n" + assets["model_override_usage_hint_text"]
        result.setdefault(key, text)
        if result[key] == "":
            result[key] = None
    if result["max_concurrent_threads_per_session"] < 1:
        raise ValueError(
            "features.multi_agent_v2.max_concurrent_threads_per_session must be at least 1"
        )
    for key in (
        "min_wait_timeout_ms",
        "max_wait_timeout_ms",
        "default_wait_timeout_ms",
    ):
        label = f"features.multi_agent_v2.{key}"
        if type(result[key]) is not int:
            raise ValueError(f"{label} must be an integer")
        if result[key] < 0:
            raise ValueError(f"{label} must be at least 0")
        if result[key] > 3600000:
            raise ValueError(f"{label} must be at most 3600000")
    for left, right, operator, phrase in (
        ("min", "max", lambda a, b: a > b, "at most"),
        ("default", "min", lambda a, b: a < b, "at least"),
        ("default", "max", lambda a, b: a > b, "at most"),
    ):
        if operator(
            result[left + "_wait_timeout_ms"], result[right + "_wait_timeout_ms"]
        ):
            raise ValueError(
                f"features.multi_agent_v2.{left}_wait_timeout_ms must be {phrase} features.multi_agent_v2.{right}_wait_timeout_ms"
            )
    namespace = result["tool_namespace"]
    if namespace is not None:
        label = "features.multi_agent_v2.tool_namespace"
        if not namespace:
            raise ValueError(f"{label} must not be empty")
        if namespace.strip() != namespace:
            raise ValueError(f"{label} must not have leading or trailing whitespace")
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", namespace):
            raise ValueError(f"{label} must match ^[a-zA-Z0-9_-]+$")
        if len(namespace) > 64:
            raise ValueError(f"{label} must be at most 64 characters")
        reserved = {
            "api_tool",
            "browser",
            "computer",
            "container",
            "file_search",
            "functions",
            "image_gen",
            "multi_tool_use",
            "python",
            "python_user_visible",
            "submodel_delegator",
            "terminal",
            "tool_search",
            "web",
            "mcp",
        }
        if namespace in reserved or namespace.startswith("mcp__"):
            raise ValueError(f"{label} uses a reserved namespace: {namespace}")
    return result


def usage_hint(settings):
    config = configuration(settings)
    return config[
        "subagent_usage_hint_text"
        if settings.get("_parent_thread_id")
        else "root_agent_usage_hint_text"
    ]


def mode_hint(settings):
    config = configuration(settings)
    if "multi_agent_mode_hint_text" in config:
        text = config["multi_agent_mode_hint_text"]
    else:
        name = (
            "proactive"
            if settings.get("model_reasoning_effort") == "ultra"
            else "explicit_request_only"
        )
        text = _assets("subagents_v2.json")[name + "_multi_agent_mode_text"]
    return f"<multi_agent_mode>{text}</multi_agent_mode>" if text else None


def _name(name):
    if not name:
        raise ToolError("agent_name must not be empty")
    if name in {"root", ".", ".."}:
        raise ToolError(f"agent_name `{name}` is reserved")
    if "/" in name:
        raise ToolError("agent_name must not contain `/`")
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise ToolError(
            "agent_name must use only lowercase letters, digits, and underscores"
        )
    return name


def resolve_path(current, reference):
    if not isinstance(reference, str) or not reference:
        raise ToolError("agent path must not be empty")
    if reference in {"/root", "/morpheus"}:
        return reference
    absolute = reference.startswith("/")
    if absolute and not reference.startswith("/root/"):
        raise ToolError(
            "absolute agent paths must start with `/root` or be `/morpheus`"
        )
    if reference.endswith("/"):
        raise ToolError(
            ("absolute" if absolute else "relative")
            + " agent path must not end with `/`"
        )
    segments = (
        reference.removeprefix("/root/").split("/")
        if absolute
        else reference.split("/")
    )
    for segment in segments:
        _name(segment)
    return reference if absolute else current + "/" + reference


def communication(author, recipient, text, *, trigger=False, encrypted=True):
    prefix = f"Message Type: {'NEW_TASK' if trigger else 'MESSAGE'}\nTask name: {recipient}\nSender: {author}\nPayload:\n"
    content = [{"type": "input_text", "text": prefix}]
    if encrypted:
        content.append({"type": "encrypted_content", "encrypted_content": text})
    else:
        content[0]["text"] += text
    return {
        "type": "agent_message",
        "author": author,
        "recipient": recipient,
        "content": content,
    }


def collaboration_spec_v2(catalog, settings, roles, role_layers):
    config = configuration(settings)
    overrides = config["expose_spawn_agent_model_overrides"]
    hide = config["hide_spawn_agent_metadata"]
    catalog = [
        model for model in catalog if model.get("multi_agent_version") != "disabled"
    ]
    description = (
        _assets("subagents_v2.json")["spawn_description"]
        .replace("{agent_role_guidance}", _format_models(catalog) if overrides else "")
        .replace(
            "{inherited_model_guidance}",
            "Spawned agents inherit your current model by default. Omit `model` to use that preferred default; set `model` only when an explicit override is needed."
            if overrides and not hide
            else "",
        )
    )
    if config.get("usage_hint_text") is not None:
        description = "\n        " + description + "\n" + config["usage_hint_text"]
    spawn = {
        "message": {
            **schema("string", "Initial plain-text task for the new agent."),
            "encrypted": True,
        },
        "task_name": schema(
            "string",
            "Task name for the new agent. Use lowercase letters, digits, and underscores.",
        ),
        "fork_turns": schema(
            "string",
            "Optional number of turns to fork. Defaults to `all`. Use `none`, `all`, or a positive integer string such as `3` to fork only the most recent turns.",
        ),
    }
    if overrides:
        spawn.update(
            model=schema(
                "string",
                "Model override for the new agent. Omit unless an explicit override is needed.",
            ),
            reasoning_effort=schema(
                "string",
                "Reasoning effort override for the new agent. Omit to inherit the parent effort.",
            ),
        )
    if not hide:
        spawn["service_tier"] = schema(
            "string",
            "Service tier override for the new agent. Omit unless explicitly requested.",
        )
    if roles:
        spawn["agent_type"] = schema(
            "string",
            "Agent type override for the new agent. Omit unless explicitly asked. Set `fork_turns` to `none` or a positive integer when an explicit override is needed.\n"
            + _role_description(roles, role_layers),
        )
    tools = [function("spawn_agent", description, spawn, ["task_name", "message"])]
    for name, text, target, message_text in (
        (
            "send_message",
            "Send a message to an existing agent. The message will be delivered promptly. Does not trigger a new turn.",
            "Relative or canonical task name to message (from spawn_agent).",
            "Message text to queue on the target agent.",
        ),
        (
            "followup_task",
            "Send a follow-up task to an existing non-root target agent and trigger a turn if it is idle. If the target is already running, deliver the task promptly at message boundaries while sampling, or after the pending tool call completes.",
            "Agent id or canonical task name to send a follow-up task to (from spawn_agent).",
            "Message text to send to the target agent.",
        ),
    ):
        tools.append(
            function(
                name,
                text,
                {
                    "target": schema("string", target),
                    "message": {**schema("string", message_text), "encrypted": True},
                },
                ["target", "message"],
            )
        )
    tools += [
        function(
            "list_agents",
            "List live agents in the current root thread tree. Optionally filter by task-path prefix.",
            {
                "path_prefix": schema(
                    "string",
                    "Task-path prefix filter without a trailing slash. Omit to list all live agents.",
                )
            },
            None,
        ),
        function(
            "interrupt_agent",
            "Interrupt an agent's current turn, if any, and return its previous status. The agent remains available for messages and follow-up tasks.",
            {
                "target": schema(
                    "string",
                    "Agent id or canonical task name to interrupt (from spawn_agent).",
                )
            },
            ["target"],
        ),
    ]
    if config["wait_agent_enabled"]:
        default, minimum, maximum = (
            config[name + "_wait_timeout_ms"] for name in ("default", "min", "max")
        )
        tools.append(
            function(
                "wait_agent",
                "Wait for a mailbox update from any live agent, including queued messages and final-status notifications. The wait also ends early when new user input is steered into the active turn. Does not return the content; returns either a summary of which agents have updates (if any), an interruption summary for steered input, or a timeout summary if no activity arrives before the deadline.",
                {
                    "timeout_ms": schema(
                        "number",
                        f"Timeout in milliseconds. Defaults to {default}, min {minimum}, max {maximum}.",
                    )
                },
                None,
            )
        )
    return sorted(tools, key=lambda tool: tool["name"])


class SubagentsV2(Subagents):
    def augment_initial_context(self, items):
        if not hasattr(self, "config"):
            return items
        additions = [
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "input_text", "text": text}],
            }
            for text in (usage_hint(self.settings), mode_hint(self.settings))
            if text
        ]
        boundary = next(
            (
                index
                for index, item in enumerate(items)
                if item.get("role") != "developer"
            ),
            len(items),
        )
        return [*items[:boundary], *additions, *items[boundary:]]

    def _initialize_v2(self):
        self.config = configuration(self.settings)
        self.catalog = [
            model
            for model in self.catalog
            if model.get("multi_agent_version") != "disabled"
        ]
        self.path = self.settings.get(
            "_agent_path", self.request.get("_agent_path", "/root")
        )
        self.registry = self.request.setdefault(
            "_v2_registry",
            {
                "paths": {"/root": self.parent_id},
                "queues": {},
                "activity": {},
                "residents": [],
                "lock": asyncio.Lock(),
            },
        )
        self.registry["paths"][self.path] = self.parent_id
        self._ensure_queue()
        # V2 worker tool visibility follows model support, without V1's depth
        # limit. Root sessions retain their configured V2 tool surface.
        if (
            self.path != "/root"
            and self.router.model.info.get("multi_agent_version") != "v2"
        ):
            return
        namespace = self.config["tool_namespace"]
        if not self.settings.get("_provider_capabilities", {}).get(
            "namespace_tools", True
        ):
            namespace = None
        for tool in collaboration_spec_v2(
            self.catalog, self.settings, self.roles, self.role_layers
        ):
            spec = (
                tool
                if namespace is None
                else {
                    "type": "namespace",
                    "name": namespace,
                    "description": "Tools for spawning and managing sub-agents.",
                    "tools": [tool],
                }
            )
            self.router.register(
                (namespace + "." if namespace else "") + tool["name"],
                spec,
                getattr(self, tool["name"]),
                pass_call=tool["name"]
                in {"spawn_agent", "send_message", "followup_task"},
            )

    def _ensure_queue(self):
        queue = self.request.setdefault("_input_queue", asyncio.Queue())
        self.registry["queues"][self.parent_id] = queue
        activity = self.registry["activity"].setdefault(
            self.parent_id, {"event": asyncio.Event(), "kind": "mailbox"}
        )
        if getattr(queue, "_codex_v2_activity", None) is not activity:
            original = queue.put_nowait

            def put_nowait(value):
                original(value)
                values = value if isinstance(value, list) else [value]
                activity["kind"] = (
                    "mailbox"
                    if any(
                        isinstance(item, dict) and item.get("type") == "agent_message"
                        for item in values
                    )
                    else "steer"
                )
                activity["event"].set()

            queue.put_nowait = put_nowait
            queue._codex_v2_activity = activity
        self.activity = activity
        return queue

    def input_drained(self):
        if self._ensure_queue().empty():
            self.activity["event"].clear()
            self.request.pop("_v2_pending_trigger", None)
            if self.parent_id in self.tree:
                self.tree[self.parent_id].request.pop("_v2_pending_trigger", None)

    @staticmethod
    def _plaintext(call):
        if call is None or call.get("_source") == "code_mode":
            return False
        namespace = call.get("namespace")
        if namespace is None and call.get("name", "").startswith("collaboration."):
            namespace = "collaboration"
        return (
            namespace == "collaboration" and call.get("encrypted_function_args") == []
        )

    def _target(self, target):
        try:
            agent_id = str(uuid.UUID(target))
        except (TypeError, ValueError, AttributeError):
            path = resolve_path(self.path, target)
            agent_id = self.registry["paths"].get(path)
            if agent_id is None:
                raise ToolError(f"live agent path `{path}` not found")
        if agent_id == self.registry["paths"]["/root"]:
            return None
        agent = self.tree.get(agent_id)
        if agent is None:
            raise ToolError(f"agent with id {agent_id} not found")
        return agent

    def _validate_capacity(self):
        maximum = self.config["max_concurrent_threads_per_session"] - 1
        if (
            sum(
                agent.task is not None and not agent.task.done()
                for agent in self.tree.values()
            )
            >= maximum
        ):
            raise ToolError("collab spawn failed: agent thread limit reached")

    async def _resident(self, agent=None):
        residents = self.registry["residents"]
        if agent is not None and agent.id in residents:
            residents.remove(agent.id)
            residents.append(agent.id)
            return
        capacity = self.config["max_concurrent_threads_per_session"] - 1
        while len(residents) >= capacity:
            candidate = next(
                (
                    self.tree[key]
                    for key in residents
                    if self.tree[key].task is not None
                    and self.tree[key].task.done()
                    and self.tree[key].queue.empty()
                ),
                None,
            )
            if candidate is None:
                raise ToolError("collab spawn failed: agent thread limit reached")
            # Model history and task paths survive unloading, just like the
            # persisted native rollout. Session actors are recreated on reload.
            cache = candidate.request.get("_session_cache")
            if cache:
                from .loop import close_session

                cache.pop("subagents", None)
                await close_session(cache)
            candidate.loaded = False
            residents.remove(candidate.id)
        if agent is not None:
            agent.loaded = True
            self._set_status(agent, "pending_init")
            residents.append(agent.id)

    @staticmethod
    def _arguments(arguments, allowed, required=()):
        unknown = next((name for name in arguments if name not in allowed), None)
        if unknown is not None:
            raise ToolError(
                f"failed to parse function arguments: unknown field `{unknown}`"
            )
        for name in required:
            if name not in arguments:
                raise ToolError(
                    f"failed to parse function arguments: missing field `{name}`"
                )
            if not isinstance(arguments[name], str):
                raise ToolError(
                    f"failed to parse function arguments: {name} must be a string"
                )

    async def spawn_agent(self, arguments, *, call=None):
        self._arguments(
            arguments,
            {
                "message",
                "task_name",
                "agent_type",
                "model",
                "reasoning_effort",
                "service_tier",
                "fork_turns",
                "fork_context",
            },
            ("message", "task_name"),
        )
        if "fork_context" in arguments and arguments["fork_context"] is not None:
            raise ToolError(
                "fork_context is not supported in MultiAgentV2; use fork_turns instead"
            )
        mode = arguments.get("fork_turns")
        if mode is not None and not isinstance(mode, str):
            raise ToolError(
                "failed to parse function arguments: fork_turns must be a string"
            )
        mode = (mode or "").strip().lower() or "all"
        if mode not in {"none", "all"} and (
            not re.fullmatch(r"\+?[0-9]+", mode) or not 0 < int(mode) <= 2**64 - 1
        ):
            raise ToolError(
                "fork_turns must be `none`, `all`, or a positive integer string"
            )
        if not arguments["message"].strip():
            raise ToolError("Empty message can't be sent to an agent")
        # V2 controls delegation by model support and session execution/residency
        # capacity. The max_depth guard belongs to the V1 protocol only.
        path = self.path + "/" + _name(arguments["task_name"])
        translated = {**arguments, "fork_context": mode == "all"}
        settings = self._settings_for_child(translated)
        settings["_agent_path"] = path
        settings["_agent_type"] = (arguments.get("agent_type") or "default").strip()
        settings["_parent_transcript_path"] = self.settings.get("_transcript_path")
        if mode != "none":
            settings["_forked_from_thread_id"] = self.parent_id
        role_layer = self.role_layers.get(settings["_agent_type"]) or {}
        if self.config.get("subagent_developer_instructions") is not None and (
            mode == "all" or "developer_instructions" not in role_layer
        ):
            settings["developer_instructions"] = self.config[
                "subagent_developer_instructions"
            ].strip()
        async with self.registry["lock"]:
            self._validate_capacity()
            await self._resident()
            if path in self.registry["paths"]:
                raise ToolError(
                    f"collab spawn failed: agent path `{path}` already exists"
                )
            agent_id = str(uuid.uuid4())
            settings["_thread_id"] = agent_id
            settings.setdefault("_session_id", self.parent_id)
            llm = copy.deepcopy(self.request["llm"])
            llm["model_name"] = settings.get("model") or llm["model_name"]
            if "model" in llm:
                llm["model"] = llm["model_name"]
            if settings.get("model_reasoning_effort") is not None:
                llm["reasoning_effort"] = settings["model_reasoning_effort"]
            child = {
                key: value
                for key, value in self.request.items()
                if not key.startswith("_history")
                and key
                not in {
                    "initial_history",
                    "_input_queue",
                    "prompt_content",
                    "_initial_input_items",
                }
            }
            child.update(
                settings=settings,
                llm=llm,
                _agent_tree=self.tree,
                _v2_registry=self.registry,
                _session_cache={},
                _agent_path=path,
                _fork_context=mode == "all",
                _rebuild_initial_context=mode not in {"all", "none"},
            )
            history = [] if mode == "none" else self._fork_history(mode, settings)
            agent = Agent(
                agent_id,
                self.parent_id,
                child,
                history=history,
                path=path,
                nickname=self._nickname(settings["_agent_type"]),
            )
            self.tree[agent_id] = agent
            self.registry["paths"][path] = agent_id
            self.registry["queues"][agent_id] = agent.queue
            self.registry["residents"].append(agent_id)
            item = communication(
                self.path,
                path,
                arguments["message"],
                trigger=True,
                encrypted=not self._plaintext(call),
            )
            self._start(agent, [item])
        self.emit(
            {
                "type": "collab_agent_spawn",
                "agent_id": agent.id,
                "agent_path": path,
                "parent_thread_id": self.parent_id,
            }
        )
        result = {"task_name": path}
        if not self.config["hide_spawn_agent_metadata"]:
            result["nickname"] = agent.nickname
        return result

    def _fork_history(self, mode, child_settings=None):
        history = self._history()
        if mode != "all":
            positions = [
                index
                for index, item in enumerate(history)
                if (
                    item.get("type") == "message"
                    and item.get("role") == "user"
                    and not any(
                        "<environment_context>" in entry.get("text", "")
                        for entry in item.get("content", [])
                    )
                )
                or (
                    item.get("type") == "agent_message"
                    and any(
                        entry.get("text", "").startswith("Message Type: NEW_TASK\n")
                        for entry in item.get("content", [])
                    )
                )
            ]
            history = (
                history[positions[max(0, len(positions) - int(mode))] :]
                if positions
                else []
            )
        hints = {
            text
            for text in (
                self.config.get("root_agent_usage_hint_text"),
                self.config.get("subagent_usage_hint_text"),
            )
            if text
        }
        history = [
            item
            for item in fork_history(history)
            if not (
                item.get("type") == "message"
                and item.get("role") == "developer"
                and len(item.get("content", [])) == 1
                and item["content"][0].get("text") in hints
            )
        ]
        parent_instructions = self.settings.get("developer_instructions")
        child_instructions = self.config.get("subagent_developer_instructions")
        replaced_parent_instructions = False
        if parent_instructions and child_instructions is not None:
            for item in history:
                if item.get("type") == "message" and item.get("role") == "developer":
                    for entry in item.get("content", []):
                        if entry.get(
                            "type"
                        ) == "input_text" and parent_instructions in entry.get(
                            "text", ""
                        ):
                            replaced_parent_instructions = True
                            entry["text"] = entry.get("text", "").replace(
                                parent_instructions,
                                child_instructions.strip() if mode == "all" else "",
                            )
        # control/spawn.rs appends a full fork's override when the parent's
        # durable reference context contained no developer fragment to replace.
        # _initial_context marks that initialized baseline in the Python loop.
        if (
            mode == "all"
            and child_instructions is not None
            and child_instructions.strip()
            and not replaced_parent_instructions
            and self.request.get("_initial_context") is not None
        ):
            history.append(
                {
                    "type": "message",
                    "role": "developer",
                    "content": [
                        {"type": "input_text", "text": child_instructions.strip()}
                    ],
                }
            )
        if mode == "all" and self.config.get("subagent_usage_hint_text"):
            history.append(
                {
                    "type": "message",
                    "role": "developer",
                    "content": [
                        {
                            "type": "input_text",
                            "text": self.config["subagent_usage_hint_text"],
                        }
                    ],
                }
            )
            # Full forks preserve the parent's durable world-state baseline.
            # spawn_forked_thread appends the child hint, then the first child
            # turn emits changed world-state sections. A root -> child hint
            # change therefore repeats the hint and reasserts the active mode.
            if usage_hint(self.settings) != self.config["subagent_usage_hint_text"]:
                for text in (
                    self.config["subagent_usage_hint_text"],
                    mode_hint(child_settings or self.settings),
                ):
                    if text:
                        history.append(
                            {
                                "type": "message",
                                "role": "developer",
                                "content": [{"type": "input_text", "text": text}],
                            }
                        )
        return history

    async def _drive(self, agent, items, submission_id=None):
        try:
            self._set_status(agent, "running")
            agent.turn += 1
            agent.request["settings"]["_turn_id"] = submission_id or str(uuid.uuid4())
            request = dict(agent.request)
            request["_rebuild_initial_context"] = agent.turn == 1 and agent.request.get(
                "_rebuild_initial_context", False
            )
            texts = [
                entry.get("text", entry.get("encrypted_content", ""))
                for item in items
                for entry in item.get("content", [])
            ]
            request.update(
                prompt="".join(texts),
                _initial_input_items=items,
                _input_queue=agent.queue,
                _history_sink=lambda history: setattr(
                    agent, "history", copy.deepcopy(history)
                ),
            )
            if agent.turn > 1 or agent.history or agent.request.get("_fork_context"):
                request["initial_history"] = copy.deepcopy(agent.history)

            def emit(event):
                self.emit(
                    {
                        **event,
                        "agent_id": agent.id,
                        "agent_path": agent.path,
                        "parent_thread_id": agent.parent_id,
                    }
                )

            result = await self.run_session(request, emit)
            agent.history = copy.deepcopy(result.get("history", agent.history))
            for key, value in result.get("usage", {}).items():
                if isinstance(value, (int, float)):
                    agent.usage[key] = agent.usage.get(key, 0) + value
            if result.get("status") in {"finished", "completed", "success"}:
                self._set_status(agent, {"completed": result.get("output") or None})
            elif result.get("status") == "interrupted":
                self._set_status(agent, "shutdown" if agent.closed else "interrupted")
                return
            else:
                self._set_status(
                    agent,
                    {
                        "errored": result.get("error_message")
                        or result.get("output")
                        or "agent execution failed"
                    },
                )
            await self._notify(agent)
            if (
                agent.request.pop("_v2_pending_trigger", False)
                and not agent.queue.empty()
            ):
                pending = []
                while not agent.queue.empty():
                    pending.extend(agent.queue.get_nowait())
                self._start(agent, pending)
        except asyncio.CancelledError:
            self._set_status(agent, "shutdown" if agent.closed else "interrupted")
            raise
        except Exception as error:
            self._set_status(agent, {"errored": str(error)})
            await self._notify(agent)

    async def _notify(self, agent):
        status = agent.status
        if isinstance(status, dict) and "completed" in status:
            payload = status["completed"] or ""
        elif isinstance(status, dict) and "errored" in status:
            payload = (
                "Agent errored: "
                + truncate(status["errored"], 900)
                + "\n\nThis agent's turn failed. If you still need this agent, use the available collaboration tools to give it another task."
            )
        else:
            return
        parent = agent.path.rsplit("/", 1)[0]
        item = {
            "type": "agent_message",
            "author": agent.path,
            "recipient": parent,
            "content": [
                {
                    "type": "input_text",
                    "text": f"Message Type: FINAL_ANSWER\nTask name: {parent}\nSender: {agent.path}\nPayload:\n{payload}",
                }
            ],
        }
        queue = self.registry["queues"].get(agent.parent_id)
        if queue is not None:
            queue.put_nowait([item])
        self.emit(
            {
                "type": "collab_agent_status",
                "agent_id": agent.id,
                "agent_path": agent.path,
                "status": status,
            }
        )

    async def _deliver(self, agent, item, trigger=False):
        if agent is None:
            if trigger:
                raise ToolError("Follow-up tasks can't target the root agent")
            self.registry["queues"][self.registry["paths"]["/root"]].put_nowait([item])
            return
        async with self.registry["lock"]:
            await self._resident(agent)
            active = agent.task is not None and not agent.task.done()
            if trigger:
                agent.request["settings"]["_parent_turn_id"] = self.settings.get(
                    "_turn_id"
                )
            if trigger and not active:
                self._validate_capacity()
                queued = []
                while not agent.queue.empty():
                    queued.extend(agent.queue.get_nowait())
                self._start(agent, queued + [item])
            else:
                agent.queue.put_nowait([item])
                if trigger:
                    agent.request["_v2_pending_trigger"] = True

    async def _message_tool(self, arguments, trigger, call=None):
        self._arguments(arguments, {"target", "message"}, ("target", "message"))
        if not arguments["message"].strip():
            raise ToolError("Empty message can't be sent to an agent")
        agent = self._target(arguments["target"])
        recipient = agent.path if agent else "/root"
        await self._deliver(
            agent,
            communication(
                self.path,
                recipient,
                arguments["message"],
                trigger=trigger,
                encrypted=not self._plaintext(call),
            ),
            trigger,
        )
        return ""

    async def send_message(self, arguments, *, call=None):
        return await self._message_tool(arguments, False, call)

    async def followup_task(self, arguments, *, call=None):
        return await self._message_tool(arguments, True, call)

    async def handle_agent_message(self, item):
        agent = self._target(item.get("recipient"))
        delivered = copy.deepcopy(item)
        delivered["author"] = self.path
        delivered["recipient"] = agent.path if agent else "/root"
        await self._deliver(agent, delivered)

    async def list_agents(self, arguments):
        self._arguments(arguments, {"path_prefix"})
        prefix = arguments.get("path_prefix")
        prefix = resolve_path(self.path, prefix) if prefix is not None else None

        def matches(path):
            return prefix is None or path == prefix or path.startswith(prefix + "/")

        rows = (
            [{"agent_name": "/root", "agent_status": "running"}]
            if matches("/root")
            else []
        )
        rows += [
            {"agent_name": agent.path, "agent_status": copy.deepcopy(agent.status)}
            for agent in sorted(
                self.tree.values(), key=lambda agent: (agent.path or "", agent.id)
            )
            if agent.loaded and not agent.closed and agent.path and matches(agent.path)
        ]
        return {"agents": rows}

    async def interrupt_agent(self, arguments):
        self._arguments(arguments, {"target"}, ("target",))
        agent = self._target(arguments["target"])
        if agent is None:
            raise ToolError("root is not a spawned agent")
        if agent.id == self.parent_id:
            raise ToolError(
                "an agent cannot interrupt itself; return your result and let the parent interrupt you if needed"
            )
        previous = copy.deepcopy(agent.status) if agent.loaded else "not_found"
        if agent.task and not agent.task.done():
            agent.task.cancel()
            await asyncio.gather(agent.task, return_exceptions=True)
        return {"previous_status": previous}

    async def wait_agent(self, arguments):
        self._arguments(arguments, {"timeout_ms"})
        timeout = arguments.get("timeout_ms")
        timeout = self.config["default_wait_timeout_ms"] if timeout is None else timeout
        if type(timeout) is not int:
            raise ToolError(
                "failed to parse function arguments: timeout_ms must be an integer"
            )
        for bound, comparator, phrase in (
            ("min", lambda value, limit: value < limit, "at least"),
            ("max", lambda value, limit: value > limit, "at most"),
        ):
            limit = self.config[bound + "_wait_timeout_ms"]
            if comparator(timeout, limit):
                raise ToolError(f"timeout_ms must be {phrase} {limit}")
        queue = self._ensure_queue()
        if queue.empty():
            self.activity["event"].clear()
            try:
                await asyncio.wait_for(self.activity["event"].wait(), timeout / 1000)
            except TimeoutError:
                return {"message": "Wait timed out.", "timed_out": True}
        return {
            "message": "Wait interrupted by new input."
            if self.activity["kind"] == "steer"
            else "Wait completed.",
            "timed_out": False,
        }
