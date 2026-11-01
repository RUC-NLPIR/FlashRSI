"""Pure-Python Pi-compatible resources and built-in tools.

The module is deliberately self-contained so a selected Agent Snapshot can
load it without importing the FlashRSI package.  ``AgentLoop`` owns model
transport and event emission; this module owns the stable Pi resource and
tool contracts used by that loop.
"""

from .controls import PendingMessageQueue
from .loop import NativePiResult, compact, navigate_session, run
from .resources import (
    ResourceBundle,
    default_tools,
    expand_prompt_template,
    load_resources,
    substitute_template,
)
from .tools import ToolResult, execute_tool, tool_schemas

PI_BASELINE = "v1.4.0@4a080252f06caf63a525d7873c5d94d3c23887e0"

__all__ = [
    "PI_BASELINE",
    "PendingMessageQueue",
    "ResourceBundle",
    "default_tools",
    "NativePiResult",
    "compact",
    "navigate_session",
    "ToolResult",
    "execute_tool",
    "load_resources",
    "expand_prompt_template",
    "substitute_template",
    "tool_schemas",
    "run",
]
