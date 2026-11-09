import json
import re
import sys


BLOCK_REASON = (
    "Return only the short answer, with no explanation, parentheticals, or "
    "extra clauses."
)

_YES_NO_RE = re.compile(r"^(yes|no)\b", re.IGNORECASE)
_ELABORATION_SEPARATORS = ("\u2014", "\u2013", ";")

_LOCATIVE_PREPOSITIONS = frozenset({"on", "in", "at", "from", "to"})

_CARDINAL_NUMBER_WORDS = frozenset({
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty",
    "forty", "fifty", "sixty", "seventy", "eighty", "ninety", "hundred",
    "thousand", "million", "billion", "trillion",
})

_MONTH_NAMES = frozenset({
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept",
    "oct", "nov", "dec",
})

# Base-form verbs that commonly introduce a trailing to-infinitive purpose
# clause ("... to delay Allied liberation"). Keeping this a static list avoids
# external POS/lexicon dependencies while still generalizing beyond the single
# example in the finding.
_TO_INFINITIVE_VERBS = frozenset({
    "act", "allow", "appear", "attempt", "avoid", "be", "become", "begin",
    "block", "bridge", "bring", "build", "capture", "carry", "cause", "close",
    "come", "connect", "continue", "cover", "create", "cross", "defend",
    "delay", "deliver", "destroy", "develop", "do", "enable", "end", "ensure",
    "enter", "establish", "explain", "extend", "fail", "find", "finish",
    "follow", "force", "form", "gain", "get", "give", "go", "guard", "happen",
    "have", "help", "hinder", "hold", "improve", "increase", "keep", "know",
    "lead", "leave", "link", "live", "look", "maintain", "make", "mean",
    "move", "need", "offer", "open", "pass", "permit", "plan", "prevent",
    "produce", "promise", "protect", "provide", "put", "reach", "receive",
    "reduce", "remain", "require", "return", "rise", "run", "secure", "see",
    "seek", "seem", "send", "serve", "set", "show", "speak", "spread", "start",
    "stay", "stop", "stretch", "supply", "support", "take", "tell", "tend",
    "think", "threaten", "transport", "try", "turn", "use", "want", "win",
    "work",
})

# Words that unambiguously start a clause in the common over-answer patterns
# "No because ...", "No the document says ...", etc. This avoids treating a
# legitimate short phrase such as "No one" or "No change" as a bare Yes/No
# followed by extra clauses.
_CLAUSE_STARTER_RE = re.compile(
    r"^(?:because|since|as|although|though|while|whereas|when|if|unless|until"
    r"|after|before|provided|given|per|according|based|due|owing|with|without"
    r"|in|on|at|by|for|the|this|that|these|those|it|there|he|she|they|we|you"
    r"|i|a|an|some|any|but|however|therefore|thus|hence|so)\b",
    re.IGNORECASE,
)

# Markdown emphasis markers that may wrap the assistant's final message. Longer
# markers must be tried first so that, for example, "***bold***" is stripped as
# one wrapper rather than being partially handled by the "**" case.
_EMPHASIS_MARKERS = (
    "```", "``", "`",
    "***", "___", "**", "__", "*", "_",
)


def _has_trailing_parenthetical(message):
    """Return True if the message ends with a non-empty parenthetical after text."""
    stripped = message.rstrip()
    if not stripped:
        return False

    # Ignore trailing sentence punctuation so "No (because...)." still counts.
    end = len(stripped)
    while end > 0 and stripped[end - 1] in ".!?\u2026":
        end -= 1

    if end == 0 or stripped[end - 1] != ")":
        return False

    start = stripped.rfind("(", 0, end)
    if start == -1:
        return False

    prefix = stripped[:start].strip()
    inside = stripped[start + 1 : end - 1].strip()
    if not prefix or not inside:
        return False

    return True


def _has_word_or_number(text):
    return bool(re.search(r"\w", text, flags=re.UNICODE))


def _is_plausible_short_answer(text):
    """Heuristic for the concise answer that may precede an elaboration."""
    candidate = text.strip()
    if not candidate or len(candidate) > 80:
        return False
    # A plausible short answer should fit on a single line.
    return "\n" not in candidate


def _has_dash_or_semicolon_elaboration(message):
    """Return True if a concise answer is followed by an em/en-dash or semicolon."""
    stripped = message.strip()
    for separator in _ELABORATION_SEPARATORS:
        for match in re.finditer(re.escape(separator), stripped):
            prefix = stripped[: match.start()].strip()
            suffix = stripped[match.end() :].strip()
            if (
                prefix
                and suffix
                and _is_plausible_short_answer(prefix)
                and _has_word_or_number(suffix)
            ):
                return True
    return False


