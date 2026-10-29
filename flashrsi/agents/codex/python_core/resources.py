"""Resource-context port of Codex rust-v0.147.0, commit be6e8eac029b.

AGENTS, skills, plugins, hooks and MCP resources are read from the selected
Snapshot home. Model/permission/environment context is assembled by the loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import stat
import uuid
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote_from_bytes
from xml.sax.saxutils import escape, quoteattr

import yaml

from .hooks import HookBlocked, Hooks, HookStopped, message
from .mcp import Mcp
from .memory import Memories
from .plugins import load_plugins


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    discovery_path: Path
    root: Path
    scope: str
    implicit: bool
    enabled: bool
    dependencies: dict
    plugin: object = None


def _project_directories(cwd, settings):
    markers = settings.get("project_root_markers", [".git"])
    if not markers:
        return [cwd]
    directories = [cwd, *cwd.parents]
    for index, directory in enumerate(directories):
        if any((directory / marker).exists() for marker in markers):
            return list(reversed(directories[: index + 1]))
    return [cwd]


def _read_doc(directory, filenames, remaining=None):
    for name in filenames:
        path = directory / name
        if path.is_file():
            data = path.read_bytes()
            if remaining is not None:
                data = data[:remaining]
            return data.decode(errors="replace"), len(data)
    return "", 0


def _frontmatter(contents, path):
    lines = contents.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing YAML frontmatter delimited by ---")
    end = next(
        (index for index, line in enumerate(lines[1:], 1) if line.strip() == "---"),
        None,
    )
    if end is None or end == 1:
        raise ValueError("missing YAML frontmatter delimited by ---")
    source = "\n".join(lines[1:end])
    try:
        metadata = yaml.safe_load(source)
    except yaml.YAMLError:
        repaired = []
        # Upstream accepts common unquoted third-party prose with `: `.
        for line in source.splitlines():
            match = re.match(r"^(name|description|argument-hint):(\s+)(.+)$", line)
            if match and match[3][:1] not in "'\"|>" and ": " in match[3]:
                line = match[1] + ": " + json.dumps(match[3])
            repaired.append(line)
        metadata = yaml.safe_load("\n".join(repaired))
    if not isinstance(metadata, dict):
        raise ValueError("skill frontmatter must be a mapping")
    name = " ".join(str(metadata.get("name") or "").split()) or path.parent.name
    description = " ".join(str(metadata.get("description") or "").split())
    if not name or len(name) > 64:
        raise ValueError("invalid name: must contain 1–64 characters")
    if not description:
        raise ValueError("missing field `description`")
    return name, description


def _skill_mentions(prompt):
    """skills/src/mentions.rs: linked mentions suppress plain-name fallback."""
    common_env = {
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "PWD",
        "TMPDIR",
        "TEMP",
        "TMP",
        "LANG",
        "TERM",
        "XDG_CONFIG_HOME",
    }
    plain, paths = set(), set()
    for match in re.finditer(
        r"\[\$([A-Za-z0-9_:-]+)\][ \t\r\n\v\f]*\(([^)]*)\)|\$([A-Za-z0-9_:-]+)",
        prompt,
    ):
        name = match[1] or match[3]
        if name.upper() in common_env:
            continue
        path = match[2].strip() if match[2] is not None else ""
        if path:
            paths.add(path.removeprefix("skill://").replace("\\", "/"))
        else:
            plain.add(name)
    return plain, paths


def _skill_enabled(name, path, home, rules):
    enabled = True
    for rule in rules:
        selector_path, selector_name = rule.get("path"), rule.get("name")
        # Native ignores entries with both/neither selectors. Path selectors
        # identify SKILL.md itself, while names are trimmed before comparison.
        if (selector_path is None) == (selector_name is None):
            continue
        matches = (
            (home / selector_path).resolve() == path
            if selector_path is not None
            else selector_name.strip() == name
        )
        if matches:
            enabled = rule.get("enabled", True)
    return enabled


# core-skills/src/loader{,/discovery}.rs and file-system/src/lib.rs.
# A skill is an inventory file, not a leaf: nested skills remain discoverable.
_SKILL_SCAN_DEPTH = 6
_SKILL_SCAN_DIRECTORIES = 2000
_SKILL_SCAN_ENTRIES = 20_000
_SKILL_WALK_RESPONSE_BYTES = 4 * 1024 * 1024
_SKILL_WALK_ITEM_OVERHEAD = 64


def _skill_path_uri(path):
    # url::Url::from_file_path / PathUri::join encode POSIX filename bytes.
    return "file://" + quote_from_bytes(os.fsencode(path), safe="/!$&'()*+,-.:;=@_~")


def _walk_skill_files(root, *, follow_symlinks, direct_children, emit):
    """The native breadth-first inventory, with its directory/entry/byte bounds."""
    try:
        root = root.resolve(strict=True)
    except (OSError, RuntimeError):
        root = root.absolute()
    try:
        if not stat.S_ISDIR(root.stat().st_mode):
            return []
    except FileNotFoundError:
        return []
    except OSError as error:
        emit(
            {
                "type": "warning",
                "message": f"failed to walk skills root {root}: {error}",
            }
        )
        return []
    files, errors = [], []
    queue = deque([(root, 0)])
    visited = {root}
    directory_count, entry_count, response_bytes = 1, 0, 0
    max_depth = 2 if direct_children else _SKILL_SCAN_DEPTH
    truncated = False

    def reserve(content_bytes):
        nonlocal response_bytes, truncated
        total = response_bytes + content_bytes + _SKILL_WALK_ITEM_OVERHEAD
        if total > _SKILL_WALK_RESPONSE_BYTES:
            truncated = True
            return False
        response_bytes = total
        return True

    def record_error(path, error):
        # Rust io::Error displays the OS message and code, without repeating
        # Python's filename. Error entries consume the same response budget.
        text = (
            f"{error.strerror} (os error {error.errno})"
            if isinstance(error, OSError)
            else str(error)
        )
        if not reserve(len(_skill_path_uri(path).encode()) + len(text.encode())):
            return False
        errors.append(f"failed to scan skill path {_skill_path_uri(path)}: {text}")
        return True

    stopped = False
    while queue and not stopped:
        directory, depth = queue.popleft()
        try:
            entries = sorted(directory.iterdir())
        except OSError as error:
            if not record_error(directory, error):
                break
            continue
        for path in entries:
            if entry_count == _SKILL_SCAN_ENTRIES:
                truncated = True
                stopped = True
                break
            entry_count += 1
            try:
                metadata = path.lstat()
                is_symlink = stat.S_ISLNK(metadata.st_mode)
                if is_symlink:
                    metadata = path.stat()
            except OSError as error:
                if not record_error(path, error):
                    stopped = True
                    break
                continue
            is_directory = stat.S_ISDIR(metadata.st_mode)
            is_file = stat.S_ISREG(metadata.st_mode)
            if is_symlink and (not follow_symlinks or not is_directory):
                continue
            if not is_directory and not is_file:
                continue
            if not reserve(len(_skill_path_uri(path).encode())):
                stopped = True
                break
            if is_file and path.name == "SKILL.md":
                if not direct_children or path.parent.parent == root:
                    files.append(path)
            if not is_directory or depth >= max_depth or path.name.startswith("."):
                continue
            try:
                identity = path.resolve(strict=True) if follow_symlinks else path
            except (OSError, RuntimeError) as error:
                if not record_error(path, error):
                    stopped = True
                    break
                continue
            if identity in visited:
                continue
            visited.add(identity)
            if directory_count == _SKILL_SCAN_DIRECTORIES:
                truncated = True
            else:
                directory_count += 1
                queue.append((path, depth + 1))
    for error in errors:
        emit({"type": "warning", "message": error})
    if truncated:
        emit(
            {
                "type": "warning",
                "message": f"skills scan reached its traversal limit (root: {root})",
            }
        )
    return files


class Resources:
    def __init__(self, home: Path, cwd: Path, settings: dict, emit, environment=None):
        self.home, self.cwd = Path(home).resolve(), Path(cwd).resolve()
        self.settings, self.emit = settings, emit
        self.memories = Memories(self.home, settings)
        self.environment = {
            **(os.environ if environment is None else environment),
            "CODEX_HOME": str(self.home),
        }
        self.settings.setdefault(
            "_session_id", self.settings.get("_thread_id", str(uuid.uuid4()))
        )
        self.settings.setdefault("_turn_id", "0")
        self.assets = self.home / "python_core/resource_assets"
        self.plugins = load_plugins(self.home, settings)
        self.hooks = Hooks(
            self.home, self.cwd, settings, emit, self.environment, self.plugins
        )
        self.mcp = Mcp(
            self.home, self.cwd, settings, emit, self.environment, self.plugins
        )
        self.mcp.hooks = self.hooks
        self.skills = []
        self.prompts = []
        self.notify_processes = []

    def _agents(self):
        user = self.settings.get("user_instructions")
        if user is None:
            for name in ("AGENTS.override.md", "AGENTS.md"):
                user, _ = _read_doc(self.home, [name])
                user = user.strip()
                if user:
                    break
        user = user if user and user.strip() else ""
        project = []
        remaining = self.settings.get("project_doc_max_bytes", 32768)
        filenames = list(
            dict.fromkeys(
                [
                    "AGENTS.override.md",
                    "AGENTS.md",
                    *self.settings.get("project_doc_fallback_filenames", []),
                ]
            )
        )
        for directory in _project_directories(self.cwd, self.settings):
            if remaining <= 0:
                break
            text, length = _read_doc(
                directory, [name for name in filenames if name], remaining
            )
            if text.strip():
                project.append(text)
                remaining -= length
        text = user
        if project:
            text += ("\n\n--- project-doc ---\n\n" if user else "") + "\n\n".join(
                project
            )
        if not text:
            return None
        directory = f" for {self.cwd}" if project else ""
        return message(
            f"# AGENTS.md instructions{directory}\n\n<INSTRUCTIONS>\n{text}\n</INSTRUCTIONS>",
            "user",
        )

    def _install_system_skills(self):
        if not self.settings.get("skills", {}).get("bundled", {}).get("enabled", True):
            return False
        source = self.assets / "system_skills"
        if not source.is_dir():
            raise ValueError(
                "Snapshot is missing the pinned Python core system skill assets"
            )
        fingerprint = hashlib.sha256()
        for path in sorted(source.rglob("*")):
            if path.is_file():
                fingerprint.update(path.relative_to(source).as_posix().encode())
                fingerprint.update(path.read_bytes())
        target = self.home / "skills/.system"
        marker = target / ".codex-python-system-skills.marker"
        digest = fingerprint.hexdigest()
        if not marker.is_file() or marker.read_text() != digest:
            if target.is_symlink():
                target.unlink()
            elif target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
            marker.write_text(digest)
        return True

    def _load_skills(self):
        bundled = self._install_system_skills()
        directories = _project_directories(self.cwd, self.settings)
        # Config layers are visited from cwd toward the root even when a
        # project's config contents are disabled by its trust level. The
        # separate .agents roots are visited from project root toward cwd.
        roots = [
            (directory / ".codex/skills", "repo", None)
            for directory in reversed(directories)
        ]
        roots.append((self.home / "skills", "user", None))
        ambient = self.environment.get("HOME")
        if ambient:
            roots.append((Path(ambient) / ".agents/skills", "user", None))
        if bundled:
            roots.append((self.home / "skills/.system", "system", None))
        for plugin in self.plugins:
            roots.extend((root, "user", plugin) for root in plugin.skill_roots)
        for directory in directories:
            roots.append((directory / ".agents/skills", "repo", None))
        seen, skills = set(), []
        for root, scope, plugin in roots:
            direct_children = bool(plugin and plugin.manifest.get("$schema"))
            for path in _walk_skill_files(
                root,
                follow_symlinks=scope != "system",
                direct_children=direct_children,
                emit=self.emit,
            ):
                try:
                    canonical = path.resolve()
                    if direct_children and not canonical.is_relative_to(
                        plugin.root.resolve()
                    ):
                        continue
                    if canonical in seen:
                        continue
                    seen.add(canonical)
                    name, description = _frontmatter(canonical.read_text(), canonical)
                    metadata_path = canonical.parent / "agents/openai.yaml"
                    metadata = (
                        yaml.safe_load(metadata_path.read_text()) or {}
                        if metadata_path.is_file()
                        else {}
                    )
                    policy = metadata.get("policy", {})
                    products = policy.get("products", [])
                    if products and "codex" not in products:
                        continue
                    if plugin:
                        name = plugin.name + ":" + name
                    enabled = _skill_enabled(
                        name,
                        canonical,
                        self.home,
                        self.settings.get("skills", {}).get("config", []),
                    )
                    skills.append(
                        Skill(
                            name,
                            description,
                            canonical,
                            path.absolute(),
                            root.resolve(),
                            scope,
                            policy.get("allow_implicit_invocation", True),
                            enabled,
                            metadata.get("dependencies", {}),
                            plugin,
                        )
                    )
                except (ValueError, OSError, RuntimeError, yaml.YAMLError) as error:
                    self.emit(
                        {
                            "type": "warning",
                            "message": f"Failed to load skill {path}: {error}",
                        }
                    )
        rank = {"repo": 0, "user": 1, "system": 2, "admin": 3}
        self.skills = sorted(
            skills, key=lambda skill: (rank[skill.scope], skill.name, str(skill.path))
        )

    def _skill_catalog(self):
        if self.settings.get("skills", {}).get("include_instructions") is False:
            return None
        rank = {"system": 0, "admin": 1, "repo": 2, "user": 3}
        skills = sorted(
            (skill for skill in self.skills if skill.enabled and skill.implicit),
            key=lambda skill: (rank[skill.scope], skill.name, str(skill.path)),
        )
        if not skills:
            return None
        prompts = json.loads((self.assets / "skills_prompt.json").read_text())
        model_info = self.settings.get("_model_info", {})
        window = model_info.get(
            "context_window", self.settings.get("model_context_window")
        )
        limit = max(1, int(window) * 2 // 100) if window and int(window) > 0 else 8000
        cost = (
            (lambda text: (len(text.encode()) + 3) // 4)
            if window and int(window) > 0
            else len
        )

        def render(locators, budget):
            descriptions = [
                skill.description
                if len(skill.description) <= 1024
                else skill.description[:1021] + "..."
                for skill in skills
            ]
            minimum = [
                f"- {skill.name}: (file: {path})"
                for skill, path in zip(skills, locators, strict=True)
            ]
            full = [
                f"- {skill.name}: {desc} (file: {path})"
                for skill, desc, path in zip(
                    skills, descriptions, locators, strict=True
                )
            ]
            if sum(cost(line + "\n") for line in full) <= budget:
                return full, 0, 0
            allocations = [0] * len(skills)
            if sum(cost(line + "\n") for line in minimum) > budget:
                lines, used = [], 0
                for line in minimum:
                    if used + cost(line + "\n") <= budget:
                        lines.append(line)
                        used += cost(line + "\n")
                return lines, len(skills) - len(lines), sum(map(len, descriptions))
            remaining = budget - sum(cost(line + "\n") for line in minimum)
            while True:
                changed = False
                for i, description in enumerate(descriptions):
                    if allocations[i] == len(description):
                        continue
                    prefix = description[: allocations[i]]
                    old = (
                        cost(minimum[i] + "\n")
                        if not prefix
                        else cost(
                            f"- {skills[i].name}: {prefix} (file: {locators[i]})\n"
                        )
                    )
                    prefix = description[: allocations[i] + 1]
                    delta = (
                        cost(f"- {skills[i].name}: {prefix} (file: {locators[i]})\n")
                        - old
                    )
                    if delta <= remaining:
                        allocations[i] += 1
                        remaining -= delta
                        changed = True
                if not changed:
                    break
            lines = [
                f"- {skill.name}: {desc[:count]} (file: {path})" if count else base
                for skill, desc, count, path, base in zip(
                    skills, descriptions, allocations, locators, minimum, strict=True
                )
            ]
            return (
                lines,
                0,
                sum(
                    len(desc) - count
                    for desc, count in zip(descriptions, allocations, strict=True)
                ),
            )

        # The host provider displays the discovery alias, while reading and
        # configuration identity continue to use the canonical skill path.
        lines, omitted, truncated = render(
            [str(skill.discovery_path) for skill in skills], limit
        )
        root_lines = []
        if omitted or truncated:
            roots = list(
                dict.fromkeys(skill.root for skill in self.skills if skill in skills)
            )
            aliases = {root: f"r{index}" for index, root in enumerate(roots)}
            proposed_roots = [
                f"- `{alias}` = `{root}`" for root, alias in aliases.items()
            ]
            overhead = cost(
                prompts["SKILLS_INTRO_WITH_ALIASES"]
                + "\n### Skill roots\n"
                + "\n".join(proposed_roots)
            ) - cost(prompts["SKILLS_INTRO_WITH_ABSOLUTE_PATHS"])
            paths = [
                f"{aliases[skill.root]}/{skill.discovery_path.relative_to(skill.root)}"
                for skill in skills
            ]
            proposed, missing, shortened = render(paths, max(0, limit - overhead))
            if (
                missing,
                shortened,
                sum(cost(line + "\n") for line in proposed) + overhead,
            ) < (omitted, truncated, sum(cost(line + "\n") for line in lines)):
                lines, root_lines, omitted, truncated = (
                    proposed,
                    proposed_roots,
                    missing,
                    shortened,
                )
        if omitted:
            self.emit(
                {
                    "type": "warning",
                    "message": f"Exceeded skills context budget. All skill descriptions were removed and {omitted} additional {'skill was' if omitted == 1 else 'skills were'} not included in the model-visible skills list.",
                }
            )
        elif truncated // len(skills) > 100:
            self.emit(
                {
                    "type": "warning",
                    "message": "Skill descriptions were shortened to fit the skills context budget. Codex can still see every skill, but some descriptions are shorter. Disable unused skills or plugins to leave more room for the rest.",
                }
            )
        intro = prompts[
            "SKILLS_INTRO_WITH_ALIASES"
            if root_lines
            else "SKILLS_INTRO_WITH_ABSOLUTE_PATHS"
        ]
        body = ["## Skills", intro]
        if root_lines:
            body.extend(["### Skill roots", *root_lines])
        body.extend(["### Available skills", *lines])
        if model_info.get("include_skills_usage_instructions", False):
            body.extend(
                [
                    "### How to use skills",
                    prompts[
                        "SKILLS_HOW_TO_USE_WITH_ALIASES"
                        if root_lines
                        else "SKILLS_HOW_TO_USE_WITH_ABSOLUTE_PATHS"
                    ],
                ]
            )
        return message(
            "<skills_instructions>\n" + "\n".join(body) + "\n</skills_instructions>"
        )

    async def start(self, router):
        self._load_skills()
        router.hooks = self.hooks
        await self.mcp.start(router)
        items = await self.memories.start(router)
        for item in (self._skill_catalog(), self._agents()):
            if item:
                items.append(item)
        if self.settings.get("_model_info", {}).get(
            "include_plugin_usage_instructions", False
        ) and any(plugin.skill_roots or plugin.mcp_servers for plugin in self.plugins):
            items.append(message((self.assets / "plugins_prompt.txt").read_text()))
        if self.settings.get("_subagent_kind") == "thread_spawn":
            role = self.settings.get("_agent_type", "default")
            contexts, _ = await self.hooks.run(
                "SubagentStart",
                matcher_input=role,
                agent_id=self.settings["_thread_id"],
                agent_type=role,
            )
        else:
            contexts, _ = await self.hooks.run(
                "SessionStart", matcher_input="startup", source="startup"
            )
        return items + contexts

    async def before_prompt(self, prompt: str):
        self.prompts.append(prompt)
        contexts, _ = await self.hooks.run("UserPromptSubmit", prompt=prompt)
        plain, paths = _skill_mentions(prompt)
        counts = Counter(skill.name for skill in self.skills if skill.enabled)
        selected = [
            skill
            for skill in self.skills
            if skill.enabled
            and (str(skill.path) in paths or str(skill.discovery_path) in paths)
        ]
        selected.extend(
            skill
            for skill in self.skills
            if skill.enabled
            and skill not in selected
            and skill.name in plain
            and counts[skill.name] == 1
        )
        for skill in selected:
            # MCP dependencies inform native optional installation/approval;
            # an unavailable dependency does not prevent reading the skill.
            contents = skill.path.read_text()
            encoded = contents.encode()
            if len(encoded) > 8000:
                contents = encoded[:8000].decode(errors="ignore")
                self.emit(
                    {
                        "type": "warning",
                        "message": f"Skill `{skill.name}` exceeded the main prompt context limit and was truncated.",
                    }
                )
            name = skill.name.encode()[:256].decode(errors="ignore")
            path = str(skill.path).encode()[:1024].decode(errors="ignore")
            contexts.append(
                message(
                    f"<skill>\n<name>{name}</name>\n<path>{path}</path>\n{contents}\n</skill>",
                    "user",
                )
            )
        plugin_names = set(re.findall(r"\[@[^\]]+\]\s*\(plugin://([^)]*)\)", prompt))
        for plugin in self.plugins:
            if plugin.config_name not in plugin_names:
                continue
            name = (
                plugin.manifest.get("interface", {}).get("displayName") or plugin.name
            ).strip()
            lines = [f"Capabilities from the `{name}` plugin:"]
            if plugin.skill_roots:
                lines.append(
                    f"- Skills from this plugin are prefixed with `{plugin.name}:`."
                )
            servers = sorted(set(plugin.mcp_servers) & self.mcp.servers.keys())
            if servers:
                lines.append(
                    "- MCP servers from this plugin available in this session: "
                    + ", ".join(f"`{name}`" for name in servers)
                    + "."
                )
            if len(lines) > 1:
                lines.append(
                    "Use these plugin-associated capabilities to help solve the task."
                )
                text = "\n".join(lines)
                suffix = "\n- Additional plugin capabilities omitted to fit the context limit."
                if len(text.encode()) > 4096:
                    text = (
                        text.encode()[: 4096 - len(suffix.encode())].decode(
                            errors="ignore"
                        )
                        + suffix
                    )
                contexts.append(message(text))
        return prompt, contexts

    async def after_turn(self, output: str, status: str):
        if status != "finished":
            return []
        try:
            child = self.settings.get("_subagent_kind") == "thread_spawn"
            fields = {}
            if child:
                role = self.settings.get("_agent_type", "default")
                fields = {
                    "matcher_input": role,
                    "agent_id": self.settings["_thread_id"],
                    "agent_type": role,
                    "agent_transcript_path": self.settings.get("_transcript_path"),
                    "transcript_path": self.settings.get("_parent_transcript_path"),
                }
            _, decisions = await self.hooks.run(
                "SubagentStop" if child else "Stop",
                stop_hook_active=self.hooks.stop_hook_active,
                last_assistant_message=output or None,
                **fields,
            )
        except HookStopped:
            self.hooks.stop_hook_active = False
            return []
        fragments = [
            {
                "type": "input_text",
                "text": f"<hook_prompt hook_run_id={quoteattr(result['_run_id'])}>{escape(self.hooks._spill(result['reason'], 2500))}</hook_prompt>",
            }
            for result in decisions
            if result.get("decision") == "block" and result.get("reason")
        ]
        continuations = (
            [{"type": "message", "role": "user", "content": fragments}]
            if fragments
            else []
        )
        self.hooks.stop_hook_active = bool(continuations)
        if continuations:
            return continuations
        argv = self.settings.get("notify") or []
        if argv:
            payload = {
                "type": "agent-turn-complete",
                "thread-id": self.settings.get(
                    "_thread_id", self.settings["_session_id"]
                ),
                "turn-id": str(self.settings.get("_turn_id", "0")),
                "cwd": str(self.cwd),
                "client": "codex_exec",
                "input-messages": self.prompts,
                "last-assistant-message": output or None,
            }
            try:
                process = await asyncio.create_subprocess_exec(
                    *argv,
                    json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    cwd=self.cwd,
                    env=self.environment,
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                    start_new_session=True,
                )
            except OSError as error:
                self.emit(
                    {"type": "warning", "message": f"failed to start notify: {error}"}
                )
            else:
                self.notify_processes.append(process)
        return []

    async def close(self):
        try:
            if self.settings.get("_subagent_kind") != "thread_spawn":
                await self.hooks.run("SessionEnd", reason="other")
        except HookBlocked as error:
            self.emit({"type": "warning", "message": str(error)})
        finally:
            await self.mcp.close()
            for process in self.notify_processes:
                try:
                    await asyncio.wait_for(process.wait(), 1)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
