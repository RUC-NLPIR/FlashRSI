from __future__ import annotations
import re

_HOUSEKEEPING_TOOLS = frozenset({"memory", "todo_list", "skill_manage", "session_search"})


_LINE_IS_REPLY_TOOLS = _HOUSEKEEPING_TOOLS | {"setup_beat"}
