"""Initial world state and metadata, ported from the pinned Codex core.

Sources: core/src/context/world_state/{environment,permissions}.rs,
prompts/src/permissions_instructions.rs, core/src/{responses_metadata,turn_metadata}.rs,
git-utils/src/{info,status,fsmonitor,git_process}.rs.
All refer to be6e8eac029b183056b7e4402879f15d2c85f61b.
Linux timezone lookup follows iana-time-zone 0.1.65/src/tz_linux.rs,
as locked by that commit; date/zone fallback is session/turn_context.rs.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
import re
import signal
import sys
import uuid
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

_ASSETS = Path(__file__).with_name("context_assets")
_GIT_TIMEOUT = 5
_GIT_STATUS_RUNS = {}


async def _git_output(cwd, args, *, fsmonitor=False, probe=False):
    """git-utils/{info,git_process}.rs: bounded, cancellable metadata reads."""
    command = ["git", "-c", "safe.bareRepository=explicit"]
    environment = None
    if not probe:
        command += [
            "-c",
            "core.hooksPath=" + ("NUL" if os.name == "nt" else "/dev/null"),
            "-c",
            "core.fsmonitor=" + str(fsmonitor).lower(),
        ]
        environment = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    process = None
    completed = False
    try:
        process = await asyncio.create_subprocess_exec(
            *command,
            *args,
            cwd=cwd,
            env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
        stdout, _ = await asyncio.wait_for(process.communicate(), _GIT_TIMEOUT)
        completed = True
        return stdout if process.returncode == 0 else None
    except (OSError, asyncio.TimeoutError):
        return None
    finally:
        if process is not None and not completed:
            try:
                if os.name == "posix":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            await process.communicate()


async def _builtin_fsmonitor(cwd):
    # git-utils/fsmonitor.rs: preserve only Git's built-in daemon, never a
    # repository-selected executable. Probe effective configuration each time.
    raw = await _git_output(
        cwd, ["config", "--null", "--get", "core.fsmonitor"], probe=True
    )
    if raw is None or not raw.endswith(b"\0") or b"\0" in raw[:-1]:
        return False
    try:
        value = raw[:-1].decode("utf-8")
    except UnicodeDecodeError:
        return False
    if value.lower() in {"true", "yes", "on"}:
        enabled = True
    elif value.lower() in {"false", "no", "off"}:
        enabled = False
    else:
        enabled = (
            await _git_output(
                cwd,
                [
                    "config",
                    "--null",
                    "--type=bool",
                    "--fixed-value",
                    "--get",
                    "core.fsmonitor",
                    value,
                ],
                probe=True,
            )
        ) == b"true\0"
    if not enabled:
        return False
    options = await _git_output(cwd, ["version", "--build-options"], probe=True)
    return options is not None and any(
        line.strip() == b"feature: fsmonitor--daemon" for line in options.split(b"\n")
    )


async def _git_has_changes(cwd, repo_root):
    # git-utils/status.rs shares only concurrently running status queries.
    key = (asyncio.get_running_loop(), repo_root.resolve())
    shared = _GIT_STATUS_RUNS.get(key)
    if shared is None or shared[0].done():

        async def status():
            output = await _git_output(
                cwd, ["status", "--porcelain"], fsmonitor=await _builtin_fsmonitor(cwd)
            )
            return None if output is None else bool(output)

        shared = [asyncio.create_task(status()), 0]
        _GIT_STATUS_RUNS[key] = shared
    shared[1] += 1
    try:
        return await asyncio.shield(shared[0])
    finally:
        shared[1] -= 1
        if not shared[1]:
            if _GIT_STATUS_RUNS.get(key) is shared:
                _GIT_STATUS_RUNS.pop(key)
            if not shared[0].done():
                shared[0].cancel()
            await asyncio.gather(shared[0], return_exceptions=True)


async def _workspace_git_metadata(cwd, repo_root):
    queries = [
        asyncio.create_task(query)
        for query in (
            _git_output(cwd, ["rev-parse", "HEAD"]),
            _git_output(cwd, ["remote", "-v"]),
            _git_has_changes(cwd, repo_root),
        )
    ]
    try:
        head, remotes, changes = await asyncio.gather(*queries)
    finally:
        for query in queries:
            if not query.done():
                query.cancel()
        await asyncio.gather(*queries, return_exceptions=True)
    data = {}
    try:
        value = head.decode("utf-8").strip() if head is not None else ""
        if value:
            data["latest_git_commit_hash"] = value
    except UnicodeDecodeError:
        pass
    urls = {}
    try:
        for line in remotes.decode("utf-8").splitlines() if remotes is not None else []:
            if not line.endswith(" (fetch)"):
                continue
            fetch = line.removesuffix(" (fetch)")
            separator = "\t" if "\t" in fetch else " "
            name, found, url = fetch.partition(separator)
            if found and url.lstrip():
                urls[name] = url.lstrip()
    except UnicodeDecodeError:
        pass
    if urls:
        data["associated_remote_urls"] = dict(sorted(urls.items()))
    if changes is not None:
        data["has_changes"] = changes
    return data


class TurnMetadataState:
    """core/turn_metadata.rs: per-turn, nonblocking Git enrichment lifecycle."""

    def __init__(self, cwd):
        self.cwd = Path(cwd)
        base = self.cwd if self.cwd.is_dir() else self.cwd.parent
        self.repo_root = next(
            (path for path in (base, *base.parents) if (path / ".git").exists()),
            None,
        )
        self.workspaces = {}
        self.task = None

    def __deepcopy__(self, memo):
        # Native cloned turn contexts retain an Arc to the same live metadata.
        # A child/new user turn installs a fresh state in run_session.
        return self

    def start(self):
        if self.repo_root is not None and self.task is None:
            self.task = asyncio.create_task(self._enrich())

    async def _enrich(self):
        data = await _workspace_git_metadata(self.cwd, self.repo_root)
        if data:
            self.workspaces = {str(self.repo_root): data}

    async def close(self):
        task, self.task = self.task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


def message(role, content):
    if isinstance(content, str):
        content = [{"type": "input_text", "text": content}]
    return {
        "type": "message",
        "id": "msg_" + str(uuid.uuid4()),
        "role": role,
        "content": content,
    }


def _xml(value):
    return escape(str(value), {'"': "&quot;", "'": "&apos;"})


def _timezone_words(line):
    """iana-time-zone's lazy OpenWRT IterWords; quotes do not escape bytes."""
    while line := line.lstrip():
        if line.startswith("#"):
            return
        if line[0] in {"'", '"'}:
            end = line.find(line[0], 1)
            if end < 0:
                raise ValueError("BrokenQuote")
            yield line[1:end]
            line = line[end + 1 :]
        else:
            parts = line.split(None, 1)
            yield parts[0]
            line = parts[1] if len(parts) > 1 else ""


