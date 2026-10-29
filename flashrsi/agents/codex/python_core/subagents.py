"""Codex collaboration port from rust-v0.147.0 (be6e8eac).

Sources: core/src/tools/handlers/{multi_agents,multi_agents_common,
multi_agents_spec}.rs, multi_agents/{spawn,send_input,wait,resume_agent,
close_agent}.rs and core/src/agent/{control,registry,role,status}.rs.
Tasks execute the same Python session loop; no native actor or CLI is started.
V2's task-path and mailbox implementation lives in subagents_v2.py.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import json
import random
import tomllib
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .models import Model
from .shell import ToolError
from .tools import function, object_schema, schema

NAMESPACE = "multi_agent_v1"
DEFAULT_TIMEOUT = 30000
MIN_TIMEOUT = 10000
MAX_TIMEOUT = 3600000
SEARCH_TEXT = {
    "spawn_agent": "spawn_agent spawn agent subagent sub-agent delegate delegation parallel work worker explorer no-apps fork model reasoning",
    "send_input": "send_input send message existing agent subagent follow up interrupt redirect queue target",
    "resume_agent": "resume_agent resume reopen closed agent subagent thread id target",
    "wait_agent": "wait_agent wait agent subagent status final result complete timeout targets",
    "close_agent": "close_agent close shutdown stop agent subagent thread status target",
}


def _assets(name):
    return json.loads((Path(__file__).with_name("tool_assets") / name).read_text())


def output_schemas(version="v1", settings=None):
    """Reviewed output types for Code Mode; regular tool wire omits them."""
    assets = _assets("collaboration_output_schemas.json")
    if version == "v2":
        from .subagents_v2 import configuration

        hide = configuration(settings or {})["hide_spawn_agent_metadata"]
        return {
            "spawn_agent": assets[
                "spawn_agent_v2_hidden" if hide else "spawn_agent_v2"
            ],
            "list_agents": assets["list_agents"],
            "interrupt_agent": assets["interrupt_agent"],
            "wait_agent": assets["wait_agent_v2"],
        }
    return {
        "spawn_agent": assets["spawn_agent_v1"],
        "send_input": assets["send_input"],
        "resume_agent": assets["resume_agent"],
        "wait_agent": assets["wait_agent_v1"],
        "close_agent": assets["close_agent"],
    }


def _items_schema():
    return schema(
        "array",
        "Structured input items. Use this to pass explicit mentions (for example app:// connector paths).",
        items=object_schema(
            {
                "type": schema(
                    "string",
                    "Input item type: text, image, local_image, audio, local_audio, skill, or mention.",
                ),
                "text": schema("string", "Text content when type is text."),
                "image_url": schema("string", "Image URL when type is image."),
                "audio_url": schema("string", "Audio data URL when type is audio."),
                "path": schema(
                    "string",
                    "Path when type is local_image/local_audio/skill, or structured mention target such as app://<connector-id> or plugin://<plugin-name>@<marketplace-name> when type is mention.",
                ),
                "name": schema("string", "Display name when type is skill or mention."),
            }
        ),
    )


def _format_models(catalog):
    models = [
        model
        for model in sorted(catalog, key=lambda model: model.get("priority", 99))
        if model.get("visibility") == "list"
    ][:5]
    if not models:
        return "No picker-visible model overrides are currently loaded."
    lines = []
    for model in models:
        efforts = ", ".join(
            level["effort"][:64]
            + (
                " (default)"
                if level["effort"] == model.get("default_reasoning_level")
                else ""
            )
            for level in model.get("supported_reasoning_levels", [])
        )
        tiers = ", ".join(tier["id"] for tier in model.get("service_tiers", []))
        lines.append(
            f"- `{model['slug']}`: {model['description']}"
            + (f" Reasoning efforts: {efforts}." if efforts else "")
            + (f" Service tiers: {tiers}." if tiers else "")
        )
    return (
        "Available model overrides (optional; inherited parent model is preferred):\n"
        + "\n".join(lines)
    )


def _role_description(roles, role_layers):
    combined = {**_assets("agent_roles.json"), **roles}
    names = sorted(roles) + sorted(set(combined) - set(roles))
    lines = []
    for name in names:
        declaration = combined[name]
        description = declaration.get("description")
        if description is None:
            lines.append(f"{name}: no description")
            continue
        layer = role_layers.get(name) or {}
        model, effort, tier = (
            layer.get(key)
            for key in ("model", "model_reasoning_effort", "service_tier")
        )
        note = ""
        if model and effort:
            note = f"\n- This role's model is set to `{model}` and its reasoning effort is set to `{effort}`. These settings cannot be changed."
        elif model:
            note = f"\n- This role's model is set to `{model}` and cannot be changed."
        elif effort:
            note = f"\n- This role's reasoning effort is set to `{effort}` and cannot be changed."
        if tier:
            note += f"\n- This role's service tier is set to `{tier}`. If it is supported by the resolved model, it takes precedence over a valid spawn request service tier."
        lines.append(f"{name}: {{\n{description}{note}\n}}")
    return "Available roles:\n" + "\n".join(lines)


def collaboration_spec(catalog, settings, roles, role_layers):
    """multi_agents_spec constructors, preserving raw description whitespace."""
    templates = _assets("spawn_agent_templates.json")
    tool_description = (
        templates["tool_description"]
        .replace("{agent_role_guidance}", _format_models(catalog))
        .replace(
            "{return_value_description}",
            "Returns the spawned agent id plus the user-facing nickname when available.",
        )
        .replace(
            "{inherited_model_guidance}",
            "Spawned agents inherit your current model by default. Omit `model` to use that preferred default; set `model` only when an explicit override is needed.",
        )
    )
    hint = settings.get("multi_agent_v2", {}).get("usage_hint_text")
    if hint is None:
        description = (
            templates["description"]
            .replace("{tool_description}", tool_description)
            .replace(
                "{agent_role_usage_hint}",
                "Agent-role guidance below only helps choose which agent to use after spawning is already authorized; it never authorizes spawning by itself.",
            )
        )
    else:
        description = (
            templates["with_usage_hint"]
            .replace("{tool_description}", tool_description)
            .replace("{usage_hint_text}", hint)
        )
    spawn = {
        "message": schema(
            "string",
            "Initial plain-text task for the new agent. Use either message or items.",
        ),
        "items": _items_schema(),
        "fork_context": schema(
            "boolean",
            "True forks the current thread history into the new agent; false or omitted starts with only the initial prompt.",
        ),
        "model": schema(
            "string",
            "Model override for the new agent. Omit unless an explicit override is needed.",
        ),
        "reasoning_effort": schema(
            "string",
            "Reasoning effort override for the new agent. Omit to inherit the parent effort.",
        ),
        "service_tier": schema(
            "string",
            "Service tier override for the new agent. Omit unless explicitly requested.",
        ),
    }
    if roles:
        spawn["agent_type"] = schema(
            "string",
            "Agent type override for the new agent. Omit to inherit the parent agent type with a full-history fork; otherwise, `default` is used.\n"
            + _role_description(roles, role_layers),
        )
    tools = [
        function("spawn_agent", description, spawn, None),
        function(
            "send_input",
            "Send a message to an existing agent. Use interrupt=true to redirect work immediately. You should reuse the agent by send_input if you believe your assigned task is highly dependent on the context of a previous task.",
            {
                "target": schema("string", "Agent id to message (from spawn_agent)."),
                "message": schema(
                    "string",
                    "Legacy plain-text message to send to the agent. Use either message or items.",
                ),
                "items": _items_schema(),
                "interrupt": schema(
                    "boolean",
                    "True interrupts the current task and handles this message immediately; false or omitted queues it.",
                ),
            },
            ["target"],
        ),
        function(
            "resume_agent",
            "Resume a previously closed agent by id so it can receive send_input and wait_agent calls.",
            {"id": schema("string", "Agent id to resume.")},
            ["id"],
        ),
        function(
            "wait_agent",
            "Wait for agents to reach a final status. Completed statuses may include the agent's final message. Returns empty status when timed out. Once the agent reaches a final status, a notification message will be received containing the same completed status.",
            {
                "targets": schema(
                    "array",
                    "Agent ids to wait on. Pass multiple ids to wait for whichever finishes first.",
                    items=schema("string"),
                ),
                "timeout_ms": schema(
                    "number",
                    f"Timeout in milliseconds. Defaults to {DEFAULT_TIMEOUT}, min {MIN_TIMEOUT}, max {MAX_TIMEOUT}. Prefer longer waits (minutes) to avoid busy polling.",
                ),
            },
            ["targets"],
        ),
        function(
            "close_agent",
            "Close an agent and any open descendants when they are no longer needed, and return the target agent's previous status before shutdown was requested. Completed agents remain open and count toward the concurrency limit until closed. Don't keep agents open for too long if they are not needed anymore.",
            {"target": schema("string", "Agent id to close (from spawn_agent).")},
            ["target"],
        ),
    ]
    return {
        "type": "namespace",
        "name": NAMESPACE,
        "description": "Tools for spawning and managing sub-agents.",
        "tools": sorted(tools, key=lambda tool: tool["name"]),
    }


def _merge(base, overlay):
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _validate_role_layer(layer):
    # Native role.rs rebuilds provider settings and uses ConfigToml's typed
    # paths relative to the role file. These capabilities require that reload
    # machinery; merging their raw values would silently change their meaning.
    for key in ("model_provider", "model_providers", "profile", "profiles"):
        if key in layer:
            raise ToolError(
                f"Python custom agent roles do not support provider/profile configuration `{key}`"
            )
    path_keys = {
        "config_file",
        "cwd",
        "model_instructions_file",
        "experimental_compact_prompt_file",
        "model_catalog_json",
        "js_repl_node_path",
        "sqlite_home",
        "log_dir",
        "export_dir",
        "load_path",
    }
    path_lists = {"writable_roots", "js_repl_node_module_dirs"}

    def visit(value, path=()):
        if not isinstance(value, dict):
            return
        for key, child in value.items():
            location = (*path, key)
            values = (
                [child]
                if key in path_keys
                else child
                if key in path_lists and isinstance(child, list)
                else []
            )
            if any(
                isinstance(item, str) and not Path(item).is_absolute()
                for item in values
            ):
                raise ToolError(
                    f"Python custom agent roles do not support relative path configuration `{'.'.join(location)}`"
                )
            visit(child, location)

    visit(layer)


def _message(content):
    return {"type": "message", "role": "user", "content": content}


def fork_history(items):
    """control/spawn.rs::keep_forked_rollout_item's model-context projection."""
    return [
        item
        for item in items
        if item.get("type") == "message"
        and (
            item.get("role") in {"system", "developer", "user"}
            or (item.get("role") == "assistant" and item.get("phase") == "final_answer")
        )
    ]


