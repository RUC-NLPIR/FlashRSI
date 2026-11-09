import json
import re
import sys
from pathlib import Path


# Stop-hook decision helpers.  Keep the hook protocol payload unchanged:
# the Stop hook always receives a JSON event on stdin and must print a
# single JSON decision object on stdout.
def _allow():
    return {"decision": {"decision": "allow"}}


def _block(reason):
    return {"decision": {"decision": "block", "reason": reason}}


# ---------------------------------------------------------------------------
# Transcript loading / message extraction
# ---------------------------------------------------------------------------

def _load_records(transcript_path):
    """Read a Claude transcript file.

    Transcripts are normally JSONL, but accept a top-level JSON array as well.
    Return a list of record dicts, or [] when the file is missing/invalid.
    """
    if not transcript_path:
        return []

    try:
        path = Path(transcript_path)
        raw = path.read_text(encoding="utf-8", errors="replace")
    except (OSError, TypeError, ValueError):
        return []

    # Support whole-file JSON exports (a top-level array, or an object with a
    # "messages"/"transcript" array) in addition to JSONL.
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("messages", "transcript"):
                items = data.get(key)
                if isinstance(items, list):
                    return [item for item in items if isinstance(item, dict)]
    except json.JSONDecodeError:
        pass

    records = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _extract_text(content):
    """Best-effort extraction of plain text from a transcript content value."""
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text" and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif isinstance(block.get("text"), str):
                    parts.append(block["text"])
        return "\n".join(part for part in parts if part)

    if isinstance(content, dict):
        return _extract_text(content.get("content", ""))

    return ""


def _is_tool_result_message(record):
    """True when a user-role record is only carrying tool results."""
    message = record.get("message") if isinstance(record, dict) else None
    content = message.get("content") if isinstance(message, dict) else record.get("content")
    if isinstance(content, list) and content:
        return all(
            isinstance(block, dict) and block.get("type") == "tool_result"
            for block in content
        )
    return False


def _message_role(record):
    if not isinstance(record, dict):
        return None

    top_type = record.get("type")
    if top_type in ("user", "assistant"):
        return top_type

    message = record.get("message")
    if isinstance(message, dict):
        role = message.get("role")
        if role in ("user", "assistant"):
            return role

    role = record.get("role")
    if role in ("user", "assistant"):
        return role

    return None


def _message_content(record):
    if not isinstance(record, dict):
        return ""
    message = record.get("message")
    if isinstance(message, dict):
        content = message.get("content")
        if content is not None:
            return content
    return record.get("content", "")


def _collect_messages(records):
    """Return [(role, text), ...] for user/assistant messages.

    Tool-result user turns are skipped because they are not real user
    instructions.  Assistant turns are kept even when they have no text so the
    caller can tell whether the *last* assistant turn actually contains a
    final text answer.
    """
    messages = []
    for record in records:
        role = _message_role(record)
        if role not in ("user", "assistant"):
            continue
        if role == "user" and _is_tool_result_message(record):
            continue
        text = _extract_text(_message_content(record)).strip()
        messages.append((role, text))
    return messages


# ---------------------------------------------------------------------------
# Formatting detection
# ---------------------------------------------------------------------------

