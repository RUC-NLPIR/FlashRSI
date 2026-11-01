from __future__ import annotations
import contextlib, contextvars, copy, hashlib, json, logging, math, re, threading
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, NamedTuple, Optional, Sequence, Tuple
from urllib.parse import unquote_plus, urlparse
logger=logging.getLogger(__name__)
from .host_boundaries import redact_registered_vault_values, _redact_enabled


_SENSITIVE_QUERY_PARAMS = frozenset({
    "access_token", "refresh_token", "id_token", "token", "api_key", "apikey",
    "client_secret", "password", "auth", "jwt", "session", "secret", "key",
    "code", "signature", "x-amz-signature",
    "x-goog-signature", "sig",  # GCS V4 signed URLs, Azure SAS tokens
})


_PREFIX_PATTERNS = [
    # Some provider-issued ``sk-`` keys carry dot-delimited body segments (Alibaba
    # ``sk-sp-…``/``sk-ws-…``). Each unit is one body char optionally preceded by
    # a single dot, so the body ends on its last non-dot char (sentence punctuation
    # is never consumed) and can never span ``..``: the ``sk-pro...EFGH`` display
    # mask is left alone by a second redaction pass instead of collapsing to
    # ``***``. Kept free of nested unbounded repeats so the pattern passes the
    # same structural gate plugins must.
    r"sk-[A-Za-z0-9_-](?:\.?[A-Za-z0-9_-]){9,}",
    r"ghp_[A-Za-z0-9]{10,}",            # GitHub PAT (classic)
    r"github_pat_[A-Za-z0-9_]{10,}",    # GitHub PAT (fine-grained)
    r"gho_[A-Za-z0-9]{10,}",            # GitHub OAuth access token
    r"ghu_[A-Za-z0-9]{10,}",            # GitHub user-to-server token
    r"ghs_[A-Za-z0-9]{10,}",            # GitHub server-to-server token
    r"ghr_[A-Za-z0-9]{10,}",            # GitHub refresh token
    r"xapp-\d+-[A-Za-z0-9-]{10,}",      # Slack app-Level token
    r"xox[baprs]-[A-Za-z0-9-]{10,}",    # Slack bot/app/user tokens
    r"AIza[A-Za-z0-9_-]{30,}",          # Google API keys
    r"pplx-[A-Za-z0-9]{10,}",           # Perplexity
    r"fal_[A-Za-z0-9_-]{10,}",          # Fal.ai
    r"fc-[A-Za-z0-9]{10,}",             # Firecrawl
    r"bb_live_[A-Za-z0-9_-]{10,}",      # BrowserBase
    r"gAAAA[A-Za-z0-9_=-]{20,}",        # Codex encrypted tokens
    r"AKIA[A-Z0-9]{16}",                # AWS Access Key ID
    r"sk_live_[A-Za-z0-9]{10,}",        # Stripe secret key (live)
    r"sk_test_[A-Za-z0-9]{10,}",        # Stripe secret key (test)
    r"rk_live_[A-Za-z0-9]{10,}",        # Stripe restricted key
    r"SG\.[A-Za-z0-9_-]{10,}",          # SendGrid API key
    r"hf_[A-Za-z0-9]{10,}",             # HuggingFace token
    r"r8_[A-Za-z0-9]{10,}",             # Replicate API token
    r"npm_[A-Za-z0-9]{10,}",            # npm access token
    r"pypi-[A-Za-z0-9_-]{10,}",         # PyPI API token
    r"dop_v1_[A-Za-z0-9]{10,}",         # DigitalOcean PAT
    r"doo_v1_[A-Za-z0-9]{10,}",         # DigitalOcean OAuth
    # AgentMail API key: ``am_`` / ``am_org_`` + an opaque alphanumeric body. The body has no ``_``/``-``,
    # which is what separates it from ``am_example_identifier_123`` (#10983); public docs pin only the
    # prefix, so the charset stays broad and the length floor does the discriminating.
    r"am_(?:org_)?[A-Za-z0-9]{20,}",
    r"sk_[A-Za-z0-9_]{10,}",            # ElevenLabs TTS key (sk_ underscore, not sk- dash)
    r"tvly-[A-Za-z0-9]{10,}",           # Tavily search API key
    r"exa_[A-Za-z0-9]{10,}",            # Exa search API key
    r"gsk_[A-Za-z0-9]{10,}",            # Groq Cloud API key
    r"syt_[A-Za-z0-9]{10,}",            # Matrix access token
    r"retaindb_[A-Za-z0-9]{10,}",       # RetainDB API key
    r"hsk-[A-Za-z0-9]{10,}",            # Hindsight API key
    r"mem0_[A-Za-z0-9]{10,}",           # Mem0 Platform API key
    r"brv_[A-Za-z0-9]{10,}",            # ByteRover API key
    r"xai-[A-Za-z0-9]{30,}",            # xAI (Grok) API key
    r"ntn_[A-Za-z0-9]{10,}",            # Notion internal integration token
    r"fw-[A-Za-z0-9]{30,}",             # Fireworks AI API key
    r"fw_[A-Za-z0-9]{30,}",             # Fireworks AI API key
    r"fpk_[A-Za-z0-9]{30,}",            # Fireworks AI project key
    # GitLab token families (each keeps a full literal prefix for the pre-screen).
    # Ported from openclaw/openclaw#112954; follow-up invited in #4541.
    r"glpat-[A-Za-z0-9_\-]{10,}",       # GitLab personal access token
    r"gloas-[A-Za-z0-9_\-]{10,}",       # GitLab OAuth application secret
    r"gldt-[A-Za-z0-9_\-]{10,}",        # GitLab deploy token
    r"glrt-[A-Za-z0-9_.\-]{10,}",       # GitLab runner authentication token (routable tokens are dotted)
    r"glrtr-[A-Za-z0-9_.\-]{10,}",      # GitLab runner registration token (routable)
    r"glcbt-[A-Za-z0-9_\-]{10,}",       # GitLab CI/CD job token
    r"glptt-[A-Za-z0-9_\-]{10,}",       # GitLab pipeline trigger token
    r"glft-[A-Za-z0-9_\-]{10,}",        # GitLab feed token
    r"glimt-[A-Za-z0-9_\-]{10,}",       # GitLab incoming mail token
    r"glagent-[A-Za-z0-9_\-]{10,}",     # GitLab agent (KAS) token
    r"glsoat-[A-Za-z0-9_\-]{10,}",      # GitLab service-account access token
    r"glffct-[A-Za-z0-9_\-]{10,}",      # GitLab feature-flags client token
    r"glwt-[A-Za-z0-9_\-]{10,}",        # GitLab workspace token
    r"GR1348941[A-Za-z0-9_\-]{10,}",    # GitLab legacy runner registration token
    r"pk-lf-[A-Za-z0-9\-]{8,}",         # Langfuse public key (sk-lf- already covered by sk- pattern)
]