def _has_bare_yes_no_with_elaboration(message):
    """Return True for a bare Yes/No that is followed by extra clauses."""
    stripped = message.strip()
    match = _YES_NO_RE.match(stripped)
    if not match:
        return False

    remainder = stripped[match.end() :].strip()
    if not remainder:
        return False

    # Only terminal punctuation is allowed after the bare answer.
    if re.fullmatch(r"[\s.,!?;:\u2026]+", remainder):
        return False

    # A clause separator directly after Yes/No is a clear over-answer.
    if remainder[0] in ",.;:!?\u2014\u2013":
        return _has_word_or_number(remainder[1:])

    # Without punctuation, only treat it as an extra clause when the next word
    # is an unambiguous clause starter ("No because ...", "No the text says ...").
    if _CLAUSE_STARTER_RE.match(remainder):
        return _has_word_or_number(remainder)

    return False


def _strip_terminal_sentence_punctuation(text):
    """Strip trailing sentence punctuation without touching the remaining text."""
    stripped = text.rstrip()
    while stripped and stripped[-1] in ".!?\u2026":
        stripped = stripped[:-1]
    return stripped


def _strip_markdown_emphasis(message):
    """Remove matching Markdown emphasis wrappers from the outside of a message.

    This handles recurring formatting such as "**New World Order (NWO)**",
    "__Notes of a Native Son__", or "`Dakota Smith`" by repeatedly removing the
    outermost marker pair so the short-answer checks below inspect the actual
    answer text instead of its decoration.
    """
    text = message.strip()
    while True:
        stripped = False
        for marker in _EMPHASIS_MARKERS:
            if len(text) < 2 * len(marker):
                continue
            if text.startswith(marker) and text.endswith(marker):
                text = text[len(marker):-len(marker)].strip()
                stripped = True
                break
        if not stripped:
            return text


def _normalize_message(message):
    """Normalize a Stop message for the short-answer contract checks.

    Terminal sentence punctuation and surrounding Markdown emphasis markers are
    removed until the text stabilizes. This covers both "**Answer.**" and
    "**Answer**." so decorated over-answers are not accepted just because the
    decoration hides a trailing parenthetical or other elaboration.
    """
    text = message.strip()
    while True:
        updated = _strip_terminal_sentence_punctuation(text).strip()
        updated = _strip_markdown_emphasis(updated)
        if updated == text:
            return updated
        text = updated


def _is_capitalized_token(token):
    """Return True if the token starts with an uppercase letter."""
    return bool(token) and token[0].isupper() and token[0].isalpha()


def _is_lowercase_token(token):
    """Return True if the token starts with a lowercase letter."""
    return bool(token) and token[0].islower() and token[0].isalpha()


def _is_cardinal_number_token(token):
    """Return True for a cardinal number written as digits or word(s)."""
    if not token:
        return False
    if re.fullmatch(r"\d+", token):
        return True
    parts = token.split("-")
    if any(not part for part in parts):
        return False
    return all(part.lower() in _CARDINAL_NUMBER_WORDS for part in parts)


def _has_two_token_prepositional_over_answer(message):
    """Return True for a locative preposition + capitalized token over-answer.

    For example "On Broadway." should be blocked so the agent returns only
    "Broadway".
    """
    stripped = _strip_terminal_sentence_punctuation(message).strip()
    tokens = stripped.split()
    if len(tokens) != 2:
        return False

    first, second = tokens
    if first.lower() not in _LOCATIVE_PREPOSITIONS:
        return False
    return _is_capitalized_token(second)


def _has_two_token_cardinal_over_answer(message):
    """Return True for a cardinal number + lowercase token over-answer.

    For example "Two parts." should be blocked so the agent returns only
    "Two".
    """
    stripped = _strip_terminal_sentence_punctuation(message).strip()
    tokens = stripped.split()
    if len(tokens) != 2:
        return False

    first, second = tokens
    if not _is_cardinal_number_token(first):
        return False
    return _is_lowercase_token(second)


def _iter_top_level_phrase_starts(text, phrase):
    """Yield positions of ``phrase`` that are outside parentheses and quotes.

    Top-level means not nested inside ``()``, ``[]``, ``{}``, or a
    double-quoted span. This is used to find the comma or `` to `` that
    separates a short answer from a post-answer elaboration, while ignoring
    commas inside parentheticals or quoted titles.
    """
    depth = 0
    in_double_quote = False
    i = 0
    while i < len(text):
        char = text[i]
        if char == '"':
            in_double_quote = not in_double_quote
            i += 1
            continue
        if not in_double_quote:
            if char in "([{":
                depth += 1
            elif char in ")]}":
                depth -= 1
            elif depth == 0 and text.startswith(phrase, i):
                yield i
        i += 1