_SHORT_ANSWER_REQUEST_PATTERNS = [
    r"\b(?:short|bare|one-word|single-word|brief|concise|direct)\s+(?:answer|response|reply|format)\b",
    r"\b(?:answer|respond|reply)\s+(?:with|using|in)?\s*(?:only|just|nothing\s+but|no\s+more\s+than)\s+(?:the\s+)?(?:short|bare|one-word|single-word|brief|concise|direct)?\s*(?:answer|response|reply|name|word|number|value)\b",
    r"\b(?:answer|respond|reply)\s+(?:only|just)\s+(?:with\s+)?(?:the\s+)?(?:short|bare|one-word|single-word|brief|concise|direct)?\s*(?:answer|response|reply|name|word|number|value)\b",
    r"\b(?:answer|respond|reply)\s+with\s+the\s+(?:name|word|number|short\s+answer|answer)\s+only\b",
    r"\b(?:only|just|nothing\s+but)\s+(?:the\s+)?(?:short|bare|one-word|single-word|brief|concise|direct)?\s*(?:answer|name|word|number|value|response|reply)\b",
    r"\b(?:give|provide|return|state|say|tell\s+me)\s+(?:only|just)\s+the\b",
    r"\b(?:just|only)\s+(?:give|provide|return|state|say|tell\s+me)\s+the\b",
    r"\b(?:give|provide|return|state|say)\s+(?:the\s+)?(?:name|word|number|short\s+answer|answer)\s+(?:only|just)\b",
    r"\b(?:only|just)\s+(?:one\s+)?(?:word|name|number)\b",
    r"\banswer\s+only\b",
    r"\banswer\s+in\s+one\s+word\b",
    r"\b(?:with|using)\s+(?:only|just)\s+(?:the\s+)?(?:short|bare)?\s*(?:answer|name|word|number)\b",
    r"\bno\s+(?:explanation|commentary|extra|additional\s+text|justification)\b",
    r"\bwithout\s+(?:any\s+)?(?:explanation|commentary|markdown|formatting|extra\s+text|justification)\b",
    r"\bdo\s+not\s+(?:explain|include|add|provide\s+context)\b",
]

_SHORT_ANSWER_REQUEST_RE = re.compile(
    "|".join(_SHORT_ANSWER_REQUEST_PATTERNS), re.IGNORECASE
)

# Explanatory glue that is not part of a bare short answer.
_EXPLANATORY_GLUE_PATTERNS = [
    r"\balso\s+known\s+as\b",
    r"\baka\b",
    r"\bwhich\s+is\b",
    r"\bbecause\b",
    r"\bsuch\s+as\b",
    r"\bfor\s+example\b",
    r"\be\.g\.",
    r"\bi\.e\.",
    r"\bthat\s+is\b",
    r"\b(?:the|my|our)\s+answer\s+is\b",
    r"\b(?:the\s+)?correct\s+answer\s+is\b",
    r"\bin\s+other\s+words\b",
    r"\bstands\s+for\b",
    r"\brefers\s+to\b",
    r"\bknown\s+as\b",
    r"\blocated\s+in\b",
    r"\b(?:the\s+)?(?:show|movie|film|series|book|play|title|cast|character|actor|actress)\s+(?:is|was)\b",
    r"\bincludes?\b",
    r"\bconsists?\s+of\b",
    r"\bcontains?\b",
    r"\b(?:played\s+by|directed\s+by|starring|role\s+of)\b",
    r"\bis\s+a\s+(?:type|kind|species|member|part|form)\s+of\b",
]

_EXPLANATORY_GLUE_RE = re.compile(
    "|".join(_EXPLANATORY_GLUE_PATTERNS), re.IGNORECASE
)

_MARKDOWN_EMPHASIS_RE = re.compile(
    r"(?<!\w)(\*|_){1,3}[^*_\n]+(\1){1,3}(?!\w)"
)

_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]+\]\([^)]*\)")

_MARKDOWN_CODE_RE = re.compile(r"`[^`]+`")

# A bare short answer wrapped only in a Markdown emphasis layer such as
# ``**bumpkin**``, ``*omelet*``, or ``__eagle__`` is still the bare answer.
# Strip that single surrounding layer before applying the formatting checks;
# emphasis that is embedded in a larger explanatory construction is left in
# place so the surrounding material is still detected.
_SURROUNDING_MARKDOWN_EMPHASIS_RE = re.compile(
    r"^\s*(\*{1,3}|_{1,3})(.+?)\1\s*$", re.DOTALL
)

_PARENTHETICAL_RE = re.compile(r"\([^)]*\)")

_EM_DASH_RE = re.compile(r"[—–]")

_SEMICOLON_RE = re.compile(r";")

