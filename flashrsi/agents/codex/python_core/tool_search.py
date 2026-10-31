"""Deferred Codex tools and BM25, ported from rust-v0.147.0.

Sources: core/src/tools/handlers/tool_search{,_spec}.rs,
tools/src/{tool_search,responses_api}.rs; pinned Cargo dependencies bm25 2.3.2,
rust-stemmers 1.2.0 (algorithms/english.sbl), deunicode 1.6.2, stop-words 0.9.0.
All production processing is Python. Equal BM25 scores retain registration
order; upstream ties inherit Rust HashSet iteration and have no stable order.
"""

from __future__ import annotations

import copy
import math
import struct
import sys
from collections import Counter
from functools import lru_cache
from pathlib import Path

ASSETS = Path(__file__).with_name("tool_assets")
VOWELS = frozenset("aeiouy")


@lru_cache(maxsize=1)
def _tables():
    return (ASSETS / "deunicode_pointers.bin").read_bytes(), (
        ASSETS / "deunicode_mapping.txt"
    ).read_bytes()


def _ascii_char(char):
    pointers, mapping = _tables()
    index = ord(char) * 3
    if index + 3 > len(pointers):
        return None
    first, second, length = pointers[index : index + 3]
    if length <= 2:
        return bytes((first, second))[:length].decode("ascii")
    offset = first | second << 8
    if offset + length > len(mapping):
        return None
    return mapping[offset : offset + length].decode("ascii")


def normalize(text):
    """deunicode_with_tofu_cow, including its lookahead space trimming."""
    prefix = 0
    while prefix < len(text) and ord(text[prefix]) < 127:
        prefix += 1
    if prefix == len(text):
        return text
    chars = [_ascii_char(char) for char in text[prefix:]]
    parts = [text[:prefix]]
    for index, value in enumerate(chars):
        following = chars[index + 1] if index + 1 < len(chars) else " "
        if value is None:
            parts.append("[?]")
        elif (
            len(value) > 1
            and value.endswith(" ")
            and following is not None
            and following.startswith(" ")
        ):
            parts.append(value[:-1])
        else:
            parts.append(value)
    return "".join(parts)


def _word_category(char):
    if "a" <= char <= "z":
        return "L"
    if "0" <= char <= "9":
        return "N"
    return {"_": "E", "'": "Q", ".": "B", ":": "Lmid", ",": "Nmid", ";": "Nmid"}.get(
        char, "O"
    )


def words(text):
    """UAX29 word rules on deunicode's ASCII output (WB5–WB13b)."""
    categories = [_word_category(char) for char in text]
    start = 0
    for index in range(1, len(text) + 1):
        joined = False
        if index < len(text):
            left, right = categories[index - 1 : index + 1]
            joined = left in {"L", "N", "E"} and right in {"L", "N", "E"}
            if index + 1 < len(text):
                after = categories[index + 1]
                joined |= left == after == "L" and right in {"Q", "B", "Lmid"}
                joined |= left == after == "N" and right in {"Q", "B", "Nmid"}
            if index >= 2:
                before = categories[index - 2]
                joined |= before == right == "L" and left in {"Q", "B", "Lmid"}
                joined |= before == right == "N" and left in {"Q", "B", "Nmid"}
        if not joined:
            if any(category in {"L", "N"} for category in categories[start:index]):
                yield text[start:index]
            start = index


def _short_vowel(word):
    return (
        len(word) >= 3
        and word[-3] not in VOWELS
        and word[-2] in VOWELS
        and word[-1] not in VOWELS | {"w", "x", "Y"}
    ) or (len(word) == 2 and word[0] in VOWELS and word[1] not in VOWELS)


def _suffix(word, suffixes):
    return next((suffix for suffix in suffixes if word.endswith(suffix)), None)


