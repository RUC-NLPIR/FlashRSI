from __future__ import annotations
import logging
from typing import Any
logger=logging.getLogger(__name__)

class ResponsesRecoveryMethods:
    def reject_all_turns(self, error: Any) -> bool:
        """400 naming ``reasoning.context``/``all_turns`` on a request that carried the opt-in: omit it for that
        model for the rest of the session. False otherwise, so it buys at most one retry per model."""
        text = str(error).lower()
        if not self._last_sent_all_turns or getattr(error, "status_code", None) not in (400, None) or not (
            "reasoning.context" in text or "all_turns" in text
        ):
            return False
        self._all_turns_rejected = self._all_turns_rejected | {self._last_issuer_model}
        self._last_sent_all_turns = False
        logger.warning("reasoning.context rejected by %s; omitting it for this session", self._last_issuer_model)
        return True

    def drop_unverified_replay(self, *message_lists: Any) -> int:
        """First ``invalid_encrypted_content`` rung: drop the replayed blobs the failing request could not vouch
        for (not stamped by exactly its endpoint + model), keeping the session's own continuity. Returns the
        count removed from the first list; 0 means only the route's own blobs were sent."""
        from ..upstream_compaction.responses_adapter import strip_unverified_reasoning_items

        if self._last_issuer_kind is None or self._last_issuer_model is None:
            return 0
        removed = [
            strip_unverified_reasoning_items(msgs, issuer_kind=self._last_issuer_kind, issuer_model=self._last_issuer_model)
            for msgs in message_lists
        ]
        return removed[0] if removed else 0