def _is_date_comma(prefix, suffix):
    """Return True for date patterns like ``May 23, 2000``."""
    prefix_match = re.fullmatch(
        r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2})",
        prefix.strip(),
    )
    if not prefix_match:
        return False
    if prefix_match.group("month").lower() not in _MONTH_NAMES:
        return False

    suffix_match = re.fullmatch(
        r"(?P<year>\d{1,4})(?:\s*(?:AD|BC|BCE|CE))?",
        suffix.strip(),
        flags=re.IGNORECASE,
    )
    return suffix_match is not None


def _is_inverted_name(prefix, suffix):
    """Return True for inverted-name patterns like ``Smith, John``."""
    prefix_tokens = prefix.strip().split()
    suffix_tokens = suffix.strip().split()
    if len(prefix_tokens) != 1 or len(suffix_tokens) != 1:
        return False
    return (
        _is_capitalized_token(prefix_tokens[0])
        and _is_capitalized_token(suffix_tokens[0])
    )


def _is_comma_exempt(text, comma_index, prefix, suffix):
    """Return True when a top-level comma is not an elaboration separator."""
    # Thousands separators such as the comma in "185,000".
    if (
        comma_index > 0
        and comma_index + 1 < len(text)
        and text[comma_index - 1].isdigit()
        and text[comma_index + 1].isdigit()
    ):
        return True

    return _is_date_comma(prefix, suffix) or _is_inverted_name(prefix, suffix)


def _has_comma_elaboration(message):
    """Return True when a plausible short answer is followed by a comma clause.

    Examples include "Dawson County, Montana" (where the county is the answer
    and the state is a post-answer qualifier) and "A Punjabi-language Bhangra
    singer-songwriter, known as the ...". Date/number patterns and inverted
    names are exempt because the comma is part of the answer itself.
    """
    text = _normalize_message(message).strip()
    for comma_index in _iter_top_level_phrase_starts(text, ","):
        prefix = text[:comma_index].strip()
        suffix = text[comma_index + 1 :].strip()
        if not prefix or not suffix:
            continue
        if not _is_plausible_short_answer(prefix):
            continue
        if not _has_word_or_number(suffix):
            continue
        if _is_comma_exempt(text, comma_index, prefix, suffix):
            continue
        return True
    return False


def _is_to_infinitive_verb(token):
    """Return True for a base-form verb that can start a to-infinitive."""
    return bool(token) and token.lower() in _TO_INFINITIVE_VERBS


def _has_trailing_to_infinitive_elaboration(message):
    """Return True when a plausible short answer has a trailing to-infinitive.

    This catches purpose clauses such as "... a vital bridge to delay Allied
    liberation." where the text before ``to`` is already a concise answer. The
    suffix must have at least a verb plus one more token, so titles such as
    "Built to Last" are not mistaken for an over-answer, and numeric range
    phrases ("185,000 to 190,000") are ignored because the token after ``to``
    is not a verb.
    """
    text = _normalize_message(message).strip()
    for to_index in _iter_top_level_phrase_starts(text, " to "):
        prefix = text[:to_index].strip()
        suffix = text[to_index + len(" to ") :].strip()
        if not prefix or not suffix:
            continue
        if not _is_plausible_short_answer(prefix):
            continue

        suffix_tokens = suffix.split()
        if len(suffix_tokens) < 2:
            continue
        if not _is_to_infinitive_verb(suffix_tokens[0]):
            continue
        if not _has_word_or_number(suffix):
            continue
        return True
    return False


def _has_over_answer(message):
    """Return True when a message violates the short-answer contract."""
    return (
        _has_trailing_parenthetical(message)
        or _has_dash_or_semicolon_elaboration(message)
        or _has_bare_yes_no_with_elaboration(message)
        or _has_two_token_prepositional_over_answer(message)
        or _has_two_token_cardinal_over_answer(message)
    )


def decide(event):
    # Only inspect the first Stop. When this hook is re-entered after a block,
    # stop_hook_active is true and the agent must be allowed to exit.
    if not isinstance(event, dict):
        return {}
    if event.get("stop_hook_active"):
        return {}

    message = event.get("last_assistant_message")
    if not isinstance(message, str) or not message.strip():
        return {}

    normalized = _normalize_message(message)

    # Check both the raw and normalized message. The normalized check catches
    # over-answers hidden behind Markdown emphasis markers (for example
    # "**New World Order (NWO)**"); the raw check preserves prior behavior.
    if (
        _has_over_answer(message)
        or _has_over_answer(normalized)
        or _has_comma_elaboration(normalized)
        or _has_trailing_to_infinitive_elaboration(normalized)
    ):
        return {"decision": "block", "reason": BLOCK_REASON}

    return {}


if __name__ == "__main__":
    event = json.load(sys.stdin)
    print(json.dumps(decide(event)))
