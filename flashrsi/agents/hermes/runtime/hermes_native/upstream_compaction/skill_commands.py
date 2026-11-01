from __future__ import annotations
import contextlib, contextvars, copy, hashlib, json, logging, math, re, threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import unquote_plus, urlparse
logger=logging.getLogger(__name__)


_SKILL_INVOCATION_PREFIX = "[IMPORTANT: The user has invoked the "


_SINGLE_SKILL_MARKER = "The full skill content is loaded below.]"


_SINGLE_SKILL_INSTRUCTION = "The user has provided the following instruction alongside the skill invocation: "


_RUNTIME_NOTE = "\n\n[Runtime note:"


_BUNDLE_MARKER = " skill bundle,"


_BUNDLE_USER_INSTRUCTION = "\nUser instruction: "


_BUNDLE_FIRST_SKILL_BLOCK = "\n\n[Loaded as part of the "


_SKILL_NAME_RE = re.compile(re.escape(_SKILL_INVOCATION_PREFIX) + r'"([^"]*)"')


_AUTO_LOAD_PREFIX = '[IMPORTANT: The "'


_AUTO_LOAD_SUFFIX_RE = re.compile(r'" skill is auto-loaded\. Follow its instructions for this session\.\]')


_SKILL_DIR_NOTE_END = "then run them with the terminal tool using the absolute path."


SKILL_EXCERPT_JOINT = "\x1e"


def extract_user_instruction_from_skill_message(content: Any) -> Optional[str]:
    """Recover the user's instruction from a slash-skill-expanded turn: the
    string unchanged when it is NOT scaffolding, the extracted instruction when
    the scaffolding carried one, or ``None`` for a bare ``/skill`` invocation."""
    if not isinstance(content, str):
        return None
    if not content.startswith(_SKILL_INVOCATION_PREFIX):
        return content
    if _BUNDLE_MARKER in content:
        # Bundles put the instruction before the loaded skills: FIRST marker is the user's.
        return _cut_after(content, _BUNDLE_USER_INSTRUCTION, _BUNDLE_FIRST_SKILL_BLOCK, content.find)
    if _SINGLE_SKILL_MARKER in content:
        # The instruction follows the skill body (which may quote the marker): LAST marker is the user's.
        return _cut_after(content, _SINGLE_SKILL_INSTRUCTION, _RUNTIME_NOTE, content.rfind)
    return None


def _describe_auto_loaded_skill_turn(content: str) -> Optional[str]:
    """``[IMPORTANT: The "X" skill is auto-loaded. …]`` + payload(s) + typed text
    -> the typed text.

    ``_hmwa_auto_load_skills`` builds each payload with ``_build_skill_message``
    (activation header, body, then the skill-directory footer note) and appends the
    user's text as the final block. The footer's closing sentence is the reliable
    payload-end marker: the user's text is what follows the LAST footer. A header
    quoted inside a body (a skill embedding the scaffold in an example) carries no
    footer, so it cannot end the payload early. ``/<skill>`` renders when no user
    text follows, matching the single-skill describer's bare-invocation shape."""
    if not content.startswith(_AUTO_LOAD_PREFIX):
        return None
    name_match = re.match(re.escape(_AUTO_LOAD_PREFIX) + r'([^"]*)"', content)
    name = name_match.group(1) if name_match else ""
    # The payload footer ends with this exact sentence (_build_skill_message); the
    # user's text is the last thing after the FINAL footer in the message.
    footer_end = content.rfind(_SKILL_DIR_NOTE_END)
    if footer_end == -1:
        return f"/{name}" if name else None
    tail = content[footer_end + len(_SKILL_DIR_NOTE_END):].lstrip()
    while block_end := next((end for start, end in _TRAILING_BLOCK_ENDS if tail.startswith(start)), None):
        cut = tail.find(block_end)
        tail = tail[cut + len(block_end):].lstrip() if cut >= 0 else ""
    if not tail.strip():
        return f"/{name}" if name else None
    return " ".join(tail.split()) or None


def describe_skill_invocation(content: Any, separator: str = " — ") -> Optional[str]:
    """Render a slash-skill-expanded turn the way the user typed it:
    ``"/work — fix the title leak"``, ``"/work"`` for a bare invocation, or
    ``None`` when *content* is not scaffolding. ``separator=" "`` gives the
    literal invocation as typed (chat transcripts).

    A gateway auto-load scaffold (channel-bound skill on a new session) is also
    scaffolding: the typed request follows the skill payload, so it renders as
    that request — the header/body never reaches a preview or a title (#48359).
    """
    if not isinstance(content, str):
        return None
    if content.startswith(_AUTO_LOAD_PREFIX):
        return _describe_auto_loaded_skill_turn(content)
    if not content.startswith(_SKILL_INVOCATION_PREFIX):
        return None
    match = _SKILL_NAME_RE.match(content)
    name = (match.group(1) if match else "").strip()
    # Bundle headers already carry their typed "/a /b" keys; a single skill is a bare name.
    label = name if name.startswith("/") else f"/{name}"
    instruction = extract_user_instruction_from_skill_message(content)
    if instruction and instruction is not content:
        # An excerpt (head + tail joined by SKILL_EXCERPT_JOINT) can put the
        # joint inside the span — keep only the side the marker was found on.
        instruction = " ".join(instruction.split(SKILL_EXCERPT_JOINT)[0].split())
        if instruction:
            return f"{label}{separator}{instruction}" if name else instruction
    return label if name else None


_AUTO_LOAD_HEADER_RE = re.compile(re.escape(_AUTO_LOAD_PREFIX) + r'([^"]*)' + _AUTO_LOAD_SUFFIX_RE.pattern)


_BUNDLE_LOADED_RE = re.compile(r"^Skills loaded: (.+)$", re.MULTILINE)


def skills_loaded_by_scaffold(content: Any) -> list[str]:
    """Skill names a slash-skill, bundle/stacked or gateway auto-load turn carries inline; ``[]`` for any
    other text. Only a complete activation header counts, so typed text that merely starts like one
    (``[IMPORTANT: The "config" file is broken]``) is not mistaken for a skill load."""
    if not isinstance(content, str):
        return []
    if content.startswith(_AUTO_LOAD_PREFIX):
        return [m.group(1) for m in _AUTO_LOAD_HEADER_RE.finditer(content)] if _AUTO_LOAD_HEADER_RE.match(content) else []
    if not content.startswith(_SKILL_INVOCATION_PREFIX):
        return []
    header = content.split("\n", 1)[0]
    if _BUNDLE_MARKER in header:
        loaded = _BUNDLE_LOADED_RE.search(content)
        return [n.strip() for n in loaded.group(1).split(",") if n.strip()] if loaded else []
    match = _SKILL_NAME_RE.match(content)
    return [match.group(1)] if header.endswith(_SINGLE_SKILL_MARKER) and match and match.group(1) else []


def _cut_after(message: str, marker: str, stop_marker: str, find) -> Optional[str]:
    """Text between *marker* (located with ``find``) and *stop_marker*, stripped; None if absent/empty."""
    marker_idx = find(marker)
    if marker_idx < 0:
        return None
    return message[marker_idx + len(marker):].split(stop_marker, 1)[0].strip() or None


_SUPPORTING_FILES_END = "/scripts/foo.js`)."


_TRAILING_BLOCK_ENDS = (("[Skill config (", "\n]"), ("[Skill setup note: ", "]\n\n"),
                        ("[This skill has supporting files", _SUPPORTING_FILES_END))