@lru_cache(maxsize=16384)
def stem(word):
    """The pinned Snowball English algorithm, retaining fixed region indices."""
    exception = {
        "skis": "ski",
        "skies": "sky",
        "dying": "die",
        "lying": "lie",
        "tying": "tie",
        "idly": "idl",
        "gently": "gentl",
        "ugly": "ugli",
        "early": "earli",
        "only": "onli",
        "singly": "singl",
    }
    if word in exception:
        return exception[word]
    if (
        word in {"sky", "news", "howe", "atlas", "cosmos", "bias", "andes"}
        or len(word) < 3
    ):
        return word
    word = word.removeprefix("'")
    letters = list(word)
    for index, char in enumerate(letters):
        if char == "y" and (index == 0 or letters[index - 1] in VOWELS):
            letters[index] = "Y"
    word = "".join(letters)
    r1 = next(
        (
            len(prefix)
            for prefix in ("gener", "commun", "arsen")
            if word.startswith(prefix)
        ),
        None,
    )
    if r1 is None:
        r1 = next(
            (
                index + 1
                for index in range(1, len(word))
                if word[index - 1] in VOWELS and word[index] not in VOWELS
            ),
            len(word),
        )
    r2 = next(
        (
            index + 1
            for index in range(r1 + 1, len(word))
            if word[index - 1] in VOWELS and word[index] not in VOWELS
        ),
        len(word),
    )
    suffix = _suffix(word, ("'s'", "'s", "'"))
    if suffix:
        word = word[: -len(suffix)]
    suffix = _suffix(word, ("sses", "ied", "ies", "us", "ss", "s"))
    if suffix == "sses":
        word = word[:-2]
    elif suffix in {"ied", "ies"}:
        word = word[:-3] + ("i" if len(word) >= 5 else "ie")
    elif suffix == "s" and any(char in VOWELS for char in word[:-2]):
        word = word[:-1]
    if word in {
        "inning",
        "outing",
        "canning",
        "herring",
        "earring",
        "proceed",
        "exceed",
        "succeed",
    }:
        return word.replace("Y", "y")
    suffix = _suffix(word, ("eedly", "ingly", "edly", "eed", "ing", "ed"))
    if suffix in {"eedly", "eed"}:
        if len(word) - len(suffix) >= r1:
            word = word[: -len(suffix)] + "ee"
    elif suffix and any(char in VOWELS for char in word[: -len(suffix)]):
        word = word[: -len(suffix)]
        if word.endswith(("at", "bl", "iz")):
            word += "e"
        elif word.endswith(("bb", "dd", "ff", "gg", "mm", "nn", "pp", "rr", "tt")):
            word = word[:-1]
        elif len(word) == r1 and _short_vowel(word):
            word += "e"
    if len(word) > 2 and word[-1] in {"y", "Y"} and word[-2] not in VOWELS:
        word = word[:-1] + "i"
    replacements = {
        "tional": "tion",
        "enci": "ence",
        "anci": "ance",
        "abli": "able",
        "entli": "ent",
        "izer": "ize",
        "ization": "ize",
        "ational": "ate",
        "ation": "ate",
        "ator": "ate",
        "alism": "al",
        "aliti": "al",
        "alli": "al",
        "fulness": "ful",
        "ousli": "ous",
        "ousness": "ous",
        "iveness": "ive",
        "iviti": "ive",
        "biliti": "ble",
        "bli": "ble",
        "ogi": "og",
        "fulli": "ful",
        "lessli": "less",
        "li": "",
    }
    suffix = _suffix(word, sorted(replacements, key=len, reverse=True))
    if suffix and len(word) - len(suffix) >= r1:
        preceding = word[-len(suffix) - 1] if len(word) > len(suffix) else ""
        if (suffix != "ogi" or preceding == "l") and (
            suffix != "li" or preceding in "cdeghkmnrt"
        ):
            word = word[: -len(suffix)] + replacements[suffix]
    replacements = {
        "tional": "tion",
        "ational": "ate",
        "alize": "al",
        "icate": "ic",
        "iciti": "ic",
        "ical": "ic",
        "ful": "",
        "ness": "",
        "ative": "",
    }
    suffix = _suffix(word, sorted(replacements, key=len, reverse=True))
    if (
        suffix
        and len(word) - len(suffix) >= r1
        and (suffix != "ative" or len(word) - len(suffix) >= r2)
    ):
        word = word[: -len(suffix)] + replacements[suffix]
    suffix = _suffix(
        word,
        sorted(
            (
                "al",
                "ance",
                "ence",
                "er",
                "ic",
                "able",
                "ible",
                "ant",
                "ement",
                "ment",
                "ent",
                "ism",
                "ate",
                "iti",
                "ous",
                "ive",
                "ize",
                "ion",
            ),
            key=len,
            reverse=True,
        ),
    )
    if suffix and len(word) - len(suffix) >= r2:
        if suffix != "ion" or (len(word) > 3 and word[-4] in "st"):
            word = word[: -len(suffix)]
    if word.endswith("e") and (
        len(word) - 1 >= r2 or (len(word) - 1 >= r1 and not _short_vowel(word[:-1]))
    ):
        word = word[:-1]
    elif word.endswith("ll") and len(word) - 1 >= r2:
        word = word[:-1]
    return word.replace("Y", "y")


@lru_cache(maxsize=1)
def _stopwords():
    return frozenset(
        normalize(word)
        for word in (ASSETS / "stopwords_english.txt").read_text().split("\n")
        if word
    )


def tokenize(text):
    return [
        stem(word)
        for word in words(normalize(text).lower())
        if word not in _stopwords()
    ]


def _f32(value):
    return struct.unpack("f", struct.pack("f", value))[0]


@lru_cache(maxsize=16384)
def token_index(token):
    """fxhash 0.2.1 hash32(str), including Rust str's 0xff terminator."""
    state = 0
    data = token.encode("utf-8")

    def update(word):
        nonlocal state
        state = (
            (((state << 5) | (state >> 27)) & 0xFFFFFFFF) ^ word
        ) * 0x27220A95 & 0xFFFFFFFF

    offset = 0
    while offset + 4 <= len(data):
        update(int.from_bytes(data[offset : offset + 4], sys.byteorder))
        offset += 4
    for byte in data[offset:]:
        update(byte)
    update(255)
    return state


