"""Original V4A header resolution helpers, bound to the local file backend."""

import re
from .todo import tool_error
from .path_security import has_traversal_component

def _file_ops_uses_host_paths(file_ops):
    return True


_V4A_SINGLE_HEADER_RE = re.compile(r'^(\*\*\*\s*(Update|Add|Delete)\s+File:\s*)(.+)$', re.MULTILINE)

_V4A_MOVE_HEADER_RE = re.compile(r'^(\*\*\*\s*Move\s+File:\s*)(.+?)\s*->\s*(.+)$', re.MULTILINE)

def _rewrite_v4a_patch_paths_for_host(patch: str, path_to_resolved: dict, path_to_entry: dict,
                                      file_ops) -> str:
    """Rewrite V4A file headers to the resolved host paths (host backends only).

    The shell layer must patch the SAME files ``patch_tool`` resolved for
    locking/staleness, not re-resolve a relative header against its own cwd
    (which can differ — the git-worktree cwd bug). Delete and Move headers take
    ``path_to_entry``: they act on a symlink itself, never on its target.
    """
    if not _file_ops_uses_host_paths(file_ops):
        return patch

    def _res(raw: str, entry: bool = False) -> str:
        raw = raw.strip()
        return (path_to_entry if entry else path_to_resolved).get(raw) or raw

    patch = _V4A_SINGLE_HEADER_RE.sub(
        lambda m: f"{m.group(1)}{_res(m.group(3), entry=m.group(2) == 'Delete')}", patch)
    return _V4A_MOVE_HEADER_RE.sub(
        lambda m: f"{m.group(1)}{_res(m.group(2), entry=True)} -> {_res(m.group(3), entry=True)}", patch)

def _collect_v4a_header_paths(patch: str) -> tuple[list[str], list[str], list[str]] | str:
    """Extract every path named in V4A headers, rejecting ``..`` traversal.

    Returns ``(all_paths, content_write_paths, entry_paths)`` or a tool_error
    string. Header paths come from patch CONTENT (more attacker-influenceable
    than ``path=``, which keeps its legitimate ``..`` use). Move headers check
    BOTH endpoints; only Update/Add write text and feed the binary-document
    guard; Delete and Move act on the directory entry (``entry_paths``).
    """

    headers = [(m.group(3), m.group(2) in ("Update", "Add")) for m in _V4A_SINGLE_HEADER_RE.finditer(patch)]
    headers += [(g, False) for m in _V4A_MOVE_HEADER_RE.finditer(patch) for g in (m.group(2), m.group(3))]
    paths: list[str] = []
    content_paths: list[str] = []
    entry_paths: list[str] = []
    for raw, writes_text in headers:
        v4a_path = raw.strip()
        if has_traversal_component(v4a_path):
            return tool_error(
                f"V4A patch header contains '..' traversal: {v4a_path!r}. "
                "Use the agent's cwd-relative path (no '..') or an absolute "
                "path in '*** Update File:' / '*** Add File:' / "
                "'*** Delete File:' / '*** Move File:' headers.")
        paths.append(v4a_path)
        (content_paths if writes_text else entry_paths).append(v4a_path)
    return paths, content_paths, entry_paths