_SECRET_ENV_NAMES = r"(?:API_?KEY|KEY|TOKEN|SECRET|PASSWORD|PASSWD|PASS|PW|CREDENTIAL|AUTH)"


_ENV_ASSIGN_RE = re.compile(rf"([A-Z0-9_]{{0,50}}{_SECRET_ENV_NAMES}[A-Z0-9_]{{0,50}})\s*=\s*(['\"]?)(\S+)\2")


_ENV_ASSIGN_LOWER_RE = re.compile(
    r"(?<![a-z0-9_])([a-z0-9_]+(?:_|^)(?:key|pass|pw|token|secret|password|passwd|credential|auth)(?=[^a-z0-9_]|$))\s*=\s*(['\"]?)(\S+)\2",
    re.IGNORECASE,
)


_SECRET_CFG_NAMES = r"(?:api[ _.\-]?key|token|secret|passwd|password|credential|auth)"


_LINE_NUMBER_GUTTER = r"(?:[0-9]+(?:[|:\-]|\t)[ \t]*)?"


_CFG_VALUE = r"(['\"]?)([^\s&]+?)\2(?=[\s&]|$)"


_CFG_SECRET_WORD_RE = re.compile(_SECRET_CFG_NAMES, re.IGNORECASE)


_ENV_LOOKUP_VALUE_RE = re.compile(r"^(?:os\.(?:getenv|environ)|process\.env|\$ENV\{)")


_CFG_DOTTED_RE = re.compile(
    rf"(?<![A-Za-z0-9_.\-])"
    rf"([A-Za-z0-9_\-]++\.[A-Za-z0-9_.\-]*{_SECRET_CFG_NAMES}[A-Za-z0-9_.\-]*+"
    rf"|[A-Za-z0-9_.\-]*{_SECRET_CFG_NAMES}[A-Za-z0-9_.\-]*\.[A-Za-z0-9_.\-]++)"
    rf"={_CFG_VALUE}",
    re.IGNORECASE,
)


_CFG_ANCHORED_RE = re.compile(
    rf"(^[ \t]*{_LINE_NUMBER_GUTTER}(?:export[ \t]+)?[A-Za-z0-9_\-]*{_SECRET_CFG_NAMES}[A-Za-z0-9_\-]*)={_CFG_VALUE}",
    re.IGNORECASE | re.MULTILINE,
)


_YAML_CFG_NAMES = r"(?:api[ _.\-]?key|token|secret|passwd|password|credential)"


_YAML_ASSIGN_RE = re.compile(
    rf"(^[ \t]*+{_LINE_NUMBER_GUTTER}[A-Za-z0-9_.\-]*{_YAML_CFG_NAMES}[A-Za-z0-9_.\-]*+)(:[ \t]*+)(?!['\"])([^\s&]++)",
    re.IGNORECASE | re.MULTILINE,
)


