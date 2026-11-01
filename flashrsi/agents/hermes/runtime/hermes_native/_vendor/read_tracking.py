"""Original task-local read-dedup helpers from Hermes v0.22.5."""

import threading
import json
from .todo import tool_error
_read_tracker_lock = threading.RLock()
GUARDRAIL_REFUSAL_KEY = "guardrail_refusal"


import os


_READ_HISTORY_CAP = 500

_DEDUP_CAP = 1000

_READ_TIMESTAMPS_CAP = 1000

_FULL_WRITE_BASELINES_CAP = 1000

_NOT_FOUND_CAP = 500

def _cap_read_tracker_data(task_data: dict) -> None:
    """Enforce size caps on the per-task sub-containers. Call with ``_read_tracker_lock`` held."""
    # Caps are read at call time so tests can monkeypatch the module constants.
    for key, cap in (
        ("read_history", _READ_HISTORY_CAP),
        ("dedup", _DEDUP_CAP),
        ("dedup_hits", _DEDUP_CAP),
        ("dedup_generation_reads", _DEDUP_CAP),
        ("read_timestamps", _READ_TIMESTAMPS_CAP),
        ("read_coverage", _READ_TIMESTAMPS_CAP),
        ("full_write_baselines", _FULL_WRITE_BASELINES_CAP),
        ("blind_patches", _FULL_WRITE_BASELINES_CAP),
        ("not_found", _NOT_FOUND_CAP)):
        container = task_data.get(key)
        if container is not None and len(container) > cap:
            _evict_oldest(container, cap)

def _bump_consecutive(task_data: dict, key: tuple) -> int:
    """Update last_key/consecutive for *key* and return the new count. Lock must be held."""
    if task_data["last_key"] == key:
        task_data["consecutive"] += 1
    else:
        task_data["last_key"] = key
        task_data["consecutive"] = 1
    return task_data["consecutive"]

def _file_metadata(resolved: str) -> tuple | None:
    try:
        st = os.stat(resolved)
        return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns
    except OSError:
        return None

def _dedup_stub_or_block(task_data: dict, dedup_key: tuple, path: str) -> str:
    """Return the "unchanged" stub for a repeated identical read, escalating to a
    hard BLOCK after 2 stubs so weak tool-followers don't loop forever."""
    with _read_tracker_lock:
        hits = task_data["dedup_hits"].get(dedup_key, 0) + 1
        task_data["dedup_hits"][dedup_key] = hits
        _cap_read_tracker_data(task_data)

    if hits >= 2:
        return tool_error(
            f"BLOCKED: You have called read_file on this "
            f"exact region {hits + 1} times and the file "
            "has NOT changed. STOP calling read_file for "
            "this path — the content from your earlier "
            "read_file result in this conversation is "
            "still current. Proceed with your task using "
            "the information you already have.",
            path=path,
            already_read=hits + 1,
            # A REFUSAL the harness chose, not a failure the tool hit: without the
            # marker the failure classifiers count the block and a repeated read
            # escalates to `repeated_exact_failure_block` over calls that never failed.
            **{GUARDRAIL_REFUSAL_KEY: True})

    return json.dumps({
        "status": "unchanged",
        "message": _READ_DEDUP_STATUS_MESSAGE,
        "path": path,
        "dedup": True,
        "content_returned": False,
    }, ensure_ascii=False)

def _evict_oldest(container, cap: int) -> None:
    """Pop entries until *container* is within *cap* (sets: arbitrary; dicts: oldest
    by insertion order). An eviction only costs one redundant re-send or staleness check."""
    for _ in range(len(container) - cap):
        try:
            if isinstance(container, set):
                container.pop()
            else:
                container.pop(next(iter(container)))
        except (StopIteration, KeyError):
            break

_READ_DEDUP_STATUS_MESSAGE = (
    "File unchanged since last read. The content from "
    "the earlier read_file result in this conversation is "
    "still current — refer to that instead of re-reading.")