def _linux_timezone():
    try:
        target = os.readlink(Path("/etc/localtime"))
        target.encode("utf-8")
        for prefix in (
            "/usr/share/zoneinfo/",
            "../usr/share/zoneinfo/",
            "/etc/zoneinfo/",
            "../etc/zoneinfo/",
        ):
            if target.startswith(prefix):
                return target[len(prefix) :]
    except (OSError, UnicodeError):
        pass
    try:
        return Path("/etc/timezone").read_bytes().decode("utf-8").rstrip()
    except (OSError, UnicodeError):
        pass
    try:
        in_system_section, timezone = False, None
        with Path("/etc/config/system").open("rb") as source:
            for line in source:
                words = _timezone_words(line.decode("utf-8"))
                keyword = next(words, None)
                if keyword == "config":
                    in_system_section = (
                        next(words, None) == "system" and next(words, None) is None
                    )
                elif in_system_section and keyword == "option":
                    key = next(words, None)
                    if key in {"zonename", "timezone"}:
                        value = next(words, None)
                        if value is not None and next(words, None) is None:
                            if key == "zonename":
                                return value
                            timezone = value
        return timezone
    except (OSError, UnicodeError, ValueError):
        return None


def timezone_name():
    if sys.platform.startswith("linux"):
        # The locked Linux crate reads system configuration, independent of TZ.
        return _linux_timezone()
    if os.environ.get("TZ"):
        return os.environ["TZ"].removeprefix(":")
    localtime = str(Path("/etc/localtime").resolve())
    if "/zoneinfo/" in localtime:
        return localtime.split("/zoneinfo/", 1)[1]
    zone = datetime.datetime.now().astimezone().tzinfo
    return getattr(zone, "key", None) or str(zone)