_KEY_KEYWORD_RE = re.compile(
    r"(?:api|auth|access|refresh|session|secret)[ _.\\-]?(?:key|token)"
    r"|token|secret|passwd|password|pass|pw|credential|auth|key",
    re.IGNORECASE,
)


_STRONG_KEY_KEYWORD_RE = re.compile(
    r"(?:api|auth|access|refresh|session|id|bearer)[ _.\\-]?(?:key|token)"
    r"|key[ _.\\-]?material|secret|passwd|password|pass|pw|credential|auth|bearer",
    re.IGNORECASE,
)


_PASSWORD_KEY_RE = re.compile(r"passwd|password|pass|pw", re.IGNORECASE)


_SHELL_VAR_REF = r"\$(?:\{[A-Za-z_]\w*[^}]*\}|[A-Za-z_]\w*)"


_PATH_OR_VAR_VALUE_RE = re.compile(rf"^(?:{_SHELL_VAR_REF}|\$\(|~|/)(?:[\w./:-]|{_SHELL_VAR_REF})*$")


_OPAQUE_PATH_SEGMENT_RE = re.compile(r"(?=[^.]*[a-z])(?=[^.]*[A-Z])(?=[^.]*[0-9])[^.]{16,}")


def _is_word_start(s: str, i: int) -> bool:
    """True if position ``i`` in ``s`` begins a word (edge, non-letter before, camelCase/acronym boundary)."""
    if i == 0:
        return True
    prev, cur = s[i - 1], s[i]
    if not prev.isalpha() or (cur.isupper() and prev.islower()):  # clientSecret
        return True
    return cur.isupper() and prev.isupper() and i + 1 < len(s) and s[i + 1].islower()  # APIToken


def _is_word_end(s: str, j: int, *, allow_plural: bool = True) -> bool:
    """True if position ``j`` (exclusive end) in ``s`` ends a word; one trailing ``s`` is absorbed."""
    if j >= len(s):
        return True
    cur = s[j]
    if not cur.isalpha() or (cur.isupper() and s[j - 1].islower()):  # secretKey
        return True
    return allow_plural and cur in "sS" and _is_word_end(s, j + 1, allow_plural=False)


def _has_word_bounded_keyword(key: str, keyword_re: re.Pattern[str]) -> bool:
    """True if ``keyword_re`` matches ``key`` at a word boundary (see _KEY_KEYWORD_RE)."""
    return any(_is_word_start(key, m.start()) and _is_word_end(key, m.end()) for m in keyword_re.finditer(key))


def _key_has_secret_keyword(key: str) -> bool:
    """Post-match key validator: ``API_KEY``/``DB_PW`` count, ``KEYBOARD``/``secretary`` do not."""
    return _has_word_bounded_keyword(key, _KEY_KEYWORD_RE)