class BM25:
    """bm25 2.3.2 Embedder/Scorer, including repeated query token scoring."""

    def __init__(self, documents):
        tokens = [
            [token_index(token) for token in tokenize(document)]
            for document in documents
        ]
        self.count = len(tokens)
        avgdl = _f32(sum(map(len, tokens)) / self.count) if self.count else 256.0
        avgdl = avgdl if avgdl > 0 else 256.0
        k1, b = _f32(1.2), _f32(0.75)
        self.embeddings, self.frequencies = [], Counter()
        for document in tokens:
            counts = Counter(document)
            self.frequencies.update(counts.keys())
            ratio = _f32(len(document) / avgdl)
            length_weight = _f32(_f32(1.0 - b) + _f32(b * ratio))
            self.embeddings.append(
                {
                    token: _f32(
                        _f32(frequency * _f32(k1 + 1.0))
                        / _f32(frequency + _f32(k1 * length_weight))
                    )
                    for token, frequency in counts.items()
                }
            )

    def search(self, query, limit=8):
        query = [token_index(token) for token in tokenize(query)]
        idfs = {
            token: _f32(
                math.log(
                    _f32(
                        1.0
                        + _f32(
                            _f32(self.count - self.frequencies[token] + 0.5)
                            / _f32(self.frequencies[token] + 0.5)
                        )
                    )
                )
            )
            for token in query
        }
        results = []
        for index, document in enumerate(self.embeddings):
            if not any(token in document for token in query):
                continue
            score = 0.0
            for token in query:
                score = _f32(score + _f32(idfs[token] * document.get(token, 0.0)))
            results.append((index, score))
        return sorted(results, key=lambda item: -item[1])[:limit]


def default_search_text(spec):
    parts = []

    def push(value):
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())

    def schema(value):
        push(value.get("description"))
        for name, child in sorted(value.get("properties", {}).items()):
            push(name)
            schema(child)
        if isinstance(value.get("items"), dict):
            schema(value["items"])
        for child in value.get("anyOf", []):
            schema(child)

    def tool(value):
        push(value.get("name"))
        if value.get("type") == "function":
            push(value["name"].replace("_", " "))
            push(value.get("description"))
            schema(value.get("parameters", {}))
        else:
            push(value.get("description"))
            push(value.get("format", {}).get("syntax"))

    if spec.get("type") == "namespace":
        push(spec["name"])
        push(spec.get("description"))
        for child in spec["tools"]:
            tool(child)
    else:
        tool(spec)
    return " ".join(parts)


def loadable_spec(spec):
    spec = copy.deepcopy(spec)
    if spec["type"] != "namespace":
        spec = {
            "type": "namespace",
            "name": "functions",
            "description": "",
            "tools": [spec],
        }
    if not spec.get("description", "").strip():
        spec["description"] = (
            ""
            if spec["name"] == "functions"
            else f"Tools in the {spec['name']} namespace."
        )
    for tool in spec["tools"]:
        tool["defer_loading"] = True
        tool.pop("output_schema", None)
    return spec


def search_spec(sources, *, omit_sources=False):
    names = {}
    for source in sources:
        if source and (source["name"] not in names or names[source["name"]] is None):
            names[source["name"]] = source.get("description")
    if omit_sources:
        section = "\n\n"
    else:
        budget = 512 * 1024
        description_budget = max(
            0,
            budget
            - max(0, len(names) - 1)
            - sum(2 + len(name.encode()) for name in names),
        )
        rendered = ""
        for name, description in sorted(names.items()):
            required = bool(rendered) + 2 + len(name.encode())
            if required > budget - len(rendered.encode()):
                continue
            rendered += ("\n" if rendered else "") + "- " + name
            if description is not None and description_budget >= 2:
                bounded = description.encode()[: description_budget - 2].decode(
                    "utf-8", errors="ignore"
                )
                rendered += ": " + bounded
                description_budget -= 2 + len(bounded.encode())
        section = (
            "\n\nYou have access to tools from the following sources:\n"
            + (rendered if names else "None currently enabled.")
            + "\n"
        )
    return {
        "type": "tool_search",
        "execution": "client",
        "description": "# Tool discovery\n\nSearches over deferred tool metadata with BM25 and exposes matching tools for the next model call."
        + section
        + "Some of the tools may not have been provided to you upfront, and you should use this tool (`tool_search`) to search for the required tools. For MCP tool discovery, always use `tool_search` instead of `list_mcp_resources` or `list_mcp_resource_templates`.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "number",
                    "description": "Maximum number of tools to return. Defaults to 8.",
                },
                "query": {
                    "type": "string",
                    "description": "Search query for deferred tools.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    }


class ToolSearch:
    def __init__(self, entries):
        self.entries = list(entries)
        self.engine = BM25([entry["search_text"] for entry in self.entries])

    def search(self, query, limit=8):
        tools = []
        for index, _ in self.engine.search(query, limit):
            spec = copy.deepcopy(self.entries[index]["output"])
            existing = next(
                (tool for tool in tools if tool["name"] == spec["name"]), None
            )
            if existing is None:
                tools.append(spec)
            else:
                existing["tools"].extend(spec["tools"])
        return tools
