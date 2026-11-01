"""Pi v1.4.0 structured system-prompt semantics; see PROMPT_SOURCES.json."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping


def _value(skill, *names, default=None):
    for name in names:
        if isinstance(skill, Mapping) and name in skill:
            return skill[name]
        if hasattr(skill, name):
            return getattr(skill, name)
    return default


def _escape(value):
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def format_skills(skills, reader="read"):
    visible = [
        skill
        for skill in skills
        if not _value(
            skill, "disable_model_invocation", "disableModelInvocation", default=False
        )
    ]
    if not visible:
        return ""
    hint = {
        "read": "Use the read tool to load a skill's file when the task matches its description.",
        "bash": "Use bash to load a skill's file when the task matches its description.",
    }.get(reader, "Load a skill's file when the task matches its description.")
    lines = [
        "\n\nThe following skills provide specialized instructions for specific tasks.",
        hint,
        "When a skill file references a relative path, resolve it against the skill directory (parent of SKILL.md / dirname of the path) and use that absolute path in tool commands.",
        "",
        "<available_skills>",
    ]
    for skill in visible:
        lines.extend(
            [
                "  <skill>",
                f"    <name>{_escape(_value(skill, 'name'))}</name>",
                f"    <description>{_escape(_value(skill, 'description'))}</description>",
                f"    <location>{_escape(_value(skill, 'path', 'filePath'))}</location>",
                "  </skill>",
            ]
        )
    return "\n".join([*lines, "</available_skills>"])


def build_system_prompt_sections(
    *,
    cwd,
    selected_tools=None,
    hidden_tools=(),
    tool_snippets=None,
    tool_guidelines=None,
    prompt_guidelines=(),
    custom_prompt=None,
    append_system_prompt="",
    sections=None,
    context_files=(),
    skills=(),
    reference_root=None,
) -> dict[str, str]:
    selected = list(
        ["read", "bash", "edit", "write"] if selected_tools is None else selected_tools
    )
    declared = [name for name in selected if name not in hidden_tools]
    snippets = tool_snippets or {}
    guidelines = tool_guidelines or {}
    extra_sections = sections or {}
    for name in extra_sections:
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", name) or name == "preamble":
            raise ValueError(f"Invalid system prompt section name: {name}")
    result = {}
    if custom_prompt:
        result["preamble"] = custom_prompt
    else:
        result["preamble"] = (
            "You are an expert coding assistant operating inside pi, a coding agent harness. You help users by reading files, executing commands, editing code, and writing new files."
        )
        visible = [name for name in declared if snippets.get(name)]
        tools = (
            "\n".join(f"- {name}: {snippets[name]}" for name in visible)
            if visible
            else "(none)"
        )
        result["tools"] = (
            tools
            + "\n\nIn addition to the tools above, you may have access to other custom tools depending on the project."
        )
        rules = []

        def add(rule):
            rule = rule.strip()
            if rule and rule not in rules:
                rules.append(rule)

        if ("bash" in declared or "powershell" in declared) and not any(
            name in declared for name in ("grep", "find", "ls")
        ):
            add(
                "Use bash or PowerShell for file operations like listing, searching, and finding files"
                if "bash" in declared and "powershell" in declared
                else "Use PowerShell for file operations like listing, searching, and finding files"
                if "powershell" in declared
                else "Use bash for file operations like ls, rg, find"
            )
        for name in declared:
            for rule in guidelines.get(name, []):
                add(rule)
        for rule in prompt_guidelines:
            add(rule)
        add("Be concise in your responses")
        add("Show file paths clearly when working with files")
        result["rules"] = "\n".join(f"- {rule}" for rule in rules)
        root = (
            Path(reference_root)
            if reference_root is not None
            else Path(__file__).parent / "reference"
        )
        template = json.loads(
            (Path(__file__).parent / "PROMPT_SOURCES.json").read_text()
        )["docs_template"]
        result["docs"] = (
            template.replace("{README}", str(root / "README.md"))
            .replace("{DOCS}", str(root / "docs"))
            .replace("{EXAMPLES}", str(root / "examples"))
        )
    if append_system_prompt:
        result["addendum"] = append_system_prompt
    if context_files:
        result["project_context"] = "\n\n".join(
            [
                "Project-specific instructions and guidelines:",
                *[
                    f'<project_instructions path="{item["path"]}">\n{item["content"]}\n</project_instructions>'
                    for item in context_files
                ],
            ]
        )
    readers = ("read", "bash")
    reader = next((name for name in readers if name in declared), None)
    if reader is None and any(name in selected for name in readers):
        reader = "indirect"
    if reader and skills:
        rendered = format_skills(skills, reader).strip()
        if rendered:
            result["skills"] = rendered
    result["cwd"] = str(cwd).replace("\\", "/")
    for name, text in extra_sections.items():
        if text:
            result[name] = text
    return {
        name: text if name == "preamble" else f"<{name}>\n{text}\n</{name}>"
        for name, text in result.items()
    }


def render_sections(sections: Mapping[str, Any]) -> str:
    return "\n\n".join(text for text in sections.values() if text)


def diff_system_prompt_sections(previous, current):
    patch = {name: text for name, text in current.items() if previous.get(name) != text}
    patch.update({name: None for name in previous if name not in current})
    return patch or None
