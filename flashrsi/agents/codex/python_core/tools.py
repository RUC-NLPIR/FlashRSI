"""Codex tool registry/spec/dispatch port, pinned to rust-v0.147.0.

Provenance: core/src/tools/{spec_plan,router,registry,context}.rs,
core/src/tools/handlers/*_spec.rs and tools/src/tool_config.rs. Schemas are
constructed for the resolved model and feature state, rather than loaded from
a captured request. Static grammar/Seatbelt assets retain upstream bytes.
"""

from __future__ import annotations

import asyncio
import base64
import copy
import inspect
import json
import os
import signal
import sys
import time
from pathlib import Path

from .apply_patch import PatchError, apply_patch, parse_patch, patch_command
from .hooks import HookBlocked, HookFeedback
from .shell import Shell, ToolError, exec_response_text, io_error, truncate
from .tool_search import ToolSearch, default_search_text, loadable_spec, search_spec


def schema(kind, description=None, **fields):
    result = {"type": kind}
    if description is not None:
        result["description"] = description
    result.update(fields)
    return result


def object_schema(properties, required=None, description=None):
    result = schema("object", description, properties=dict(sorted(properties.items())))
    if required is not None:
        result["required"] = required
    result["additionalProperties"] = False
    return result


def function(name, description, properties, required):
    return {
        "type": "function",
        "name": name,
        "description": description,
        "strict": False,
        "parameters": object_schema(properties, required),
    }


def approval_properties(additional=False):
    """shell_spec::create_approval_parameters."""
    values = ["use_default", "require_escalated"]
    description = "Per-command sandbox override. Defaults to `use_default`; use `require_escalated` for unsandboxed execution."
    properties = {
        "sandbox_permissions": schema("string", description, enum=values),
        "justification": schema(
            "string",
            "User-facing approval question for `require_escalated`; omit otherwise.",
        ),
        "prefix_rule": schema(
            "array",
            'Reusable approval prefix for `cmd`, only with `sandbox_permissions: "require_escalated"`; for example ["git", "pull"].',
            items=schema("string"),
        ),
    }
    if additional:
        values.insert(1, "with_additional_permissions")
        properties["sandbox_permissions"]["description"] = (
            "Per-command sandbox override. Defaults to `use_default`; use `with_additional_permissions` with `additional_permissions`, or `require_escalated` for unsandboxed execution."
        )
        properties["additional_permissions"] = object_schema(
            {
                "network": object_schema(
                    {
                        "enabled": schema(
                            "boolean",
                            "True requests network access; false or omitted requests none.",
                        )
                    },
                    description="Network access request.",
                ),
                "file_system": object_schema(
                    {
                        "read": schema(
                            "array",
                            "Absolute paths to grant read access; omit when none are needed.",
                            items=schema("string"),
                        ),
                        "write": schema(
                            "array",
                            "Absolute paths to grant write access; omit when none are needed.",
                            items=schema("string"),
                        ),
                    },
                    description="Filesystem access request.",
                ),
            },
            description='Sandboxed filesystem or network access for this command; only with `sandbox_permissions: "with_additional_permissions"`.',
        )
    return properties


def shell_spec(login=True, additional=False):
    properties = {
        "command": schema("string", "Shell script to run in the user's default shell."),
        "workdir": schema(
            "string", "Working directory for the command. Defaults to the turn cwd."
        ),
        "timeout_ms": schema(
            "number", "Maximum command runtime. Defaults to 10000 ms."
        ),
        **approval_properties(additional),
    }
    if login:
        properties["login"] = schema(
            "boolean",
            "True runs with login shell semantics; false disables them. Defaults to true.",
        )
    return function(
        "shell_command",
        "Runs a shell command and returns its output.\n- Always set the `workdir` param when using the shell_command function. Do not use `cd` unless absolutely necessary.",
        properties,
        ["command"],
    )


