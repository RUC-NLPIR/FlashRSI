"""Pinned upstream bounded streaming capture and capped disk spill."""

import threading
from collections import deque
from pathlib import Path
from typing import IO
from .tool_output_truncate import head_tail_split, truncation_notice

class _BoundedOutputCollector:
    """Retain a bounded 40/60 head-tail window of streamed text. When ``spill_path`` is set,
    the FULL stream is also teed to that file once eviction begins (up to ``_SPILL_CAP_CHARS``)
    so a truncated foreground result is recoverable without re-running."""

    # Hard ceiling on spill file size; protects disk from runaway output.
    _SPILL_CAP_CHARS = 5_000_000

    def __init__(self, max_chars: int, spill_path: Path | None = None):
        self.max_chars = max(1, int(max_chars))
        self._head_limit = int(self.max_chars * 0.4)
        self._tail_limit = self.max_chars - self._head_limit
        self._head: list[str] = []
        self._tail: deque[str] = deque()
        self._head_chars = 0
        self._tail_chars = 0
        self._total_chars = 0
        self._lock = threading.Lock()
        self._spill_path = spill_path
        self._spill_fh: IO[str] | None = None
        self._spill_chars = 0
        self._spill_capped = False

    def _maybe_spill(self, text: str) -> None:
        """Tee ``text`` to the spill file (opened lazily on first overflow)."""
        if self._spill_path is None or self._spill_capped:
            return
        try:
            if self._spill_fh is None:
                from .spill_safety import ensure_spill_dir, open_exclusive
                # Raw pre-redaction output: private perms + symlink-refusing
                # exclusive create (a planted link must fail, never redirect).
                ensure_spill_dir(self._spill_path.parent, private=True)
                self._spill_fh = open_exclusive(self._spill_path, private=True, errors="replace")
                # Backfill what's retained so the file holds the stream from byte 0.
                backlog = "".join(self._head) + "".join(self._tail)
                self._spill_fh.write(backlog)
                self._spill_chars = len(backlog)
            budget = self._SPILL_CAP_CHARS - self._spill_chars
            if budget <= 0 or len(text) > budget:
                self._spill_fh.write(text[:max(0, budget)])
                self._spill_fh.write("\n... [spill capped at 5,000,000 chars] ...\n")
                self._spill_capped = True
            else:
                self._spill_fh.write(text)
            self._spill_chars += len(text)
        except OSError:
            # Disk trouble must never break command execution.
            self._spill_capped = True

    def close_spill(self) -> str | None:
        """Close the spill file and return its path if it was used."""
        with self._lock:
            if self._spill_fh is None:
                return None
            try:
                self._spill_fh.close()
            except OSError:
                pass
            self._spill_fh = None
            return str(self._spill_path)

    @property
    def buffered_chars(self) -> int:
        with self._lock:
            return self._head_chars + self._tail_chars

    @property
    def total_chars(self) -> int:
        with self._lock:
            return self._total_chars

    def append(self, text: str) -> None:
        if not text:
            return
        with self._lock:
            text_len = len(text)
            # Spill tee activates at the first overflow, then mirrors every chunk.
            if self._spill_path is not None and (
                self._spill_fh is not None or self._total_chars + text_len > self.max_chars):
                self._maybe_spill(text)
            self._total_chars += text_len
            start = 0

            if self._head_chars < self._head_limit:
                take = min(self._head_limit - self._head_chars, text_len)
                if take:
                    self._head.append(text[:take])
                    self._head_chars += take
                    start = take

            remaining = text_len - start
            if remaining <= 0 or self._tail_limit <= 0:
                return
            if remaining >= self._tail_limit:
                self._tail.clear()
                self._tail.append(text[-self._tail_limit :])
                self._tail_chars = self._tail_limit
                return

            chunk = text[start:]
            self._tail.append(chunk)
            self._tail_chars += len(chunk)
            while (excess := self._tail_chars - self._tail_limit) > 0:
                first = self._tail[0]
                if len(first) <= excess:
                    self._tail.popleft()
                    self._tail_chars -= len(first)
                else:
                    self._tail[0] = first[excess:]
                    self._tail_chars -= excess

    def render(self, *, suffix: str = "") -> str:
        """Render within ``max_chars``, preserving a required status suffix."""
        with self._lock:
            if len(suffix) >= self.max_chars:
                return suffix[-self.max_chars :]

            head = "".join(self._head)
            tail = "".join(self._tail)
            available = self.max_chars - len(suffix)
            if self._total_chars <= available:
                return head + tail + suffix

            # The notice length depends on the omitted count, which depends on
            # the notice length; iterate to a fixed point (converges quickly).
            notice = ""
            for _ in range(4):
                omitted = max(0, self._total_chars - max(0, available - len(notice)))
                updated = truncation_notice(omitted, self._total_chars)
                if updated == notice:
                    break
                notice = updated

            content_budget = max(0, available - len(notice))
            head_chars, tail_chars = head_tail_split(content_budget)
            rendered_tail = tail[-tail_chars:] if tail_chars else ""
            return head[:head_chars] + notice[:available] + rendered_tail + suffix