def _looks_like_opaque_credential(value: str) -> bool:
    """Credential-like shape test for ambiguous ``token``/``key`` values, so short
    technical scalars (``CPU``, ``local``) are not masked merely for their key name."""
    if value == "***" or value.startswith("«redacted:"):
        return True
    if len(value) >= 16 and re.fullmatch(r"[A-Fa-f0-9]+", value):
        return True
    if len(value) >= 20 and re.fullmatch(r"[A-Za-z0-9_./+=-]+", value):
        return True
    if len(value) < 12:
        return False
    return sum(bool(re.search(p, value)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]")) >= 2


def _should_redact_assignment(key: str, value: str, *, check_keyword: bool) -> bool:
    """Shared gate for the ENV / JSON / YAML assignment passes: skip programmatic env
    lookups used as values, optionally require a word-bounded keyword in the key,
    then redact when the key is unambiguously credential-bearing or the value looks opaque."""
    # Programmatic env lookups reference variable *names*, not secret values — masking them corrupts code
    # snippets in prose/log contexts (issue #2852): ``KEY=os.getenv('X')``.
    # Same programmatic-env-lookup exception as _redact_env above (issue #2852): "apiKey": "os.getenv('X')"
    # is a code snippet, not a leaked secret value.
    # Same programmatic-env-lookup exception as _redact_env above (issue #2852): api_key: os.getenv('X') is
    # a code snippet, not a leaked secret value.
    if _ENV_LOOKUP_VALUE_RE.match(value):
        return False
    # An earlier pass already masked this value (``***`` or the ``«redacted:…»`` sentinel). Masking it
    # again only erases what the sentinel deliberately kept — the vendor label (``Digest ***`` →
    # ``***``, ``«redacted:ghp_…»`` → ``«redacted-secret»``). Same guard _redact_python_repr_fields uses.
    if value == "***" or value.startswith("«redacted"):
        return False
    if check_keyword and not _key_has_secret_keyword(key):
        return False
    # A shell rc's ``SSH_AUTH_SOCK=$HOME/.ssh/agent.sock`` is configuration the agent must keep
    # readable; only password-class keys mask a path/variable reference.
    if _PATH_OR_VAR_VALUE_RE.match(value) and not _has_word_bounded_keyword(key, _PASSWORD_KEY_RE):
        # ``$VAR`` is an unambiguous reference. A bare ``/...`` or ``~...`` is not:
        # ``/home/u/.docker`` and ``/8f3kd9sKd0als...`` have the same shape, so every
        # segment has to look like a path (see _OPAQUE_PATH_SEGMENT_RE) before the
        # value is treated as configuration.
        if value[0] == "$" or not any(_OPAQUE_PATH_SEGMENT_RE.fullmatch(seg) for seg in value.split("/")):
            return False
    return (_has_word_bounded_keyword(key, _STRONG_KEY_KEYWORD_RE)
            or _looks_like_opaque_credential(value))


_JSON_KEY_NAMES = r"(?:api_?[Kk]ey|token|secret|password|access_token|refresh_token|auth_token|bearer|secret_value|raw_secret|secret_input|key_material)"


_JSON_FIELD_RE = re.compile(rf'("{_JSON_KEY_NAMES}")\s*:\s*"([^"]+)"', re.IGNORECASE)


_JSON_FIELD_ESCAPED_RE = re.compile(rf'((\\+)"{_JSON_KEY_NAMES}\2")\s*:\s*\2"([^"\\]+)\2"', re.IGNORECASE)


_PYTHON_REPR_SECRET_KEYS = frozenset({
    "access_token",
    "refresh_token",
    "id_token",
    "auth_token",
    "token",
    "api_key",
    "apikey",
    "client_secret",
    "secret",
    "password",
    "passwd",
    "private_key",
    "credential",
    "credentials",
    "authorization",
    "bearer",
    "secret_value",
    "raw_secret",
    "secret_input",
    "key_material",
})


_PYTHON_REPR_ENV_SUFFIXES = (
    "_API_KEY",
    "_TOKEN",
    "_SECRET",
    "_PASSWORD",
    "_PASSWD",
    "_CREDENTIAL",
    "_CREDENTIALS",
)


_PYTHON_REPR_CREDENTIAL_SUFFIXES = (
    "apikey",
    "api_key",
    "token",
    "secret",
    "password",
    "passwd",
    "credential",
    "credentials",
)


_PYTHON_REPR_FIELD_RE = re.compile(
    r"'(?P<key>[A-Za-z_][A-Za-z0-9_]*)'(?P<sep>\s*:\s*)"
    r"(?:"
    r"(?P<single_prefix>[bB]?)'(?P<single_value>(?:\\.|[^'\\])+)'"
    r"|(?P<double_prefix>[bB]?)\"(?P<double_value>(?:\\.|[^\"\\])+)\""
    r")"
)


_AUTH_HEADER_RE = re.compile(r"((?:Proxy-)?Authorization:\s*)([A-Za-z][\w.+-]*\s+)?([^\s\"']+)", re.IGNORECASE)


SECRET_HEADER_NAME_LIST = ("x-api-key", "x-goog-api-key", "api-key", "apikey", "x-api-token", "x-auth-token", "x-access-token")


_SECRET_HEADER_NAMES = rf"(?:{'|'.join(SECRET_HEADER_NAME_LIST)})"


_SECRET_HEADER_RE = re.compile(rf"({_SECRET_HEADER_NAMES}\s*:\s*)(\S+)", re.IGNORECASE)


_TELEGRAM_RE = re.compile(r"(?<!\d)(bot)?(\d{8,}):([-A-Za-z0-9_]{30,})")


_PRIVATE_KEY_RE = re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----")


_DB_CONNSTR_RE = re.compile(
    r"((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:\s]+:)([^@\s]+)(@)",
    re.IGNORECASE,
)


_URL_BARE_TOKEN_RE = re.compile(
    r"((?:https?|wss?|git|ssh|ftp|ftps|sftp)://)"  # scheme
    r"([^\s:@/]{8,})"                               # bare token (no colon/slash/@), 8+ chars
    r"(@[^\s]+)",                                   # @host...
    re.IGNORECASE,
)


_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{10,}(?:\.[A-Za-z0-9_=-]{4,}){0,2}")


_SIGNAL_PHONE_RE = re.compile(r"(\+[1-9]\d{6,14})(?![A-Za-z0-9])")


_STRICT_URL_PARAM_RE = re.compile(r"([?#&;])([A-Za-z0-9_.~+%\-]+)=([^#&;\s\"'<>]*)")


_STRICT_URL_USERINFO_RE = re.compile(r"//[^/\s?#@]+@")


_FORM_BODY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]*=[^&\s]*(?:&[A-Za-z_][A-Za-z0-9_.-]*=[^&\s]*)+$")


_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f\u200b-\u200f\u2028-\u202f\u2060\ufeff]")


_TOKEN_BODY_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-.")