def exec_spec(
    login=True, additional=False, include_environment_id=False, include_shell=True
):
    properties = {
        "cmd": schema("string", "Shell command to execute."),
        "workdir": schema(
            "string", "Working directory for the command. Defaults to the turn cwd."
        ),
        "tty": schema(
            "boolean",
            "True allocates a PTY for the command; false or omitted uses plain pipes.",
        ),
        "yield_time_ms": schema(
            "number",
            "Wait before yielding output. Defaults to 10000 ms; effective range is 250-30000 ms.",
        ),
        "max_output_tokens": schema(
            "number",
            "Output token budget. Defaults to 10000 tokens; larger requests may be capped by policy.",
        ),
        **approval_properties(additional),
    }
    if include_shell:
        properties["shell"] = schema(
            "string", "Shell binary to launch. Defaults to the user's default shell."
        )
    if login:
        properties["login"] = schema(
            "boolean",
            "True runs the shell with -l/-i semantics; false disables them. Defaults to true.",
        )
    if include_environment_id:
        properties["environment_id"] = schema(
            "string",
            "Environment id from <environment_context>. Omit to use the primary environment.",
        )
    return function(
        "exec_command",
        "Runs a command in a PTY, returning output or a session ID for ongoing interaction.",
        properties,
        ["cmd"],
    )


def stdin_spec():
    return function(
        "write_stdin",
        "Writes characters to an existing unified exec session and returns recent output.",
        {
            "session_id": schema(
                "number", "Identifier of the running unified exec session."
            ),
            "chars": schema(
                "string",
                "Bytes to write to stdin. Defaults to empty, which polls without writing.",
            ),
            "yield_time_ms": schema(
                "number",
                "Wait before yielding output. Non-empty writes default to 250 ms and cap at 30000 ms; empty polls wait 5000-300000 ms by default.",
            ),
            "max_output_tokens": schema(
                "number",
                "Output token budget. Defaults to 10000 tokens; larger requests may be capped by policy.",
            ),
        },
        ["session_id"],
    )


def plan_spec():
    return function(
        "update_plan",
        "Updates the task plan.\nProvide an optional explanation and a list of plan items, each with a step and status.\nAt most one step can be in_progress at a time.\n",
        {
            "explanation": schema(
                "string", "Optional explanation for this plan update."
            ),
            "plan": schema(
                "array",
                "The list of steps",
                items=object_schema(
                    {
                        "step": schema("string", "Task step text."),
                        "status": schema(
                            "string",
                            "Step status.",
                            enum=["pending", "in_progress", "completed"],
                        ),
                    },
                    ["step", "status"],
                ),
            ),
        },
        ["plan"],
    )


def patch_spec(include_environment_id=False):
    definition = (
        Path(__file__).with_name("tool_assets") / "apply_patch.lark"
    ).read_text()
    if include_environment_id:
        definition = definition.replace(
            "start: begin_patch hunk+ end_patch",
            'start: begin_patch environment_id? hunk+ end_patch\nenvironment_id: "*** Environment ID: " filename LF',
        )
    return {
        "type": "custom",
        "name": "apply_patch",
        "description": "The `apply_patch` tool can be used to edit files. This is a FREEFORM tool, so do not wrap the patch in JSON.",
        "format": {"type": "grammar", "syntax": "lark", "definition": definition},
    }


def image_spec(original=False, include_environment_id=False):
    properties = {"path": schema("string", "Local filesystem path to an image file.")}
    if original:
        properties["detail"] = schema(
            "string",
            "Image detail level. Defaults to `high`; use `original` to preserve exact resolution.",
            enum=["high", "original"],
        )
    if include_environment_id:
        properties["environment_id"] = schema(
            "string",
            "Environment id from <environment_context>. Omit to use the primary environment.",
        )
    return function(
        "view_image",
        "View a local image file from the filesystem when visual inspection is needed. Use this for images already available on disk.",
        properties,
        ["path"],
    )