_MULTILINE_OR_TAB_RE = re.compile(r"[\n\t]")

_BLOCKQUOTE_OR_LIST_RE = re.compile(r"^\s*(?:>|[-*+]\s+|\d+[.)]\s+)", re.MULTILINE)

# Leading pronoun/copula lead-ins such as "It is Paris" are full-sentence
# answers, not bare short answers.  The copula alternatives are lower-case so
# title-case titles such as "This Is Spinal Tap" are preserved.
_LEADING_PRONOUN_COPULA_RE = re.compile(
    r"^\s*(?:[Ii]t|[Hh]e|[Ss]he|[Tt]hey|[Tt]here|[Hh]ere|[Tt]his|[Tt]hat)\s+(?:is|was|are|were)\b"
)

# Cast/description vocabulary that indicates an answer mode other than a bare
# entity when it appears in a longer phrase.
_CAST_DESCRIPTION_WORDS_RE = re.compile(
    r"\b(?:cast|characters?|actors?|actresses?|starring|played\s+by|directed\s+by|role\s+of)\b",
    re.IGNORECASE,
)

# A trailing "by <Proper Noun...>" attribution is not part of a bare short
# answer (for example "Losing My Religion by R.E.M.").  Only "by" is checked:
# other prepositions such as "in", "on", "at", and "from" are common inside
# valid titles (for example "Picture in Picture", "Last Tango in Paris", or
# "An American in Paris") and are deliberately not treated as attributions.
_TRAILING_BY_ATTRIBUTION_RE = re.compile(
    r"\bby\s+[A-Z][\w.'’\-]*(?:\s+[A-Z][\w.'’\-]*)*\.?\s*$"
)

# Comma-separated capitalized elaboration such as "Dahlonega, Georgia".
# Common abbreviation suffixes are allowed because they are part of the
# answer itself (for example "Washington, D.C." or "Martin Luther King, Jr.").
_COMMA_ELABORATION_ABBREVIATIONS = {
    "d.c.",
    "jr.",
    "sr.",
    "inc.",
    "ltd.",
    "co.",
    "st.",
    "mt.",
    "dr.",
    "mr.",
    "mrs.",
    "ms.",
    "u.s.",
    "u.s.a.",
    "u.k.",
}

_COMMA_CAPITALIZED_QUALIFIER_RE = re.compile(
    r"[A-Z][\w.'’\-]*(?:\s+[A-Z][\w.'’\-]*)*\.?$"
)