def _compile_prefix_matcher(patterns: list) -> re.Pattern[str]:
    return re.compile(r"(?<![A-Za-z0-9_-])(" + "|".join(patterns) + r")(?![A-Za-z0-9_-])")


_PREFIX_RE = _compile_prefix_matcher(_PREFIX_PATTERNS)


_ZHIPU_API_KEY_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])([0-9a-f]{32}\.[A-Za-z0-9]{16,})(?![A-Za-z0-9_.-])"
)


def _mask_control_split_tokens(text: str, mask_fn) -> str:
    """Mask tokens whose body is split by control/zero-width characters.

    Match on a control-stripped copy, then mask the corresponding span in the
    ORIGINAL — only when that span holds solely token-body and control chars, so
    a match can never cross into another line's unrelated text.

    A credential like ``sk-abc\\x1bdef456…`` or ``ghp_abc\\n123def…`` has its token body interrupted, so the
    contiguous _PREFIX_RE cannot match it and the secret leaks verbatim (issue #77484). ``EXA_API_KEY=*** is
    rejected).
    """
    stripped = _CONTROL_CHARS_RE.sub("", text)
    if stripped == text:
        return text
    orig_idx = [i for i, c in enumerate(text) if not _CONTROL_CHARS_RE.match(c)]
    out, matches = list(text), []
    for m in _PREFIX_RE.finditer(stripped):
        start_orig = orig_idx[m.start(1)]
        end_orig = orig_idx[m.end(1) - 1] + 1
        span = text[start_orig:end_orig]
        # Self-matching fragment AND a span crossing a LINE boundary: do NOT join
        # (``ghp_<tok>\nbutton`` would mask ``button``; the prefix pass handles the
        # fragment). Non-newline controls (ESC, ZWSP) never legitimately sit
        # between a token and prose, so there the join proceeds regardless.
        if ("\n" in span or "\r" in span) and _PREFIX_RE.search(span):
            continue
        # Reject spans containing a non-token char (``sk_abc…\nTAVILY_API_KEY=``
        # matched across lines) and matches running into a ``KEY=`` name.
        if (all(c in _TOKEN_BODY_CHARS or _CONTROL_CHARS_RE.match(c) for c in span)
                and (end_orig >= len(text) or text[end_orig] != "=")):
            matches.append((start_orig, end_orig, mask_fn(m.group(1))))
    for start_orig, end_orig, replacement in reversed(matches):
        out[start_orig:end_orig] = list(replacement)
    return "".join(out)


_DISPLAY_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\x80-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u2064]")


def mask_secret(value: str, *, head: int = 4, tail: int = 4, floor: int = 12,
                placeholder: str = "***", empty: str = "") -> str:
    """Mask a secret for display (``hermes config`` / ``status`` / ``dump``):
    ``sk-p...7890``; shorter than ``floor`` (after control-byte stripping) →
    ``placeholder``; falsy → ``empty``."""
    value = _DISPLAY_CONTROL_RE.sub("", value) if value else value
    if not value:
        return empty
    return placeholder if len(value) < floor else f"{value[:head]}...{value[-tail:]}"


def _mask_token(token: str) -> str:
    """Mask a log token — 18-char floor, preserves 6 prefix / 4 suffix; empty → ``***``."""
    if not token:
        return "***"
    return mask_secret(token, head=6, tail=4, floor=18)


def _is_python_repr_secret_key(key: str) -> bool:
    """Return True for exact secret keys or credential-suffixed key names."""
    folded = key.casefold()
    if folded in _PYTHON_REPR_SECRET_KEYS:
        return True
    if key.isupper() and key.endswith(_PYTHON_REPR_ENV_SUFFIXES):
        return True
    # Mixed/camel-case keys ending in a credential word (``UserPassword``,
    # ``sessionToken``, ``clientApiKey``) — the exact-set and uppercase-suffix
    # rules above miss these. Suffix-only matching keeps metadata names like
    # ``TOKEN_COUNT`` / ``PASSWORD_POLICY`` / ``SECRET_NAME`` untouched.
    # Class widened per OpenHands/software-agent-sdk#4508 (their dict-entry
    # redaction was uppercase-only and leaked mixed-case keys).
    return folded.endswith(_PYTHON_REPR_CREDENTIAL_SUFFIXES)


def _redact_python_repr_fields(text: str) -> str:
    """Fully mask credential fields in Python mapping ``repr`` output."""
    def _sub(match: re.Match) -> str:
        key = match.group("key")
        if not _is_python_repr_secret_key(key):
            return match.group(0)

        single_value = match.group("single_value")
        if single_value is not None:
            prefix = match.group("single_prefix") or ""
            quote = "'"
            value = single_value
        else:
            prefix = match.group("double_prefix") or ""
            quote = '"'
            value = match.group("double_value")

        # Mapping repr can contain code-shaped fixture values too. Preserve
        # programmatic env lookups just like the ENV/JSON/YAML passes do.
        if _ENV_LOOKUP_VALUE_RE.match(value):
            return match.group(0)
        # An upstream pass (MCP probe header scrub, _mask_token) already masked this
        # value; re-masking would erase the scheme word it deliberately kept
        # (``'Authorization': 'Digest ***'`` → ``'***'``).
        if "***" in value or value.startswith("«redacted:"):
            return match.group(0)
        # Do not retain head/tail characters here: escaped repr atoms can cross
        # a slicing boundary and leave an unescaped quote behind. A full mask is
        # parseable for both str and bytes values and leaks no opaque bytes.
        return f"'{key}'{match.group('sep')}{prefix}{quote}***{quote}"

    return _PYTHON_REPR_FIELD_RE.sub(_sub, text)