def writable_roots(cwd, settings):
    options = settings.get("sandbox_workspace_write", {})
    roots = [str(Path(cwd).resolve())]
    roots.extend(
        str(Path(root).resolve()) for root in options.get("writable_roots", [])
    )
    if (
        os.name == "posix"
        and not options.get("exclude_slash_tmp", False)
        and Path("/tmp").is_dir()
    ):
        roots.append(str(Path("/tmp").resolve()))
    tmpdir = os.environ.get("TMPDIR", "")
    if (
        not options.get("exclude_tmpdir_env_var", False)
        and tmpdir
        and Path(tmpdir).is_absolute()
    ):
        roots.append(str(Path(tmpdir).resolve()))
    return sorted(set(roots))


def permissions(settings, cwd, model):
    mode = settings.get("sandbox_mode", "workspace-write")
    if mode not in {"danger-full-access", "workspace-write", "read-only"}:
        raise ValueError(f"Unsupported Codex sandbox mode: {mode}")
    messages = model.info.get("model_messages") or {}
    permission_messages = messages.get("permissions") or {}
    name = mode.replace("-", "_")
    template = permission_messages.get(name)
    if template is None:
        template = (
            (_ASSETS / "permissions/sandbox_mode" / (name + ".md")).read_text().rstrip()
        )
    network = mode == "danger-full-access" or settings.get(
        "sandbox_workspace_write", {}
    ).get("network_access", False)
    sections = []
    sandbox_text = template.replace(
        "{{ network_access }}", "enabled" if network else "restricted"
    )
    if sandbox_text:
        sections.append(sandbox_text)
    # The framework's noninteractive execution contract fixes Never.
    policy = settings.get("approval_policy", "never")
    if policy != "never":
        raise ValueError(
            "Python Codex headless execution requires approval_policy=never"
        )
    approval = (messages.get("approvals") or {}).get("never")
    if approval is None:
        approval = (_ASSETS / "permissions/approval_policy/never.md").read_text()
    sections.append(approval)
    if mode == "workspace-write":
        roots = writable_roots(cwd, settings)
        label = "root is" if len(roots) == 1 else "roots are"
        sections.append(
            f" The writable {label} " + ", ".join(f"`{r}`" for r in roots) + "."
        )
    body = ""
    for section in sections:
        if not body.endswith("\n"):
            body += "\n"
        body += section
    if not body.endswith("\n"):
        body += "\n"
    return "<permissions instructions>" + body + "</permissions instructions>"


def environment_context(settings, cwd):
    cwd = str(Path(cwd).resolve())
    mode = settings.get("sandbox_mode", "workspace-write")
    shell = Path(
        settings.get("_shell_path")
        or settings.get("shell")
        or os.environ.get("SHELL", "/bin/sh")
    ).name
    zone = timezone_name()
    if zone is None:
        current_date = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        zone = "Etc/UTC"
    else:
        current_date = datetime.datetime.now().astimezone().date().isoformat()
    current_date = settings.get("_current_date") or current_date
    zone = settings.get("_timezone") or zone
    filesystem = (
        "<filesystem><workspace_roots><root>" + _xml(cwd) + "</root></workspace_roots>"
    )
    if mode == "danger-full-access":
        filesystem += '<permission_profile type="disabled"><file_system type="unrestricted" /></permission_profile>'
    else:
        entries = [("<special>:root</special>", "read")]
        if mode == "workspace-write":
            entries.append(("<path>" + _xml(cwd) + "</path>", "write"))
            options = settings.get("sandbox_workspace_write", {})
            if not options.get("exclude_slash_tmp", False):
                entries.append(("<special>:slash_tmp</special>", "write"))
            if not options.get("exclude_tmpdir_env_var", False):
                entries.append(("<special>:tmpdir</special>", "write"))
            entries.extend(
                ("<path>" + _xml(p) + "</path>", "write")
                for p in options.get("writable_roots", [])
            )
            entries.extend(
                ("<path>" + _xml(Path(cwd) / name) + "</path>", "read")
                for name in (".git", ".agents", ".codex")
            )
        filesystem += (
            '<permission_profile type="managed"><file_system type="restricted">'
        )
        filesystem += "".join(
            f'<entry access="{access}">{path}</entry>' for path, access in entries
        )
        filesystem += "</file_system></permission_profile>"
    filesystem += "</filesystem>"
    return (
        "<environment_context>\n"
        f"  <cwd>{_xml(cwd)}</cwd>\n"
        f"  <shell>{_xml(shell)}</shell>\n"
        f"  <current_date>{_xml(current_date)}</current_date>\n"
        f"  <timezone>{_xml(zone)}</timezone>\n"
        f"  {filesystem}\n"
        "</environment_context>"
    )