@dataclass
class Agent:
    id: str
    parent_id: str
    request: dict
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None
    status: str | dict = "pending_init"
    history: list = field(default_factory=list)
    changed: asyncio.Event = field(default_factory=asyncio.Event)
    closed: bool = False
    nickname: str | None = None
    turn: int = 0
    usage: dict = field(default_factory=dict)
    path: str | None = None
    loaded: bool = True


class Subagents:
    def __new__(cls, router, request, emit, run_session):
        if cls is Subagents:
            feature = request["settings"].get("features", {}).get("multi_agent_v2")
            enabled = (
                feature.get("enabled", True) if isinstance(feature, dict) else feature
            )
            if enabled or router.model.info.get("multi_agent_version") == "v2":
                from .subagents_v2 import SubagentsV2

                return object.__new__(SubagentsV2)
        return object.__new__(cls)

    def __init__(self, router, request, emit, run_session):
        self.router, self.request, self.emit, self.run_session = (
            router,
            request,
            emit,
            run_session,
        )
        self.settings = request["settings"]
        self.parent_id = str(
            self.settings.get("_thread_id", self.settings.get("_session_id", "root"))
        )
        self.depth = int(self.settings.get("_agent_depth", 0))
        self.tree: dict[str, Agent] = request.setdefault("_agent_tree", {})
        self.nicknames = request.setdefault(
            "_agent_nicknames", {"used": set(), "reset": 0}
        )
        model_assets = getattr(
            router.model, "assets_dir", Path(__file__).with_name("assets")
        )
        self.catalog = [
            model
            for model in json.loads((model_assets / "models.json").read_text())[
                "models"
            ]
            if model.get("supported_in_api", True)
        ]
        declarations = self.settings.get("agents", {})
        # config/mod.rs resolves this public TOML field into agent_max_threads.
        # V1 counts all open children, including completed threads, with six
        # slots when the optional value is absent.
        maximum = declarations.get("max_concurrent_threads_per_session")
        if maximum is not None:
            label = "agents.max_concurrent_threads_per_session"
            if type(maximum) is not int or not 0 <= maximum <= 2**64 - 1:
                raise ValueError(f"{label} must be a non-negative integer")
            if maximum == 0:
                raise ValueError(f"{label} must be at least 1")
        self.max_threads = 6 if maximum is None else maximum
        self.roles = {
            name: value
            for name, value in declarations.items()
            if isinstance(value, dict) and name not in {"multi_agent_v2"}
        }
        self.role_layers = {}
        for name, role in self.roles.items():
            if role.get("config_file"):
                path = Path(role["config_file"])
                if not path.is_absolute():
                    path = Path(request["home"]) / path
                try:
                    self.role_layers[name] = tomllib.loads(path.read_text())
                except (OSError, ValueError):
                    # Source format_role ignores read errors; spawn rejects.
                    self.role_layers[name] = None
        features = self.settings.get("features", {})
        if not self.settings.get(
            "agents_enabled", self.settings.get("agents", {}).get("enabled", True)
        ):
            return
        feature = features.get("multi_agent_v2", False)
        enabled = feature.get("enabled", True) if isinstance(feature, dict) else feature
        version = "v2" if enabled else router.model.info.get("multi_agent_version")
        if version is None:
            version = "v1" if features.get("multi_agent", True) else "disabled"
        if version == "v2":
            self._initialize_v2()
            return
        if version == "disabled" or self.depth + 1 > self._limit("max_depth", 1):
            return
        spec = collaboration_spec(
            self.catalog, self.settings, self.roles, self.role_layers
        )
        for tool in spec["tools"]:
            router.register(
                f"{NAMESPACE}.{tool['name']}",
                {**spec, "tools": [tool]},
                getattr(self, tool["name"]),
                deferred=True,
                search_text=SEARCH_TEXT[tool["name"]],
                source_info={
                    "name": "Multi-agent tools",
                    "description": "Spawn and manage sub-agents.",
                },
            )

    def _limit(self, name, default):
        return self.settings.get("agents", {}).get(
            name, self.settings.get("agent_" + name, default)
        )

    def augment_initial_context(self, items):
        return items

    def _validate_depth(self):
        if self.depth + 1 > self._limit("max_depth", 1):
            raise ToolError("Agent depth limit reached. Solve the task yourself.")

    def _validate_capacity(self):
        if sum(not agent.closed for agent in self.tree.values()) >= self.max_threads:
            raise ToolError("collab spawn failed: agent thread limit reached")

    def _nickname(self, role):
        candidates = self.roles.get(role, {}).get("nickname_candidates")
        if candidates is None:
            candidates = [
                line.strip()
                for line in (
                    Path(__file__).with_name("tool_assets") / "agent_names.txt"
                )
                .read_text()
                .splitlines()
                if line.strip()
            ]
        if not candidates:
            raise ToolError("collab spawn failed: no available agent nicknames")

        def formatted(name):
            reset = self.nicknames["reset"]
            if not reset:
                return name
            value = reset + 1
            suffix = (
                "th"
                if 11 <= value % 100 <= 13
                else {1: "st", 2: "nd", 3: "rd"}.get(value % 10, "th")
            )
            return f"{name} the {value}{suffix}"

        available = [
            formatted(name)
            for name in candidates
            if formatted(name) not in self.nicknames["used"]
        ]
        if not available:
            self.nicknames["used"].clear()
            self.nicknames["reset"] += 1
            available = [formatted(name) for name in candidates]
        nickname = random.choice(available)
        self.nicknames["used"].add(nickname)
        return nickname

    def _agent(self, target, allow_closed=False):
        try:
            target = str(uuid.UUID(target))
        except (ValueError, TypeError, AttributeError) as error:
            raise ToolError(f"invalid agent id {target}: {error}") from error
        agent = self.tree.get(target)
        if agent is None:
            raise ToolError(f"agent with id {target} not found")
        if agent.closed and not allow_closed:
            raise ToolError(f"agent with id {target} is closed")
        return agent

    def _input(self, arguments):
        message, items = arguments.get("message"), arguments.get("items")
        if message is not None and items is not None:
            raise ToolError("Provide either message or items, but not both")
        if message is None and items is None:
            raise ToolError("Provide one of: message or items")
        if message is not None:
            if not isinstance(message, str):
                raise ToolError(
                    "failed to parse function arguments: message must be a string"
                )
            if not message.strip():
                raise ToolError("Empty message can't be sent to an agent")
            items = [{"type": "text", "text": message}]
        if not items:
            raise ToolError("Items can't be empty")
        content = []
        for item in items:
            kind = item.get("type")
            if kind == "text":
                content.append({"type": "input_text", "text": item["text"]})
            elif kind == "image":
                content.append({"type": "input_image", "image_url": item["image_url"]})
            elif kind == "local_image":
                path = Path(self.request["cwd"]) / item["path"]
                data = path.read_bytes()
                content.append(
                    {
                        "type": "input_image",
                        "image_url": "data:application/octet-stream;base64,"
                        + base64.b64encode(data).decode(),
                    }
                )
            else:
                raise ToolError(
                    f"Python sub-agent input capability for `{kind}` is unavailable"
                )
        return content

    def _settings_for_child(self, arguments):
        settings = copy.deepcopy(self.settings)
        role = (arguments.get("agent_type") or "").strip() or None
        if arguments.get("fork_context") and role is not None:
            raise ToolError(
                "Full-history forked agents inherit the parent agent type; omit agent_type, or spawn without a full-history fork."
            )
        requested_model = arguments.get("model") or settings.get("agents", {}).get(
            "default_subagent_model"
        )
        requested_effort = arguments.get("reasoning_effort") or settings.get(
            "agents", {}
        ).get("default_subagent_reasoning_effort")
        if requested_model:
            match = next(
                (model for model in self.catalog if model["slug"] == requested_model),
                None,
            )
            if match is None:
                available = ", ".join(
                    model["slug"]
                    for model in sorted(
                        self.catalog, key=lambda model: model.get("priority", 99)
                    )
                    if model.get("visibility") == "list"
                )
                raise ToolError(
                    f"Unknown model `{requested_model}` for spawn_agent. Available models: {available}"
                )
            settings["model"] = requested_model
            settings["model_reasoning_effort"] = match.get("default_reasoning_level")
        if requested_effort:
            model_name = (
                settings.get("model")
                or self.request["llm"].get("model_name")
                or self.request["llm"].get("model")
            )
            model = Model(model_name, settings)
            supported = [
                level["effort"]
                for level in model.info.get("supported_reasoning_levels", [])
            ]
            if requested_effort not in supported:
                raise ToolError(
                    f"Reasoning effort `{requested_effort}` is not supported for model `{model_name}`. Supported reasoning efforts: {', '.join(supported)}"
                )
            settings["model_reasoning_effort"] = requested_effort
        if not arguments.get("fork_context"):
            name = role or "default"
            if name not in self.roles and name not in _assets("agent_roles.json"):
                raise ToolError(f"unknown agent_type '{name}'")
            layer = self.role_layers.get(name, {})
            if layer is None:
                raise ToolError("agent type is currently not available")
            _validate_role_layer(layer)
            _merge(settings, layer)
        if arguments.get("service_tier") is not None:
            model_name = (
                settings.get("model")
                or self.request["llm"].get("model_name")
                or self.request["llm"].get("model")
            )
            model = Model(model_name, settings)
            supported = [tier["id"] for tier in model.info.get("service_tiers", [])]
            requested = arguments["service_tier"]
            if requested not in supported:
                raise ToolError(
                    f"Service tier `{requested}` is not supported for model `{model_name}`. Supported service tiers: {', '.join(supported) or 'none'}"
                )
            if not (self.role_layers.get(role or "default") or {}).get("service_tier"):
                settings["service_tier"] = requested
        settings["_agent_depth"] = self.depth + 1
        settings["_parent_thread_id"] = self.parent_id
        settings["_parent_turn_id"] = self.settings.get("_turn_id")
        settings["_subagent_kind"] = "thread_spawn"
        settings["_agent_type"] = (
            role or self.settings.get("_agent_type", "default")
            if arguments.get("fork_context")
            else role or "default"
        )
        settings["_parent_transcript_path"] = self.settings.get("_transcript_path")
        settings.pop("_transcript_path", None)
        for key in (
            "approval_policy",
            "approvals_reviewer",
            "cwd",
            "permissions",
            "sandbox_mode",
            "sandbox_workspace_write",
            "sandbox_external_sandbox",
        ):
            if key in self.settings:
                settings[key] = copy.deepcopy(self.settings[key])
            else:
                settings.pop(key, None)
        if arguments.get("fork_context"):
            settings["_forked_from_thread_id"] = self.parent_id
        else:
            settings.pop("_forked_from_thread_id", None)
        return settings

    def _history(self):
        provider = self.request.get("_history_provider")
        return copy.deepcopy(
            provider() if provider else self.request.get("initial_history", [])
        )

    async def spawn_agent(self, arguments):
        content = self._input(arguments)
        self._validate_depth()
        self._validate_capacity()
        settings = self._settings_for_child(arguments)
        agent_id = str(uuid.uuid4())
        settings["_thread_id"] = agent_id
        settings.setdefault("_session_id", self.parent_id)
        llm = copy.deepcopy(self.request["llm"])
        llm["model_name"] = (
            settings.get("model") or llm.get("model_name") or llm.get("model")
        )
        if "model" in llm:
            llm["model"] = llm["model_name"]
        if settings.get("model_reasoning_effort") is not None:
            llm["reasoning_effort"] = settings["model_reasoning_effort"]
        child = {
            key: value
            for key, value in self.request.items()
            if not key.startswith("_history")
            and key not in {"initial_history", "_input_queue", "prompt_content"}
        }
        child.update(
            settings=settings,
            llm=llm,
            _agent_tree=self.tree,
            _session_cache={},
            _fork_context=bool(arguments.get("fork_context")),
        )
        nickname = self._nickname(settings["_agent_type"])
        agent = Agent(
            agent_id,
            self.parent_id,
            child,
            history=fork_history(self._history())
            if arguments.get("fork_context")
            else [],
            nickname=nickname,
        )
        self.tree[agent_id] = agent
        self._start(agent, content)
        self.emit(
            {
                "type": "collab_agent_spawn",
                "agent_id": agent_id,
                "parent_thread_id": self.parent_id,
            }
        )
        return {"agent_id": agent_id, "nickname": nickname}

    def _set_status(self, agent, status):
        agent.status = status
        agent.changed.set()

    def _start(self, agent, content, submission_id=None):
        agent.closed = False
        self._set_status(agent, "pending_init")
        agent.task = asyncio.create_task(self._drive(agent, content, submission_id))

    async def _drive(self, agent, content, submission_id=None):
        try:
            while True:
                self._set_status(agent, "running")
                agent.turn += 1
                agent.request["settings"]["_turn_id"] = submission_id or str(
                    uuid.uuid4()
                )
                submission_id = None
                request = dict(agent.request)
                request.update(
                    prompt="\n".join(
                        item["text"] for item in content if item["type"] == "input_text"
                    ),
                    prompt_content=content,
                    _input_queue=agent.queue,
                    _history_sink=lambda history: setattr(
                        agent, "history", copy.deepcopy(history)
                    ),
                )
                if (
                    agent.turn > 1
                    or agent.history
                    or agent.request.get("_fork_context")
                ):
                    request["initial_history"] = copy.deepcopy(agent.history)

                def emit(event):
                    self.emit(
                        {
                            **event,
                            "agent_id": agent.id,
                            "parent_thread_id": agent.parent_id,
                        }
                    )

                result = await self.run_session(request, emit)
                agent.history = copy.deepcopy(result.get("history", agent.history))
                for key, value in result.get("usage", {}).items():
                    if isinstance(value, (int, float)):
                        agent.usage[key] = agent.usage.get(key, 0) + value
                if result.get("status") in {"completed", "success", "finished"}:
                    self._set_status(agent, {"completed": result.get("output") or None})
                elif result.get("status") == "interrupted":
                    self._set_status(
                        agent, "shutdown" if agent.closed else "interrupted"
                    )
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
                if agent.queue.empty():
                    break
                messages = agent.queue.get_nowait()
                content = messages[0]["content"]
            self.emit(
                {
                    "type": "collab_agent_status",
                    "agent_id": agent.id,
                    "status": agent.status,
                }
            )
            parent_queue = self.request.get("_input_queue")
            if parent_queue is not None:
                parent_queue.put_nowait(
                    [
                        _message(
                            [
                                {
                                    "type": "input_text",
                                    "text": f"<subagent_notification>\n{json.dumps({'agent_path': agent.id, 'status': agent.status}, ensure_ascii=False, separators=(',', ':'), sort_keys=True)}\n</subagent_notification>",
                                }
                            ]
                        )
                    ]
                )
        except asyncio.CancelledError:
            self._set_status(agent, "shutdown" if agent.closed else "interrupted")
            raise
        except Exception as error:
            self._set_status(agent, {"errored": str(error)})
            self.emit(
                {
                    "type": "collab_agent_status",
                    "agent_id": agent.id,
                    "status": agent.status,
                }
            )

    async def send_input(self, arguments):
        agent = self._agent(arguments.get("target"))
        content = self._input(arguments)
        submission_id = str(uuid.uuid4())
        if arguments.get("interrupt") and agent.task and not agent.task.done():
            agent.task.cancel()
            await asyncio.gather(agent.task, return_exceptions=True)
        if agent.task is None or agent.task.done():
            self._start(agent, content, submission_id)
        else:
            agent.queue.put_nowait([_message(content)])
        return {"submission_id": submission_id}

    async def wait_agent(self, arguments):
        targets = arguments.get("targets")
        if not isinstance(targets, list) or not targets:
            raise ToolError("agent ids must be non-empty")
        timeout = arguments.get("timeout_ms", DEFAULT_TIMEOUT)
        if not isinstance(timeout, int) or timeout <= 0:
            raise ToolError("timeout_ms must be greater than zero")
        timeout = min(MAX_TIMEOUT, max(MIN_TIMEOUT, timeout))
        agents = []
        for target in targets:
            try:
                agents.append((target, self._agent(target, allow_closed=True)))
            except ToolError as error:
                if "not found" in str(error):
                    return {"status": {target: "not_found"}, "timed_out": False}
                raise

        def statuses():
            return {
                target: agent.status
                for target, agent in agents
                if isinstance(agent.status, dict)
                or agent.status in {"shutdown", "not_found"}
            }

        ready = statuses()
        if not ready:
            for _, agent in agents:
                agent.changed.clear()
            waits = [asyncio.create_task(agent.changed.wait()) for _, agent in agents]
            deadline = asyncio.get_running_loop().time() + timeout / 1000
            try:
                while not ready:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        break
                    done, _ = await asyncio.wait(
                        waits, timeout=remaining, return_when=asyncio.FIRST_COMPLETED
                    )
                    if not done:
                        break
                    ready = statuses()
                    for task in done:
                        waits.remove(task)
                    for _, agent in agents:
                        agent.changed.clear()
                    waits += [
                        asyncio.create_task(agent.changed.wait()) for _, agent in agents
                    ]
            finally:
                for task in waits:
                    task.cancel()
                await asyncio.gather(*waits, return_exceptions=True)
        return {"status": ready, "timed_out": not bool(ready)}

    async def resume_agent(self, arguments):
        self._validate_depth()
        agent = self._agent(arguments.get("id"), allow_closed=True)
        if agent.closed:
            self._validate_capacity()
            agent.closed = False
            self._set_status(agent, "pending_init")
        return {"status": agent.status}

    async def _close(self, agent):
        agent.closed = True
        if agent.task and not agent.task.done():
            agent.task.cancel()
            await asyncio.gather(agent.task, return_exceptions=True)
        errors = await asyncio.gather(
            *(
                self._close(child)
                for child in list(self.tree.values())
                if child.parent_id == agent.id and not child.closed
            ),
            return_exceptions=True,
        )
        try:
            cache = agent.request.get("_session_cache")
            if cache:
                close_session = self.request.get("_close_session")
                if close_session is None:
                    from .loop import close_session
                await close_session(cache)
        except Exception as error:
            errors.append(error)
        finally:
            self._set_status(agent, "shutdown")
        failures = [error for error in errors if isinstance(error, Exception)]
        if failures:
            raise ExceptionGroup("sub-agent cleanup failed", failures)

    async def close_agent(self, arguments):
        agent = self._agent(arguments.get("target"), allow_closed=True)
        previous = copy.deepcopy(agent.status)
        await self._close(agent)
        return {"previous_status": previous}

    async def close(self):
        errors = await asyncio.gather(
            *(
                self._close(agent)
                for agent in list(self.tree.values())
                if agent.parent_id == self.parent_id and not agent.closed
            ),
            return_exceptions=True,
        )
        failures = [error for error in errors if isinstance(error, Exception)]
        if failures:
            raise ExceptionGroup("sub-agent cleanup failed", failures)