def _redact_query_string(query: str) -> str:
    """Replace values of sensitive ``k=v&k=v`` params with ``***``; others pass through."""
    if not query:
        return query
    return "&".join(
        f"{key}=***" if sep and key.lower() in _SENSITIVE_QUERY_PARAMS else pair
        for pair in query.split("&") for key, sep, _ in (pair.partition("="),)
    )


def _canonical_url_param_name(name: str) -> str:
    """Decode a URL parameter name (up to 3 unquote rounds) for case-insensitive matching."""
    decoded = name
    for _ in range(3):
        next_value = unquote_plus(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    folded = decoded.casefold()
    # Preserve policy names that are canonically hyphenated (for example
    # x-amz-signature) before accepting underscore-normalized aliases.
    return folded if folded in _SENSITIVE_QUERY_PARAMS else folded.replace("-", "_")


def _redact_strict_url_credentials(text: str) -> str:
    """Strict egress-boundary redaction of URL credentials (absolute, relative and
    network references); preserves keys, separators, public params, hosts, paths."""
    text = _STRICT_URL_PARAM_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}=***"
        if _canonical_url_param_name(m.group(2)) in _SENSITIVE_QUERY_PARAMS else m.group(0), text)
    return _STRICT_URL_USERINFO_RE.sub("//***:***@", text)


def _redact_form_body(text: str) -> str:
    """Redact sensitive values when the ENTIRE text is a clean ``k=v&k=v`` body."""
    if not text or "\n" in text or "&" not in text or not _FORM_BODY_RE.match(text.strip()):
        return text
    return _redact_query_string(text.strip())


def _mask_token_nonreusable(token: str) -> str:
    """Redact a prefix-matched credential to a NON-REUSABLE sentinel: no head/tail
    chars (an agent once wrote a truncated-looking mask back into a config file),
    only the vendor prefix label so the credential KIND stays visible.

    * cannot be mistaken for a usable-but-truncated key, so an agent that reads it from a config file and
    writes it back does NOT corrupt the stored credential into a dead 13-char string (issue #35519); and *
    still does not leak the secret material (no head/tail chars).
    """
    label = next((sub for sub in _PREFIX_SUBSTRINGS if token.startswith(sub)), "") if token else ""
    return f"«redacted:{label}…»" if label else "«redacted-secret»"


def _assignment_sub(render, *, check_keyword: bool):
    """re.sub callback: keep the match unless the key/value pair (groups[0], groups[-1]) needs redaction."""
    def _sub(m):
        groups = m.groups()
        if not _should_redact_assignment(groups[0], groups[-1], check_keyword=check_keyword):
            return m.group(0)
        return render(groups)
    return _sub