def user_input_spec(default_mode=False):
    option = object_schema(
        {
            "label": schema("string", "User-facing label (1-5 words)."),
            "description": schema(
                "string", "One short sentence explaining impact/tradeoff if selected."
            ),
        },
        ["label", "description"],
    )
    question = object_schema(
        {
            "id": schema(
                "string", "Stable identifier for mapping answers (snake_case)."
            ),
            "header": schema(
                "string", "Short header label shown in the UI (12 or fewer chars)."
            ),
            "question": schema("string", "Single-sentence prompt shown to the user."),
            "options": schema(
                "array",
                'Provide 2-3 mutually exclusive choices. Put the recommended option first and suffix its label with "(Recommended)". Do not include an "Other" option in this list; the client will add a free-form "Other" option automatically.',
                items=option,
            ),
        },
        ["id", "header", "question", "options"],
    )
    modes = "Default or Plan" if default_mode else "Plan"
    return function(
        "request_user_input",
        f"Request user input for one to three short questions and wait for the response. This tool is only available in {modes} mode.",
        {
            "questions": schema(
                "array",
                "Questions to show the user. Prefer 1 and do not exceed 3",
                items=question,
            ),
        },
        ["questions"],
    )


def call_name(call: dict) -> str:
    name = call.get("name", "")
    namespace = call.get("namespace")
    return f"{namespace}.{name}" if namespace and namespace != "functions" else name


