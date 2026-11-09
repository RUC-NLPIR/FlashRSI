import json
import re
import sys

# Substrings (matched case-insensitively) that indicate the final message still
# defers a decision or rests on an open assumption instead of delivering a
# verified result.
_DEFERRAL_PATTERNS = (
    "just say the word",
    "if you actually want",
    "one-line change",
    "assuming",
)

# Substrings that indicate the final message presents a reconstructed or
# extracted answer rather than one that was directly observed and verified.
_RECONSTRUCTED_PATTERNS = (
    "flag{",
    "the text reads",
    "reconstruct",
    "recover",
    "extract",
    "decod",
)

# Substrings that indicate the final message includes concrete verification
# evidence (per-symbol metrics, byte/character matching, etc.) backing a
# reconstructed answer.
_VERIFICATION_PATTERNS = (
    "verif",
    "match",
    "measure",
    "height",
    "digit",
    "exact",
    "byte",
)

# Tokens (matched as whole words, case-insensitively) that indicate the final
# message asserts output equivalence or correctness rather than merely
# narrating the work performed. Word boundaries keep "diff"/"correct" from
# matching "different"/"incorrect" and the like.
_EQUIVALENCE_PATTERNS = (
    "identical",
    "byte-identical",
    "matches",
    "verified",
    "correct",
    "diff",
)

# Substrings that indicate the authoritative check was skipped, estimated, or
# only partially run, so any equivalence claim in the same message is not backed
# by a full verification.
_SKIPPED_CHECK_PATTERNS = (
    "can't run",
    "couldn't run",
    "still running",
    "timed out",
    "measured",
    "estimated",
    "reduced db",
    "subset",
    "did not finish",
)

# Substrings that indicate concrete tool-output evidence (exit/status codes,
# byte/line arithmetic, test counts, runtime artifacts) beyond a bare assertion
# of equivalence or correctness.
_CONCRETE_EVIDENCE_PATTERNS = (
    "exit code",
    "exit status",
    "status code",
    "return code",
    "returned 0",
    "0x",
    " rows",
    " lines",
    " bytes",
    "passed",
    "failed",
    "pid",
    "port",
    "json",
)

# A double-quoted or backtick-fenced span, used to detect a quoted line of tool
# output (which only counts as evidence when it carries non-alphabetic content).
_QUOTED_OUTPUT_RE = re.compile(r'(["\x60])([^"\x60\n]+)\1')


def _final_assistant_text(transcript_path):
    """Return the text of the final assistant message, or None if unreadable."""
    try:
        with open(transcript_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except (OSError, IOError):
        return None

    last_text = None
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue

        message = entry.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")

        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    value = block.get("text")
                    if isinstance(value, str):
                        parts.append(value)
            text = "".join(parts)
        else:
            continue

        if text.strip():
            last_text = text

    return last_text


def _has_any(lowered_text, patterns):
    return any(pattern in lowered_text for pattern in patterns)


def _has_word(lowered_text, patterns):
    """True when any pattern appears as a whole word in the lowered text."""
    return any(
        re.search(r"(?<![a-z0-9])" + re.escape(pattern) + r"(?![a-z0-9])", lowered_text)
        for pattern in patterns
    )


def _has_quoted_output(text):
    """True when the text quotes output-like content (digits or punctuation)."""
    for match in _QUOTED_OUTPUT_RE.finditer(text):
        if re.search(r"[^a-zA-Z ]", match.group(2)):
            return True
    return False


def decide(event):
    if not isinstance(event, dict):
        return {}

    # Never recurse: a Stop hook already blocked this turn, so allow it through.
    if event.get("stop_hook_active"):
        return {}

    # Never break a run: allow when the transcript can't be located or read.
    transcript_path = event.get("transcript_path")
    if not isinstance(transcript_path, str) or not transcript_path:
        return {}

    text = _final_assistant_text(transcript_path)
    if text is None:
        return {}

    lowered = text.lower()

    if _has_any(lowered, _DEFERRAL_PATTERNS):
        return {
            "decision": "block",
            "reason": "Final message still defers a decision or rests on an open assumption; verify before finishing.",
        }

    if _has_any(lowered, _RECONSTRUCTED_PATTERNS) and not _has_any(
        lowered, _VERIFICATION_PATTERNS
    ):
        return {
            "decision": "block",
            "reason": "Final message presents a reconstructed answer without verification evidence; verify before finishing.",
        }

    # An equivalence/correctness claim is only sound when the authoritative
    # check was actually run in full and its output is visible. Block when the
    # same message either admits the check was skipped/estimated/partial or
    # offers no concrete tool-output evidence beyond the assertion itself.
    if _has_word(lowered, _EQUIVALENCE_PATTERNS):
        admits_partial = _has_any(lowered, _SKIPPED_CHECK_PATTERNS)
        has_evidence = _has_any(
            lowered, _CONCRETE_EVIDENCE_PATTERNS
        ) or _has_quoted_output(text)
        if admits_partial or not has_evidence:
            if admits_partial:
                reason = (
                    "Final message asserts equivalence/correctness but admits the "
                    "authoritative check was skipped, estimated, or only partially "
                    "run; verify before finishing."
                )
            else:
                reason = (
                    "Final message asserts equivalence/correctness without concrete "
                    "tool-output evidence; verify before finishing."
                )
            return {"decision": "block", "reason": reason}

    return {}


if __name__ == "__main__":
    print(json.dumps(decide(json.load(sys.stdin))))