def _redact_assignments(text: str, *, mask_nonreusable: bool = False) -> str:
    """ENV / config / JSON / YAML assignment passes (skipped for code files). Passes
    that would match ``token=``/``key=`` URL params skip ``://`` text (web-URL query
    params are intentionally passed through, see redact_sensitive_text).

    ``mask_nonreusable`` masks the assignments with the ``«redacted:…»`` sentinel that
    ``file_read=True`` already uses for prefix-matched credentials. Without it an agent
    that read a secret-bearing file would hold a head/tail mask shaped like a real but
    truncated key and could write it back as a dead credential (#35519)."""
    mask = _mask_token_nonreusable if mask_nonreusable else _mask_token
    if "=" in text:
        _redact_env = _assignment_sub(lambda g: f"{g[0]}={g[1]}{mask(g[2])}{g[1]}", check_keyword=True)
        text = _ENV_ASSIGN_RE.sub(_redact_env, text)
        if "://" not in text:  # lowercase names would match URL params
            # Skip URLs — the query string may contain ``token=``/``key=`` params that are intentionally
            # passed through (see note near the bottom of this function; _redact_strict_url_credentials
            # handles the opt-in case). The uppercase regex above is all-caps-only, so it never matches URL
            # params; the lowercase one would (issue #77484).
            text = _ENV_ASSIGN_LOWER_RE.sub(_redact_env, text)
        # The keyword pre-gate is exact and matters: _CFG_DOTTED_RE backtracks
        # quadratically on long unbroken [A-Za-z0-9_.\-] runs.
        # Lowercase/dotted config keys (issue #16413). Skip URLs entirely — web-URL query params are
        # intentionally passed through (see note near the bottom of this function); _DB_CONNSTR_RE still
        # guards connection-string passwords. Extra gate: every _CFG_*_RE match requires a secret keyword in
        # the key, so a text without any secret keyword cannot match — skipping is exact. This matters
        # because _CFG_DOTTED_RE backtracks quadratically on long unbroken [A-Za-z0-9_.\-] runs (e.g.
        # base64/hex blobs in compaction payloads); the linear keyword scan prevents that pathological path
        # on secret-free text.
        if "://" not in text and _CFG_SECRET_WORD_RE.search(text):
            text = _CFG_DOTTED_RE.sub(_redact_env, text)
            text = _CFG_ANCHORED_RE.sub(_redact_env, text)

    if ":" in text and '"' in text:
        text = _JSON_FIELD_RE.sub(
            _assignment_sub(lambda g: f'{g[0]}: "{mask(g[1])}"', check_keyword=False), text)
        if '\\"' in text:
            text = _JSON_FIELD_ESCAPED_RE.sub(
                _assignment_sub(lambda g: f'{g[0]}: {g[1]}"{mask(g[2])}{g[1]}"', check_keyword=False), text)

    # Python mapping repr fields ({'API_KEY': '…'}): single-quoted, so the JSON rule
    # above never sees them — the traceback / pytest-introspection leak shape.
    if ":" in text and "'" in text:
        text = _redact_python_repr_fields(text)

    # YAML after JSON: quoted values are handled there (_YAML_ASSIGN_RE skips quotes).
    if ":" in text and "://" not in text:
        text = _YAML_ASSIGN_RE.sub(
            _assignment_sub(lambda g: f"{g[0]}{g[1]}{mask(g[2])}", check_keyword=True), text)
    return text


def _redact_url_credentials(text: str, code_file: bool) -> str:
    """DB connection-string passwords and bare-token URL userinfo (``://`` text only)."""
    def _redact_db(m):
        # code_file: a pure ``{...}`` password is an f-string template reference
        # (f"postgresql://{user}:{pass}@{host}"), not a literal credential.
        pw = m.group(2)
        if code_file and pw.startswith("{") and pw.endswith("}"):
            return m.group(0)
        return f"{m.group(1)}***{m.group(3)}"
    text = _DB_CONNSTR_RE.sub(_redact_db, text)
    return _URL_BARE_TOKEN_RE.sub(lambda m: f"{m.group(1)}{_mask_token(m.group(2))}{m.group(3)}", text)


def _redact_phone(m):
    phone = m.group(1)
    keep = 2 if len(phone) <= 8 else 4
    return phone[:keep] + "****" + phone[-keep:]


