"""Pinned upstream read presentation budget helpers."""

def _truncate_to_char_budget(content: str, max_chars: int) -> tuple[str, int, bool]:
    """Trim line-numbered ``read_file`` content to the last COMPLETE line within *max_chars*.

    Returns ``(kept_text, lines_kept, truncated)`` so the caller can offer a
    ``next_offset`` instead of rejecting the read. If not even the first line
    fits it is clamped mid-line so the read is never empty and the cursor advances.

    Ported in spirit from nearai/ironclaw#5029 (dual line/byte cap on ``read_file``). Where hermes
    previously hard-rejected an oversized read (forcing the model to guess a smaller ``limit`` and burn a
    round-trip returning nothing), this trims the content to the last *complete line* that fits within
    ``max_chars`` and reports how many lines were kept so the caller can offer a ``next_offset``
    continuation.
    """
    if len(content) <= max_chars:
        return content, (content.count("\n") + 1 if content else 0), False

    lines = content.split("\n")
    kept: list[str] = []
    running = 0
    for line in lines:
        addition = len(line) + (1 if kept else 0)  # +1 for the rejoining "\n"
        if running + addition > max_chars:
            break
        kept.append(line)
        running += addition
    if not kept:
        kept.append(lines[0][:max_chars])
    return "\n".join(kept), len(kept), True

def _apply_char_budget(result_dict: dict, content: str, offset: int, total_lines, max_chars: int) -> str:
    """Trim *content* to the char budget, annotate *result_dict* with the
    continuation hint, and return the trimmed text."""
    trimmed, lines_kept, _ = _truncate_to_char_budget(content, max_chars)
    next_offset = offset + lines_kept
    result_dict["content"] = trimmed
    result_dict["truncated"] = True
    result_dict["truncated_by"] = "bytes"
    result_dict["next_offset"] = next_offset
    result_dict["hint"] = (
        f"Output truncated at the {max_chars:,}-char read budget after "
        f"{lines_kept} line(s) (showing lines {offset}-{next_offset - 1} of "
        f"{total_lines}). Use offset={next_offset} to continue.")
    if len(trimmed.split("\n", 1)[0]) >= max_chars:
        result_dict["truncated_lines"] = True
        result_dict["hint"] += (
            " Note: the first line alone exceeded the budget and was "
            "clamped mid-line; its remainder is not retrievable via offset.")
    return trimmed