class ToolRouter:
    def __init__(
        self, settings: dict, cwd: Path, model, emit, environment: dict | None = None
    ):
        self.settings, self.cwd, self.model, self.emit = (
            settings,
            Path(cwd),
            model,
            emit,
        )
        self._environment = copy.deepcopy(environment)
        self.shell = Shell(settings, self.cwd, model.info, environment)
        self.hooks = None
        self._specs: list[dict] = []
        self._handlers = {}
        self._parallel = set()
        self._pass_call = set()
        self._kinds = {}
        self._exec_hooks = {}
        self._deferred = {}
        self._search = None
        self.code_mode = None
        self.search_enabled = bool(
            model.info.get("supports_search_tool", False)
            and settings.get("_provider_capabilities", {}).get("namespace_tools", True)
        )
        features = settings.get("features", {})
        info = model.info
        login = settings.get("allow_login_shell", True)
        approvals = features.get("exec_permission_approvals", False)
        shell_enabled = features.get("shell_tool", True)
        unified = features.get("unified_exec", True) and (
            not features.get("shell_zsh_fork", False)
            or features.get("unified_exec_zsh_fork", False)
        )
        shell_type = info.get("shell_type", "default")
        if (
            shell_type in {"default", "local"}
            or shell_type == "unified_exec"
            and not unified
        ):
            shell_type = "shell_command"
        if unified:
            shell_type = "unified_exec"
        if shell_enabled:
            if shell_type == "unified_exec":
                self.register(
                    "exec_command",
                    exec_spec(login, approvals),
                    self._exec,
                    parallel=True,
                )
                self.register("write_stdin", stdin_spec(), self._stdin, parallel=True)
                self.register("shell_command", None, self._shell)
            elif shell_type != "disabled":
                self.register(
                    "shell_command",
                    shell_spec(login, approvals),
                    self._shell,
                    parallel=True,
                )
        if settings.get("update_plan_enabled", True):
            self.register("update_plan", plan_spec(), self._plan)
        if settings.get("experimental_request_user_input_enabled", True):
            self.register(
                "request_user_input",
                user_input_spec(features.get("default_mode_request_user_input", False)),
                self._request_input,
            )
        from .context_budget import enabled

        if enabled(settings, "token_budget"):
            self.register(
                "new_context",
                function(
                    "new_context",
                    "Start a new context window. Does not clear, reset, or otherwise affect environment state.",
                    {},
                    None,
                ),
                self._new_context,
            )
            self.register(
                "get_context_remaining",
                function(
                    "get_context_remaining",
                    "Get the remaining tokens in the current context window.",
                    {},
                    None,
                ),
                self._get_context_remaining,
                parallel=True,
            )
        if info.get("apply_patch_tool_type") is not None:
            self.register("apply_patch", patch_spec(), self._patch, kind="custom")
        if features.get("view_image", True):
            self.register(
                "view_image",
                image_spec(info.get("supports_image_detail_original", False)),
                self._image,
                parallel=True,
            )
        default_web_mode = (
            "live"
            if self.shell.sandbox.mode == "danger-full-access"
            or self.shell.sandbox.network
            else "cached"
        )
        web_mode = settings.get(
            "web_search", settings.get("web_search_mode", default_web_mode)
        )
        if web_mode not in {"disabled", None, False}:
            spec = {
                "type": "web_search",
                "external_web_access": web_mode in {"live", "indexed"},
            }
            if web_mode == "indexed":
                spec["indexed_web_access"] = True
            if info.get("web_search_tool_type") == "text_and_image":
                spec["search_content_types"] = ["text", "image"]
            for key in ("filters", "user_location", "search_context_size"):
                value = settings.get("web_search_config", {}).get(key)
                if value is not None:
                    spec[key] = copy.deepcopy(value)
            self._specs.append(spec)

    @property
    def specs(self) -> list[dict]:
        from .code_mode_spec import specs

        return specs(self.raw_specs, self.settings, self.model, self._deferred)

    @property
    def raw_specs(self) -> list[dict]:
        # Core MCP resource tools precede the plan/input/image tools; discovery
        # and API-hosted tools follow all registered direct local tools.
        resources = {
            "list_mcp_resources",
            "list_mcp_resource_templates",
            "read_mcp_resource",
        }
        direct = [
            item
            for item in self._specs
            if item.get("type") != "web_search" and item.get("name") not in resources
        ]
        resource_specs = [item for item in self._specs if item.get("name") in resources]
        position = next(
            (
                index
                for index, item in enumerate(direct)
                if item.get("name")
                not in {"exec_command", "write_stdin", "shell_command", "shell"}
            ),
            len(direct),
        )
        direct[position:position] = sorted(
            resource_specs,
            key=lambda item: (
                "list_mcp_resources",
                "list_mcp_resource_templates",
                "read_mcp_resource",
            ).index(item["name"]),
        )
        if self._deferred:
            direct.append(
                search_spec(
                    [entry.get("source_info") for entry in self._deferred.values()],
                    omit_sources=self.settings.get("features", {}).get(
                        "deferred_tool_world_state", False
                    ),
                )
            )
        return copy.deepcopy(
            direct + [item for item in self._specs if item.get("type") == "web_search"]
        )

    def prepare_code_mode(self):
        if (
            self.model.info.get("tool_mode") in {"code_mode", "code_mode_only"}
            and self.code_mode is None
        ):
            from .code_mode import CodeMode

            self.code_mode = CodeMode(self)

    def code_mode_definitions(self):
        from .code_mode_spec import active_definitions

        deferred = [entry["output"] for entry in self._deferred.values()]
        return active_definitions(
            self.raw_specs + deferred, self.settings, augment=True
        )

    async def execute_nested(self, call):
        result = await self.execute(
            {**call, "_source": "code_mode", "_code_mode": True}
        )
        for item in result.pop("extra_items", []):
            if getattr(self, "append", None):
                self.append(item)
        return result.pop("_code_mode_result", result.get("output", ""))

    async def _new_context(self, args):
        self.settings["_new_context_window_requested"] = True
        return (
            "A new context window will start without summarizing conversation history."
        )

    async def _get_context_remaining(self, args):
        from .context_budget import token_status

        status = token_status(self.history, self.model, self.settings)
        left = status["base_window_tokens_remaining"]
        return (
            "You have "
            + (str(left) if left is not None else "unknown")
            + " tokens left in this context window."
        )

    def register(
        self,
        name,
        spec,
        async_handler,
        *,
        parallel=False,
        kind="function",
        deferred=False,
        search_text=None,
        source_info=None,
        pass_call=False,
    ):
        """Register full dispatch names; namespaces may be supplied as a group."""
        self._handlers[name] = async_handler
        self._kinds[name] = kind
        if pass_call:
            self._pass_call.add(name)
        if parallel:
            self._parallel.add(name)
        else:
            self._parallel.discard(name)
        if spec is None:
            return
        spec = copy.deepcopy(spec)
        if spec.get("type") == "namespace":
            namespace = spec["name"]
            for tool in spec["tools"]:
                alias = f"{namespace}.{tool['name']}"
                if name in {alias, f"{namespace}__{tool['name']}"}:
                    self._handlers[alias] = async_handler
                    self._kinds[alias] = kind
                    if pass_call:
                        self._pass_call.add(alias)
                    if parallel:
                        self._parallel.add(alias)
        if deferred and self.search_enabled:
            self._deferred[name] = {
                "search_text": search_text
                if search_text is not None
                else default_search_text(spec),
                "output": loadable_spec(spec),
                "source_info": copy.deepcopy(source_info),
            }
            self._search = None
            return
        self._deferred.pop(name, None)
        if spec.get("type") == "namespace":
            existing = next(
                (
                    item
                    for item in self._specs
                    if item.get("type") == "namespace" and item["name"] == spec["name"]
                ),
                None,
            )
            if existing is not None:
                for tool in spec["tools"]:
                    existing["tools"] = [
                        item
                        for item in existing["tools"]
                        if item["name"] != tool["name"]
                    ]
                    existing["tools"].append(tool)
                existing["tools"].sort(key=lambda item: item["name"])
                return
        self._specs = [
            item
            for item in self._specs
            if not (
                item.get("name") == spec.get("name")
                and item.get("type") == spec.get("type")
            )
        ]
        self._specs.append(spec)

    def supports_parallel(self, call: dict) -> bool:
        return (
            call.get("type") == "tool_search_call" or call_name(call) in self._parallel
        )

    async def _execute_search(self, call):
        call_id = call.get("call_id")
        if call.get("execution") != "client" or not isinstance(call_id, str):
            raise ValueError("tool_search calls require execution=client and call_id")
        self.emit(
            {"type": "tool_call_begin", "name": "tool_search", "call_id": call_id}
        )
        try:
            if not self._deferred:
                raise ToolError("unsupported call: tool_search")
            arguments = call.get("arguments")
            if not isinstance(arguments, dict):
                raise ToolError(
                    "failed to parse tool_search arguments: expected an object"
                )
            if "query" not in arguments:
                raise ToolError(
                    "failed to parse tool_search arguments: missing field `query`"
                )
            if not isinstance(arguments["query"], str):
                raise ToolError(
                    "failed to parse tool_search arguments: query must be a string"
                )
            query = arguments["query"].strip()
            limit = 8 if arguments.get("limit") is None else arguments["limit"]
            if type(limit) is not int or limit < 0 or limit > 2**64 - 1:
                raise ToolError(
                    "failed to parse tool_search arguments: limit must be a nonnegative integer"
                )
            if not query:
                raise ToolError("query must not be empty")
            if limit == 0:
                raise ToolError("limit must be greater than zero")
            if self._search is None:
                self._search = ToolSearch(self._deferred.values())
            return {
                "type": "tool_search_output",
                "call_id": call_id,
                "status": "completed",
                "execution": "client",
                "tools": self._search.search(query, limit),
            }
        except ToolError as error:
            return {
                "type": "function_call_output",
                "call_id": call_id,
                "output": str(error),
            }
        finally:
            self.emit(
                {"type": "tool_call_end", "name": "tool_search", "call_id": call_id}
            )

    async def _exec(self, arguments):
        intercepted = await self._intercept_patch(arguments, "exec_command")
        if intercepted is not None:
            policy = self.model.info.get(
                "truncation_policy", {"mode": "tokens", "limit": 10000}
            )
            policy_tokens = policy["limit"] // (4 if policy["mode"] == "bytes" else 1)
            maximum = arguments.get("max_output_tokens")
            model_maximum = min(10000 if maximum is None else maximum, policy_tokens)
            return {
                "_codex_exec": {
                    "wall_time_seconds": 0.0,
                    "output": truncate(
                        intercepted,
                        {"mode": "tokens", "limit": model_maximum},
                        formatted=True,
                    ),
                },
                "_codex_code_mode_result": {
                    "wall_time_seconds": 0.0,
                    "output": intercepted
                    if maximum is None
                    else truncate(
                        intercepted,
                        {"mode": "tokens", "limit": maximum},
                        formatted=True,
                    ),
                },
                "_skip_post_hook": True,
            }
        return {"_codex_exec": await self.shell.exec_command(arguments)}

    async def _stdin(self, arguments):
        return {"_codex_exec": await self.shell.write_stdin(arguments)}

    async def _shell(self, arguments):
        intercepted = await self._intercept_patch(arguments, "shell_command")
        if intercepted is not None:
            return {"_intercepted_patch": intercepted}
        return await self.shell.shell_command(arguments)

    async def _legacy_shell(self, arguments):
        intercepted = await self._intercept_patch(arguments, "shell")
        if intercepted is not None:
            return {"_intercepted_patch": intercepted}
        return await self.shell.shell_command(arguments, "shell")

    async def _intercept_patch(self, arguments, name):
        command, cwd = self.shell._command(arguments, name, sandboxed=False)
        try:
            selected = patch_command(command, cwd)
        except PatchError as error:
            raise ToolError(f"apply_patch verification failed: {error}") from error
        if selected is None:
            return None
        text, cwd = selected
        return await self._patch(text, cwd=cwd)

    async def _patch(self, text, *, cwd=None):
        cwd = self.cwd if cwd is None else cwd
        started = time.monotonic()
        if self.shell.sandbox.mode == "danger-full-access":
            output, success = await apply_patch(text, cwd)
        else:
            # The parent checks policy before work starts; the child writes
            # under Seatbelt, so path replacement cannot escape the policy.
            try:
                hunks, _ = parse_patch(text)
                for hunk in hunks:
                    self.shell.sandbox.authorize_file(cwd / hunk.path, True)
                    if hunk.move:
                        self.shell.sandbox.authorize_file(cwd / hunk.move, True)
            except (ValueError, OSError) as error:
                raise ToolError(f"apply_patch verification failed: {error}") from error
            argv = self.shell.sandbox.wrap(
                [sys.executable, "-B", str(Path(__file__).with_name("apply_patch.py"))]
            )
            process = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                env=self.shell.environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )
            try:
                stdout, stderr = await process.communicate(text.encode("utf-8"))
            except asyncio.CancelledError:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()
                raise
            if process.returncode:
                raise ToolError(stderr.decode("utf-8", "replace"))
            output, success = json.loads(stdout)
        if not success and output.startswith("apply_patch verification failed:"):
            raise ToolError(output)
        duration = int((time.monotonic() - started) * 10 + 0.5) / 10
        content = truncate(
            output,
            self.model.info.get(
                "truncation_policy", {"mode": "tokens", "limit": 10000}
            ),
        )
        sections = [
            f"Exit code: {0 if success else 1}",
            f"Wall time: {duration:g} seconds",
        ]
        if len(content.splitlines()) != len(output.splitlines()):
            sections.append(f"Total output lines: {len(output.splitlines())}")
        return "\n".join([*sections, "Output:", content])

    async def _plan(self, arguments):
        if (
            self.settings.get(
                "collaboration_mode", self.settings.get("mode", "default")
            )
            == "plan"
        ):
            raise ToolError(
                "update_plan is a TODO/checklist tool and is not allowed in Plan mode"
            )
        plan = arguments.get("plan")
        if not isinstance(plan, list):
            raise ToolError("failed to parse function arguments: missing field `plan`")
        for item in plan:
            if not isinstance(item, dict) or not isinstance(item.get("step"), str):
                raise ToolError(
                    "failed to parse function arguments: missing field `step`"
                )
            if item.get("status") not in {"pending", "in_progress", "completed"}:
                raise ToolError(
                    f"failed to parse function arguments: unknown variant `{item.get('status')}`, expected one of `pending`, `in_progress`, `completed`"
                )
        self.emit({"type": "plan_update", **arguments})
        return "Plan updated"

    async def _request_input(self, arguments):
        mode = self.settings.get(
            "collaboration_mode", self.settings.get("mode", "default")
        )
        if mode == "default" and not self.settings.get("features", {}).get(
            "default_mode_request_user_input", False
        ):
            raise ToolError("request_user_input is unavailable in Default mode")
        raise ToolError(
            "request_user_input requires a user-input capability; this session is headless"
        )

    async def _image(self, arguments):
        if "image" not in self.model.info.get("input_modalities", ["text", "image"]):
            raise ToolError(
                "view_image is not allowed because you do not support image inputs"
            )
        detail = arguments.get("detail", "high")
        if detail not in {"high", "original"}:
            raise ToolError(
                f"view_image.detail only supports `high` or `original`; omit `detail` for default high resized behavior, got `{detail}`"
            )
        if not isinstance(arguments.get("path"), str):
            raise ToolError("failed to parse function arguments: missing field `path`")
        path = self.cwd / arguments["path"]
        try:
            path.stat()
        except OSError as error:
            raise ToolError(
                f"unable to locate image at `{path}`: {io_error(error)}"
            ) from error
        if not path.is_file():
            raise ToolError(f"image path `{path}` is not a file")
        try:
            self.shell.sandbox.authorize_file(path, False)
            data = path.read_bytes()
        except OSError as error:
            raise ToolError(
                f"unable to read image at `{path}`: {io_error(error)}"
            ) from error
        if detail == "original" and not self.model.info.get(
            "supports_image_detail_original", False
        ):
            detail = "high"
        self.emit({"type": "image_view", "path": str(path)})
        # Upstream's history layer owns decoding/resizing. Preserve raw bytes at
        # this boundary so image normalization remains a single operation.
        return [
            {
                "type": "input_image",
                "image_url": "data:application/octet-stream;base64,"
                + base64.b64encode(data).decode("ascii"),
                "detail": detail,
            }
        ]

    async def execute(self, call: dict) -> dict:
        if self.code_mode is not None and call_name(call) in {"exec", "wait"}:
            return await self.code_mode.execute_call(call)
        if call.get("type") == "tool_search_call":
            return await self._execute_search(call)
        name = call_name(call)
        if name == "tool_search" and self._deferred:
            raise ValueError("tool_search handler received unsupported payload")
        custom = call.get("type") == "custom_tool_call"
        response = {
            "type": "custom_tool_call_output" if custom else "function_call_output",
            "call_id": call.get("call_id", call.get("id", "")),
        }
        extra_items = []
        try:
            handler = self._handlers.get(name)
            if handler is None:
                raise ToolError(
                    f"unsupported {'custom tool call' if custom else 'call'}: {name}"
                )
            expected_custom = self._kinds.get(name) == "custom"
            if custom != expected_custom:
                raise ToolError(f"{name} handler received unsupported payload")
            if custom:
                arguments = call.get("input", "")
            else:
                raw = call.get("arguments", "{}")
                try:
                    arguments = json.loads(raw) if isinstance(raw, str) else raw
                except (ValueError, TypeError) as error:
                    raise ToolError(
                        f"failed to parse function arguments: {error}"
                    ) from error
                if not isinstance(arguments, dict):
                    raise ToolError(
                        "failed to parse function arguments: expected an object"
                    )
                if arguments.get("environment_id") is not None:
                    raise ToolError(
                        f"unknown environment `{arguments['environment_id']}`"
                    )
            hook_name, hook_arguments, aliases = name, arguments, ()
            if name in {"exec_command", "shell_command"}:
                hook_name = "Bash"
                hook_arguments = {
                    "command": arguments.get(
                        "cmd" if name == "exec_command" else "command"
                    )
                }
            elif name == "apply_patch":
                hook_arguments, aliases = {"command": arguments}, ("Write", "Edit")
            elif name in {"spawn_agent", "multi_agent_v1.spawn_agent"}:
                hook_name, aliases = "spawn_agent", ("Agent",)
            if self.hooks is not None and name != "write_stdin":
                updated, items = await self.hooks.before_tool(
                    hook_name,
                    hook_arguments,
                    call_id=response["call_id"],
                    aliases=aliases,
                )
                extra_items.extend(items)
                if name in {"exec_command", "shell_command", "apply_patch"}:
                    if not isinstance(updated, dict) or not isinstance(
                        updated.get("command"), str
                    ):
                        raise ToolError(
                            "hook returned updatedInput without string field `command`"
                        )
                    if custom:
                        arguments = updated["command"]
                    else:
                        arguments = {
                            **arguments,
                            "cmd" if name == "exec_command" else "command": updated[
                                "command"
                            ],
                        }
                else:
                    arguments = updated
                hook_arguments = updated
            self.emit(
                {
                    "type": "tool_call_begin",
                    "name": name,
                    "call_id": response["call_id"],
                }
            )
            result = (
                handler(arguments, call=call)
                if name in self._pass_call
                else handler(arguments)
            )
            result = await result if inspect.isawaitable(result) else result
            code_mode_result = result
            hook_response = result
            hook_call_id = response["call_id"]
            run_post_hook = True
            if isinstance(result, dict) and "_intercepted_patch" in result:
                result = result["_intercepted_patch"]
                code_mode_result = result
                run_post_hook = False
            elif isinstance(result, dict) and "_codex_exec" in result:
                run_post_hook = not result.get("_skip_post_hook", False)
                executed = result["_codex_exec"]
                code_mode_result = result.get("_codex_code_mode_result", executed)
                result = exec_response_text(executed)
                hook_response = executed["output"]
                if name == "exec_command":
                    if "session_id" in executed:
                        self._exec_hooks[executed["session_id"]] = (
                            arguments["cmd"],
                            hook_call_id,
                        )
                        run_post_hook = False
                else:
                    pending = self._exec_hooks.get(arguments["session_id"])
                    run_post_hook = pending is not None and "session_id" not in executed
                    if run_post_hook:
                        command, hook_call_id = self._exec_hooks.pop(
                            arguments["session_id"]
                        )
                        hook_name, hook_arguments = "Bash", {"command": command}
            elif name in {"shell_command", "shell"} and isinstance(result, str):
                hook_response = result.split("Output:\n", 1)[-1]
            if self.hooks is not None and run_post_hook:
                updated, items = await self.hooks.after_tool(
                    hook_name,
                    hook_arguments,
                    hook_response,
                    call_id=hook_call_id,
                    aliases=aliases,
                )
                extra_items.extend(items)
                if name.startswith("mcp__") or isinstance(updated, HookFeedback):
                    result = updated
                    code_mode_result = updated
            if isinstance(result, dict) and result.get("type") in {
                "function_call_output",
                "custom_tool_call_output",
            }:
                response = result
            else:
                if isinstance(result, dict) and "mcp_result" in result:
                    code_mode_result = result["mcp_result"]
                    result = result["output"]
                response["output"] = (
                    result
                    if isinstance(result, (str, list))
                    else json.dumps(result, ensure_ascii=False, separators=(",", ":"))
                )
            if call.get("_code_mode"):
                if name == "apply_patch":
                    code_mode_result = {}
                elif name == "view_image" and isinstance(result, list):
                    code_mode_result = {
                        "image_url": result[0]["image_url"],
                        "detail": result[0]["detail"],
                    }
                elif name == "get_context_remaining":
                    from .context_budget import token_status

                    code_mode_result = {
                        "tokens_left": token_status(
                            self.history, self.model, self.settings
                        )["base_window_tokens_remaining"]
                    }
                response["_code_mode_result"] = code_mode_result
        except (ToolError, OSError, ValueError, HookBlocked) as error:
            if call.get("_code_mode"):
                raise
            response["output"] = str(error)
        if extra_items:
            response["extra_items"] = extra_items
        self.emit(
            {"type": "tool_call_end", "name": name, "call_id": response["call_id"]}
        )
        return response

    async def close(self):
        if self.code_mode is not None:
            await self.code_mode.close()
        self._exec_hooks.clear()
        await self.shell.close()

    async def reset_processes(self):
        """Interrupt a turn while retaining the registry and MCP bindings."""
        await self.shell.reset_processes()
        self._exec_hooks.clear()