# Geographic qualifier names (states, provinces, territories, and countries)
# that turn a comma-separated answer core into an elaborated location such as
# "Salt Lake City, Utah" or "Buenos Aires, Argentina".  The list is kept as a
# coarse gazetteer rather than a per-task rule so the check applies to any
# place-name-plus-qualifier shape.  Titles such as "Welcome Back, Kotter" do
# not use one of these suffixes and therefore remain allowed.
_GEOGRAPHIC_QUALIFIERS = {
    name.strip().lower().replace("’", "'")
    for name in """
alabama
alaska
arizona
arkansas
california
colorado
connecticut
delaware
florida
georgia
hawaii
idaho
illinois
indiana
iowa
kansas
kentucky
louisiana
maine
maryland
massachusetts
michigan
minnesota
mississippi
missouri
montana
nebraska
nevada
new hampshire
new jersey
new mexico
new york
north carolina
north dakota
ohio
oklahoma
oregon
pennsylvania
rhode island
south carolina
south dakota
tennessee
texas
utah
vermont
virginia
washington
west virginia
wisconsin
wyoming
american samoa
guam
northern mariana islands
puerto rico
u.s. virgin islands
district of columbia
alberta
british columbia
manitoba
new brunswick
newfoundland and labrador
nova scotia
ontario
prince edward island
quebec
saskatchewan
northwest territories
nunavut
yukon
england
scotland
wales
northern ireland
new south wales
queensland
south australia
tasmania
victoria
western australia
australian capital territory
northern territory
afghanistan
albania
algeria
andorra
angola
antigua and barbuda
argentina
armenia
australia
austria
azerbaijan
bahamas
bahrain
bangladesh
barbados
belarus
belgium
belize
benin
bhutan
bolivia
bosnia and herzegovina
botswana
brazil
brunei
bulgaria
burkina faso
burundi
cambodia
cameroon
canada
cape verde
central african republic
chad
chile
china
colombia
comoros
congo
costa rica
cote d'ivoire
côte d'ivoire
croatia
cuba
cyprus
czech republic
democratic republic of the congo
denmark
djibouti
dominica
dominican republic
east timor
ecuador
egypt
el salvador
equatorial guinea
eritrea
estonia
eswatini
ethiopia
fiji
finland
france
gabon
gambia
georgia
germany
ghana
greece
grenada
guatemala
guinea
guinea-bissau
guyana
haiti
honduras
hungary
iceland
india
indonesia
iran
iraq
ireland
israel
italy
ivory coast
jamaica
japan
jordan
kazakhstan
kenya
kiribati
kosovo
kuwait
kyrgyzstan
laos
latvia
lebanon
lesotho
liberia
libya
liechtenstein
lithuania
luxembourg
madagascar
malawi
malaysia
maldives
mali
malta
marshall islands
mauritania
mauritius
mexico
micronesia
moldova
monaco
mongolia
montenegro
morocco
mozambique
myanmar
namibia
nauru
nepal
netherlands
new zealand
nicaragua
niger
nigeria
north korea
north macedonia
norway
oman
pakistan
palau
palestine
panama
papua new guinea
paraguay
peru
philippines
poland
portugal
qatar
romania
russia
rwanda
saint kitts and nevis
saint lucia
saint vincent and the grenadines
samoa
san marino
sao tome and principe
saudi arabia
senegal
serbia
seychelles
sierra leone
singapore
slovakia
slovenia
solomon islands
somalia
south africa
south korea
south sudan
spain
sri lanka
sudan
suriname
sweden
switzerland
syria
taiwan
tajikistan
tanzania
thailand
togo
tonga
trinidad and tobago
tunisia
turkey
turkmenistan
tuvalu
uganda
ukraine
united arab emirates
united kingdom
united states
uruguay
uzbekistan
vanuatu
vatican city
venezuela
vietnam
yemen
zambia
zimbabwe
""".splitlines()
    if name.strip()
}



def _requests_short_answer(user_text):
    return bool(_SHORT_ANSWER_REQUEST_RE.search(user_text))


def _strip_surrounding_markdown_emphasis(text):
    """Remove one Markdown emphasis layer that wraps the whole answer.

    ``**bumpkin**``, ``*omelet*``, and ``__eagle__`` are bare answers with an
    emphasis wrapper, not explanatory formatting, so the wrapper is removed
    before the short-answer checks run.  Emphasis that is only part of a larger
    construction (for example ``**True** — ...``) is left intact so the extra
    material can still be detected.
    """
    match = _SURROUNDING_MARKDOWN_EMPHASIS_RE.match(text)
    if not match:
        return text
    return match.group(2).strip()


# Bare boolean/yes-no answer detection.  A short-answer prompt that is not a
# yes/no or true/false question cannot have "True", "False", "Yes", or "No"
# as its bare answer, so block those completions rather than accepting them.
_BARE_BOOLEAN_TOKEN_RE = re.compile(
    r"^\s*(?:true|false|yes|no)\s*[.!?]?\s*$",
    re.IGNORECASE,
)

_BOOLEAN_QUESTION_MARKER_RE = re.compile(
    r"\b(?:"
    r"true\s+or\s+false|false\s+or\s+true|"
    r"yes\s+or\s+no|no\s+or\s+yes|"
    r"yes\s*/\s*no|no\s*/\s*yes|"
    r"true\s*/\s*false|false\s*/\s*true|"
    r"yes-no|no-yes|true-false|false-true"
    r")\b",
    re.IGNORECASE,
)

