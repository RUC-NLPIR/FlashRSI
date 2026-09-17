"""Built-in harness adapters; selection by configuration belongs to the runner."""

from flashrsi.agents.claude_code import ClaudeCode
from flashrsi.agents.miniagent import MiniAgent

__all__ = ["ClaudeCode", "MiniAgent"]