def initial_context(items, settings, cwd, model):
    developer, user, other = [], [], []
    instructions = settings.get("developer_instructions")
    if instructions:
        developer.append({"type": "input_text", "text": instructions})
    for item in items:
        role = item.get("role")
        texts = item.get("content", [])
        if any(is_hook_prompt(entry.get("text", "")) for entry in texts):
            other.append(item)
        elif role == "developer":
            developer.extend(texts)
        elif role == "user":
            user.extend(texts)
        else:
            other.append(item)
    developer.append({"type": "input_text", "text": permissions(settings, cwd, model)})
    user.append({"type": "input_text", "text": environment_context(settings, cwd)})
    return [message("developer", developer), message("user", user), *other]


def is_hook_prompt(text):
    # protocol/src/items.rs::parse_hook_prompt_fragment uses XML decoding, not
    # a substring marker; ordinary prose mentioning hooks stays a user prompt.
    try:
        element = ElementTree.fromstring(text.strip())
    except ElementTree.ParseError:
        return False
    return element.tag == "hook_prompt" and bool(element.get("hook_run_id", "").strip())


def request_metadata(settings):
    thread_id = settings["_thread_id"]
    session_id = settings.get("_session_id", thread_id)
    turn_id = settings["_turn_id"]
    installation_id = settings["_installation_id"]
    window_id = thread_id + ":" + str(settings.get("_window_number", 0))
    mode = settings.get("sandbox_mode", "workspace-write")
    data = {
        "installation_id": installation_id,
        "session_id": session_id,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "window_id": window_id,
        "request_kind": "turn",
    }
    if settings.get("_forked_from_thread_id"):
        data["forked_from_thread_id"] = settings["_forked_from_thread_id"]
    if settings.get("_parent_thread_id"):
        data["parent_thread_id"] = settings["_parent_thread_id"]
    if settings.get("_parent_turn_id"):
        data["parent_turn_id"] = settings["_parent_turn_id"]
    if settings.get("_parent_thread_id"):
        data["subagent_kind"] = settings.get("_subagent_kind", "thread_spawn")
    data["thread_source"] = "subagent" if settings.get("_parent_thread_id") else "user"
    data["sandbox"] = (
        "none"
        if mode == "danger-full-access"
        else {"darwin": "seatbelt", "linux": "seccomp", "win32": "windows_sandbox"}.get(
            sys.platform, "none"
        )
    )
    if settings.get("_code_mode_tool_names"):
        data["code_mode_tool_names"] = settings["_code_mode_tool_names"]
    data["turn_started_at_unix_ms"] = settings["_started_at_unix_ms"]
    state = settings.get("_turn_metadata_state")
    if state is not None and state.workspaces:
        data["workspaces"] = state.workspaces
    result = {
        "session_id": session_id,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "x-codex-installation-id": installation_id,
        "x-codex-window-id": window_id,
        "x-codex-turn-metadata": json.dumps(
            data, ensure_ascii=True, separators=(",", ":")
        ),
    }
    if settings.get("_parent_thread_id"):
        result["x-codex-parent-thread-id"] = settings["_parent_thread_id"]
        result["x-openai-subagent"] = "collab_spawn"
    if settings.get("_parent_turn_id"):
        result["parent_turn_id"] = settings["_parent_turn_id"]
    return result


def assistant_text(item, *, plan_mode=False):
    # stream_events_utils.rs + utils/stream-parser/src/citation.rs: literal,
    # non-nested hidden citations, including an unclosed final citation.
    if item.get("type") != "message" or item.get("role") != "assistant":
        return None
    text = "".join(
        c.get("text", "")
        for c in item.get("content", [])
        if c.get("type") == "output_text"
    )
    text = re.sub(
        r"<oai-mem-citation>.*?(?:</oai-mem-citation>|\Z)", "", text, flags=re.S
    )
    if plan_mode:
        text = re.sub(
            r"<proposed_plan>.*?(?:</proposed_plan>|\Z)", "", text, flags=re.S
        )
    return text if text.strip() else None