_YES_NO_AUX_START_RE = re.compile(
    r"^\s*(?:is|are|am|do|does|did|can|could|will|would|should|shall|has|have|had|may|might|must)\b",
    re.IGNORECASE,
)


def _is_bare_boolean_answer(assistant_text):
    """True when the final answer is only a bare boolean/yes-no token.

    A surrounding Markdown emphasis layer (``**True**``) and matching quotes
    (``"yes"``) are ignored, as is a single trailing sentence-ending
    punctuation mark, because those are still bare boolean tokens.  Anchoring
    the token to the whole answer means longer answers that merely contain
    ``yes`` or ``no`` are not affected.
    """
    text = _strip_surrounding_markdown_emphasis(assistant_text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'", "`"):
        text = text[1:-1].strip()
    return bool(_BARE_BOOLEAN_TOKEN_RE.match(text))


def _contains_yes_no_question_sentence(sentence):
    """True when a text segment is a direct yes/no question."""
    sentence = sentence.strip()
    candidates = [sentence]
    # Allow labels such as "Question: Is ...?"
    candidates.extend(re.split(r"[:：]\s*", sentence))
    for candidate in candidates:
        candidate = candidate.strip()
        if candidate.endswith("?") and _YES_NO_AUX_START_RE.match(candidate):
            return True
    return False


def _is_boolean_question(user_text):
    """True when the prompt asks a yes/no or true/false question."""
    if _BOOLEAN_QUESTION_MARKER_RE.search(user_text):
        return True

    for segment in re.split(r"(?<=[.!?])\s+", user_text):
        if _contains_yes_no_question_sentence(segment):
            return True
    return False


def _has_trailing_by_attribution(assistant_text):
    """True when the answer ends with a "by <Proper Noun...>" attribution."""
    return bool(_TRAILING_BY_ATTRIBUTION_RE.search(assistant_text))


def _is_geographic_qualifier(suffix):
    """True when a comma suffix is a known state/province/country name."""
    normalized = suffix.strip()
    normalized = re.sub(r"\.\s*$", "", normalized)
    normalized = normalized.lower().replace("’", "'")
    return normalized in _GEOGRAPHIC_QUALIFIERS


def _is_multiword_proper_noun_core(prefix):
    """True when the text before the comma is a capitalized proper-noun phrase."""
    if not re.search(r"\s", prefix):
        return False
    return bool(_COMMA_CAPITALIZED_QUALIFIER_RE.match(prefix))


def _has_comma_capitalized_elaboration(assistant_text):
    """True when an answer appends a capitalized qualifier after a comma.

    The classic single-word shape ``<Answer>, <Capitalized Qualifier>`` is
    always rejected (for example ``Dahlonega, Georgia``).  The same check also
    applies to a multi-word proper-noun answer core when the suffix is a
    geographic qualifier, such as ``Salt Lake City, Utah`` or
    ``Buenos Aires, Argentina``.  A comma inside a multi-word title/name such
    as ``Welcome Back, Kotter`` is part of the answer rather than an appended
    qualifier, so it is not flagged.  Common abbreviations such as ``D.C.``,
    ``Jr.``, and ``Sr.`` remain exempt.
    """
    for match in re.finditer(r",\s*", assistant_text):
        prefix = assistant_text[:match.start()].strip()
        suffix = assistant_text[match.end():].strip()
        if not prefix or not suffix:
            continue

        if suffix.lower() in _COMMA_ELABORATION_ABBREVIATIONS:
            continue

        suffix_is_capitalized = bool(_COMMA_CAPITALIZED_QUALIFIER_RE.match(suffix))
        suffix_is_geographic = _is_geographic_qualifier(suffix)
        if not suffix_is_capitalized and not suffix_is_geographic:
            continue

        # The original single-word answer core shape.
        if not re.search(r"\s", prefix):
            return True

        # A multi-word answer core is only an elaboration when it is followed
        # by a geographic qualifier (state/province/country); otherwise the
        # comma is treated as part of the answer title/name.
        if suffix_is_geographic and _is_multiword_proper_noun_core(prefix):
            return True

    return False


# Leading question-phrase answer formats such as "What is a well?" are full
# Jeopardy-style sentences rather than the requested bare answer.  Keep the
# auxiliary verb lower-case and require the answer object to start with a
# lower-case common noun (or an article) so title-case question titles such as
# "Who Framed Roger Rabbit" are not treated as violations.
_LEADING_QUESTION_ANSWER_RE = re.compile(
    r"^\s*"
    r"(?:"
    r"(?:[Ww]hat|[Ww]ho|[Ww]here|[Ww]hen|[Ww]hy|[Ww]hich)"
    r"(?:'s|’s|\s+is\b|\s+are\b|\s+was\b|\s+were\b)"
    r"|"
    r"(?:[Hh]ow)\s+(?:many|much|old|long|far|tall|big|often)\b"
    r")"
    r"\s+(?:(?:[Aa]n?|[Tt]he)\s+)?[a-z][\w’'\-]*"
)

# Full-sentence definitional answers for short-answer prompts, e.g.
# "A campaign slogan for William Henry Harrison and John Tyler in the 1840
# U.S. presidential election." or "A community in Maryland".  These start with
# an article, a generic category noun, and a definitional preposition, which is
# not a bare short answer.
_DEFINITIONAL_CATEGORY_NOUN_PATTERN = (
    r"(?:"
    r"campaign\s+slogan|slogan|community|census-designated\s+place|"
    r"term|word|phrase|name|title|concept|idea|theory|method|process|technique|"
    r"city|town|state|country|region|person|character|"
    r"film|movie|novel|book|song|album|play|painting|work|device|tool|instrument|"
    r"system|disease|condition|event|war|battle|treaty|law|amendment|period|era|"
    r"epoch|language|religion|movement|organization|organisation|company|brand|"
    r"type|kind|species|form|class|genre|group|team|party|member|part|role|job|"
    r"position|office"
    r")"
)

_FULL_SENTENCE_DEFINITION_RE = re.compile(
    r"^\s*(?:[Aa]n?|[Tt]he)\s+"
    + _DEFINITIONAL_CATEGORY_NOUN_PATTERN
    + r"(?:\s+[a-z][\w’'\-]*){0,2}\s+"
    + r"(?:for|in|of|by|about|that|which|used\s+(?:for|in|to)|referring\s+to)\b"
)

# An indefinite article plus a three-or-more-word lowercase descriptive
# common-noun phrase is a full noun-phrase description, not a bare short answer
# (e.g. "A hot air balloon" or "A giant flour tortilla").  Article + one- or
# two-word phrases such as "A subject" or "A eucalyptus tree" remain valid,
# as do title-case titles such as "The Stand" or "The Bastille".
_INDEFINITE_ARTICLE_DESCRIPTIVE_PHRASE_RE = re.compile(
    r"^\s*[Aa]n?\s+[a-z][\w’'\-]*(?:\s+[a-z][\w’'\-]*){2,}\.?\s*$"
)

# A descriptive common-noun phrase headed by a rank, ordinal, or superlative
# modifier and followed by a prepositional complement is a short description
# rather than a bare answer (e.g. "Second largest city in Germany" or
# "Largest city in France").  The head is case-insensitive so the normal
# sentence-initial capital is accepted, but the descriptive words between the
# head and the preposition must be lower-case.  A bare title such as
# "Last Tango in Paris" keeps its inner words capitalized and is not matched.
_RANK_SUPERLATIVE_DESCRIPTIVE_PHRASE_RE = re.compile(
    r"^\s*"
    r"(?i:"
    r"first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|"
    r"eleventh|twelfth|thirteenth|fourteenth|fifteenth|sixteenth|"
    r"seventeenth|eighteenth|nineteenth|twentieth|"
    r"last|next|"
    r"largest|smallest|tallest|biggest|highest|lowest|oldest|newest|"
    r"longest|shortest|best|worst|top|leading|chief|main|"
    r"most\s+[a-z]+|least\s+[a-z]+"
    r")"
    r"(?:\s+[a-z][\w’'\-]*)+?\s+"
    r"(?:in|of|on|by|near|at|to)\b"
)

# Parenthetical asides that elaborate an otherwise short answer.  This hint
# regex detects explicit aside markers inside a parenthetical (years, roles,
# and "also called"/aka glosses). Plain alternate-name parentheticals are
# caught by _has_parenthetical_aside when they follow an existing answer core.
_PARENTHETICAL_ASIDE_HINT_RE = re.compile(
    r"\([^)]*(?:\b(?:also\s+(?:known\s+as|called)|aka|a\.k\.a\.)\b|"
    r"\b(?:19|20)\d{2}\b|"
    r"\b(?:director|producer|actor|actress|starring|played\s+by|released\s+in|"
    r"published\s+in|originally|based\s+on|circa|est\.)\b)[^)]*\)",
    re.IGNORECASE,
)


def _has_leading_question_phrase(assistant_text):
    """True when the final answer is a Jeopardy-style question sentence."""
    return bool(_LEADING_QUESTION_ANSWER_RE.search(assistant_text))


def _has_full_sentence_definition(assistant_text):
    """True when the final answer is a definitional full sentence/description."""
    return bool(_FULL_SENTENCE_DEFINITION_RE.match(assistant_text))


def _has_indefinite_article_descriptive_phrase(assistant_text):
    """True for an indefinite-article-prefixed descriptive noun phrase.

    The phrase must have at least three lower-case content words after the
    article.  One- and two-word article phrases are deliberately left alone
    because some valid short answers take that form (for example
    ``A subject`` and ``A eucalyptus tree``).
    """
    return bool(_INDEFINITE_ARTICLE_DESCRIPTIVE_PHRASE_RE.match(assistant_text))


def _has_rank_superlative_descriptive_phrase(assistant_text):
    """True for a rank/ordinal/superlative-headed descriptive phrase."""
    return bool(_RANK_SUPERLATIVE_DESCRIPTIVE_PHRASE_RE.match(assistant_text))


def _has_parenthetical_aside(assistant_text):
    """True when the answer contains a parenthesized elaboration.

    A leading parenthesized token can be an integral part of the answer
    (for example ``(Lou) Gehrig``), so it is allowed as long as it does not
    itself contain aside material such as a year, role, or "also called"
    gloss. Parentheticals that follow an existing answer core, or that are the
    entire answer, are still treated as explanatory asides.
    """
    for match in _PARENTHETICAL_RE.finditer(assistant_text):
        parenthetical = match.group(0)
        if _PARENTHETICAL_ASIDE_HINT_RE.search(parenthetical):
            return True
        prefix = assistant_text[:match.start()].strip()
        suffix = assistant_text[match.end():].strip()
        if prefix:
            return True
        if not suffix:
            return True
    return False


def _has_leading_pronoun_copula(assistant_text):
    """True when the answer is a pronoun-plus-copula full sentence."""
    return bool(_LEADING_PRONOUN_COPULA_RE.match(assistant_text))


def _has_non_entity_description(assistant_text):
    """True for comma-separated lists and cast/description answer modes.

    This merges the final-answer heuristics that used to live in the
    tool-interaction hook into the completion hook.  A bare short answer should
    not be a two-or-more-comma list, and a longer phrase that explicitly
    mentions cast/characters/actors/starring is an explanation rather than the
    requested entity.
    """
    text = _strip_surrounding_markdown_emphasis(assistant_text).strip()
    word_count = len(text.split())
    if word_count >= 4 and text.count(",") >= 2:
        return True
    if word_count >= 4 and _CAST_DESCRIPTION_WORDS_RE.search(text):
        return True
    return False


def _has_explanatory_formatting(assistant_text):
    """Return True when the final answer is more than the bare short answer."""
    text = _strip_surrounding_markdown_emphasis(assistant_text)
    if _MARKDOWN_EMPHASIS_RE.search(text):
        return True
    if _MARKDOWN_LINK_RE.search(text):
        return True
    if _MARKDOWN_CODE_RE.search(text):
        return True
    if _has_parenthetical_aside(text):
        return True
    if _EM_DASH_RE.search(text):
        return True
    if _SEMICOLON_RE.search(text):
        return True
    if _MULTILINE_OR_TAB_RE.search(text):
        return True
    if _BLOCKQUOTE_OR_LIST_RE.search(text):
        return True
    if _has_non_entity_description(text):
        return True
    if _has_leading_pronoun_copula(text):
        return True
    if _EXPLANATORY_GLUE_RE.search(text):
        return True
    if _has_trailing_by_attribution(text):
        return True
    if _has_comma_capitalized_elaboration(text):
        return True
    if _has_leading_question_phrase(text):
        return True
    if _has_full_sentence_definition(text):
        return True
    if _has_indefinite_article_descriptive_phrase(text):
        return True
    if _has_rank_superlative_descriptive_phrase(text):
        return True
    return False


# ---------------------------------------------------------------------------
# Main hook
# ---------------------------------------------------------------------------

def decide(event):
    if not isinstance(event, dict):
        return _allow()

    if event.get("stop_hook_active") is False:
        return _allow()

    transcript_path = event.get("transcript_path")
    records = _load_records(transcript_path)
    if not records:
        return _allow()

    messages = _collect_messages(records)
    if not messages:
        return _allow()

    # Find the latest real user instruction (tool-result user turns are already
    # skipped) and the latest assistant turn, even if that turn has no text.
    user_text = ""
    for role, text in reversed(messages):
        if role == "user" and text:
            user_text = text
            break

    assistant_text = None
    for role, text in reversed(messages):
        if role == "assistant":
            assistant_text = text
            break

    if not user_text or not assistant_text:
        return _allow()

    if not _requests_short_answer(user_text):
        return _allow()

    if not _is_boolean_question(user_text) and _is_bare_boolean_answer(assistant_text):
        return _block(
            "The user requested a short/bare answer but did not ask a yes/no or "
            "true/false question, so a bare boolean/yes-no token such as "
            "'true', 'false', 'yes', or 'no' cannot be the requested short "
            "answer. Return only the short answer the prompt asks for, with "
            "no extra text, explanation, or formatting."
        )

    if not _has_explanatory_formatting(assistant_text):
        return _allow()

    return _block(
        "The user requested a short/bare answer, but the final response is not "
        "bare. It may be phrased as a leading question (for example 'What is a "
        "well?'), as a full-sentence definition (for example 'A campaign "
        "slogan for ...'), as an article-prefixed descriptive phrase (for "
        "example 'A hot air balloon'), as a rank/ordinal/superlative "
        "descriptive phrase (for example 'Second largest city in Germany'), "
        "or with explanatory formatting/asides such as markdown emphasis "
        "attached to extra explanation, parenthesized alternate "
        "titles/years/roles/'also called' glosses, em-dashes, explanatory "
        "glue, semicolon-separated explanations, multi-line/tab-separated "
        "text, leading pronoun/copula sentences such as 'It is Paris', "
        "comma-separated lists or cast/description phrases, trailing "
        "'by' attributions such as 'by R.E.M.', or comma-separated "
        "elaborations such as 'Dahlonega, Georgia' or 'Salt Lake City, "
        "Utah'. Return only the bare short answer with no question phrasing, "
        "definitions, descriptive phrases, explanatory markdown, parentheses, "
        "em-dashes, semicolons, multi-line text, explanations, lists, "
        "attributions, or extra qualifiers."
    )


if __name__ == "__main__":
    try:
        event = json.load(sys.stdin)
    except (json.JSONDecodeError, TypeError, ValueError):
        event = {}
    print(json.dumps(decide(event)))