def redact_sensitive_text(text: str, *, force: bool = False, code_file: bool = False,
                          file_read: bool = False, secret_file: bool = False,
                          redact_url_credentials: bool = False) -> str:
    """Apply all redaction patterns to a block of text.

    Safe on any string. Enabled by default (``security.redact_secrets: false``
    disables); ``force=True`` is for safety boundaries that must never return
    raw secrets regardless.

    ``redact_url_credentials=True``: also redact credential-named query params
    and the entire URL userinfo (``***:***@``) — off by default because OAuth-callback /
    magic-link / pre-signed URLs must survive ordinary tool flows unchanged.
    ``code_file=True``: skip the ENV/JSON assignment passes for known source
    code (``MAX_TOKENS=***``, ``"apiKey": "test"`` fixtures). ``file_read=True``
    (implies code_file unless ``secret_file``): prefix-matched credentials become a
    non-reusable sentinel (``«redacted:ghp_…»``) instead of a head/tail mask an agent
    could write back into config.yaml as a dead credential.
    Every regex sits behind a cheap substring gate that its pattern requires,
    so the gates are never false-negative.

    Set code_file=True to also skip the Python-repr mapping pass (``{'API_KEY': '…'}``
    fixtures in source); pytest/exception diagnostic lines get a narrow pass in
    redact_terminal_output instead.

    Set file_read=True for file *content* returned to the agent (read_file / search_files / cat). The old
    mask looked like a real-but-truncated key, so an agent reading it from config.yaml and writing it back
    silently corrupted the stored credential into a dead 13-char value → 401 (issue #35519). The sentinel is
    syntactically invalid as a token, so it can't be mistaken for a usable key or written back as one.

    Set ``secret_file=True`` when the caller has already classified the SOURCE as secret-bearing
    (``_is_secret_file_arg``: command reads on the terminal side, resolved tool paths on the
    file side). It re-enables the ENV/JSON/YAML assignment passes that ``file_read`` would
    otherwise skip, so an opaque prefix-less credential assigned to a credential-shaped key is
    masked instead of passed through in cleartext (issue #110567). With ``file_read=True`` those
    assignments are masked with the non-reusable sentinel, so the #35519 write-back hazard stays
    closed. ``secret_file`` is authoritative: it wins over ``code_file``, so a caller cannot be
    fail-open by setting both. Files that are not secret-bearing (any source file, a project's own
    ``config.yaml``) keep the code_file behaviour: ``MAX_TOKENS: 100`` and ``"apiKey": "test"``
    fixtures are untouched.
    """
    if text is None:
        return None
    text = text if isinstance(text, str) else str(text)
    if not text:
        return text
    # Vault secrets are a hard model-egress boundary: scrubbed regardless of the redact_secrets preference.
    text = redact_registered_vault_values(text)
    if not (force or _redact_enabled()):
        return text
    # ``secret_file`` is authoritative: a caller that classified the source as secret-bearing must not
    # be silently fail-open because another flag (code_file, or file_read implying it) was also set.
    code_file = (code_file or file_read) and not secret_file

    # Control/zero-width chars can split a token body so _PREFIX_RE alone misses it.
    if _has_known_prefix_substring(text):
        _prefix_sub = _mask_token_nonreusable if file_read else _mask_token
        # Control/zero-width chars (\\n, \\r, ESC, U+200B, …) split a token body so _PREFIX_RE cannot match
        # across them — a secret smuggled as ``sk-abc\\x1bdef…`` leaks verbatim (issue #77484). Mask such
        # runs by first matching on a control-stripped copy, then re-masking the corresponding span in the
        # original (the stripped copy and the original are aligned 1:1 for non-control chars).
        text = _mask_control_split_tokens(text, _prefix_sub)
        text = _PREFIX_RE.sub(lambda m: _prefix_sub(m.group(1)), text)

    if "." in text:
        _zhipu_sub = _mask_token_nonreusable if file_read else _mask_token
        text = _ZHIPU_API_KEY_RE.sub(lambda m: _zhipu_sub(m.group(1)), text)

    if not code_file:
        text = _redact_assignments(text, mask_nonreusable=file_read)

    if "uthorization" in text or "UTHORIZATION" in text:  # cheapest gate over every casing
        text = _AUTH_HEADER_RE.sub(lambda m: m.group(1) + (m.group(2) or "") + _mask_token(m.group(3)), text)

    if ":" in text:
        text = _SECRET_HEADER_RE.sub(lambda m: m.group(1) + _mask_token(m.group(2)), text)
        text = _TELEGRAM_RE.sub(lambda m: f"{m.group(1) or ''}{m.group(2)}:***", text)

    if "BEGIN" in text and "-----" in text:
        text = _PRIVATE_KEY_RE.sub("[REDACTED PRIVATE KEY]", text)

    # Database connection string passwords. With code_file=True, a password group that is a pure ``{...}``
    # brace expression is an f-string template reference (e.g. f"postgresql://{user}:{pass}@{host}"), not a
    # literal credential — preserve it. Literal passwords are still redacted. The regex forbids whitespace
    # in the password group, so a single-line template's group(2) is exactly the brace expression. See issue
    # #33801.
    if "://" in text:
        text = _redact_url_credentials(text, code_file)

    if "eyJ" in text:
        text = _JWT_RE.sub(lambda m: _mask_token(m.group(0)), text)

    if redact_url_credentials:  # opt-in; known credential shapes in URLs are caught above
        # NOTE: Web-URL redaction (query params + userinfo + HTTP access-log request targets) is
        # intentionally OFF. Many legitimate workflows pass opaque tokens through query strings — magic-link
        # checkouts, OAuth callbacks the agent is meant to follow, pre-signed share URLs — and
        # blanket-redacting param values by name breaks those skills mid-flow. DB connection-string
        # passwords are still caught by _DB_CONNSTR_RE. The ONE userinfo case still redacted is the
        # colon-less bare-token form ``scheme://TOKEN@host`` (#6396, handled by _URL_BARE_TOKEN_RE in the
        # ``://`` block above): a bare credential in userinfo is never a round-trip workflow token (those
        # live in the query string), so masking it can't break a skill. The ``user:pass@`` form is left to
        # pass through per #34029.
        text = _redact_strict_url_credentials(text)

    if "&" in text and "=" in text:
        text = _redact_form_body(text)

    if "+" in text:
        text = _SIGNAL_PHONE_RE.sub(_redact_phone, text)

    return text


def _extract_literal_prefix(pattern: str) -> str:
    """Leading literal chars of a regex (up to the first metacharacter)."""
    meta = "[(\\.?*+|{^$"
    for i, ch in enumerate(pattern):
        if ch in meta:
            return pattern[:i]
    return pattern


_PREFIX_SUBSTRINGS = tuple(_extract_literal_prefix(p) for p in _PREFIX_PATTERNS)


def _has_known_prefix_substring(text: str) -> bool:
    """Cheap pre-check before the expensive ``_PREFIX_RE``."""
    return any(p in text for p in _PREFIX_SUBSTRINGS)
