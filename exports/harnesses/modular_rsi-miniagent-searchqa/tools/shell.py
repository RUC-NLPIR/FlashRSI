"""A bounded shell call in the native MiniAgent's task environment."""

import asyncio
import json
import math
import os
import re
import shlex
import signal
from pathlib import Path

_OUTPUT_LIMIT = 32 * 1024

# ---------------------------------------------------------------------------
# Pre-execution network guard
# ---------------------------------------------------------------------------
# The shell tool is intended for filesystem work. Outbound network retrieval
# repeatedly wastes turns in this environment because network access is
# disabled, so we recognize those commands and return an explanatory tool
# result before spawning anything.

_NETWORK_EXECUTABLES = {
    "curl",
    "wget",
    "wget2",
    "aria2c",
    "axel",
    "http",
    "https",
    "fetch",
    "lynx",
    "w3m",
    "elinks",
    "links",
    "links2",
}

_SHELL_INTERPRETERS = {"sh", "bash", "zsh", "dash", "ksh", "ash"}
_SCRIPT_INTERPRETERS = {"node", "nodejs", "php", "perl", "ruby"}

_WRAPPER_WORDS = {
    "env",
    "command",
    "sudo",
    "doas",
    "nohup",
    "nice",
    "ionice",
    "stdbuf",
    "chroot",
    "time",
    "xargs",
    "watch",
    "busybox",
}

# Options for wrappers where the option consumes the following token as a
# value. This keeps command-word detection from mistaking an option value for
# the command that follows the wrapper.
_WRAPPER_OPTION_VALUES = {
    "env": {"-u", "--unset", "-C", "--chdir", "-S", "--split-string"},
    "sudo": {
        "-u", "--user",
        "-g", "--group",
        "-h", "--host",
        "-p", "--prompt",
        "-U", "--other-user",
        "-T", "--command-timeout",
        "-r", "--role",
        "-t", "--type",
        "-C", "--chdir",
        "-D", "--chdir",
    },
    "chroot": {"--userspec", "--groups"},
    "stdbuf": {"-i", "--input", "-o", "--output", "-e", "--error"},
    "nice": {"-n", "--adjustment"},
    "ionice": {"-n", "--classdata", "-c", "--class", "-t", "--timeout"},
    "time": {"-o", "--output", "-f", "--format", "-a", "--append"},
    "xargs": {
        "-I", "--replace",
        "-n", "--max-args",
        "-s", "--max-chars",
        "-P", "--max-procs",
        "-a", "--arg-file",
        "-E", "--eof",
        "-L", "--max-lines",
        "-d", "--delimiter",
    },
    "watch": {
        "-n", "--interval",
        "-t", "--no-title",
        "-b", "--beep",
        "-d", "--differences",
        "-g", "--chgexit",
        "-x", "--exec",
        "-e", "--errexit",
        "-p", "--precise",
    },
}

_PYTHON_NETWORK_RE = re.compile(
    r"\b(?:urllib\.(?:request|urlopen)|urllib2|urlopen|requests|httpx|http\.client)\b",
    re.IGNORECASE,
)
_HTTP_FETCH_RE = re.compile(
    r"\b(?:"
    r"fetch\s*\(|http\.get\s*\(|https\.get\s*\(|axios|XMLHttpRequest"
    r"|file_get_contents\s*\(|curl_init\s*\(|fsockopen\s*\(|stream_context_create\s*\(|"
    r"LWP::Simple|HTTP::Tiny|WWW::Mechanize|Net::HTTP|open-uri"
    r")",
    re.IGNORECASE,
)
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_CONTROL_TOKENS = {"|", "||", "&&", ";", "&", "(", ")", "\n", "$"}


def _shell_tokens(command):
    """Tokenize a shell command for inspection. Returns None on lex errors."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        lexer.commenters = ""
        return list(lexer)
    except ValueError:
        return None


def _basename(word):
    return word.rsplit("/", 1)[-1]


def _skip_wrapper_options(segment, index, wrapper):
    value_opts = _WRAPPER_OPTION_VALUES.get(wrapper, set())
    while index < len(segment):
        token = segment[index]
        if _ASSIGN_RE.match(token):
            index += 1
            continue
        if token.startswith("-"):
            if token in value_opts:
                index += 2
            else:
                index += 1
            continue
        break
    return index


def _command_word(segment):
    """Return the first real command word in a pipeline segment."""
    index = 0
    while index < len(segment) and _ASSIGN_RE.match(segment[index]):
        index += 1
    while index < len(segment):
        word = segment[index]
        if word not in _WRAPPER_WORDS:
            return word
        wrapper = word
        index += 1
        index = _skip_wrapper_options(segment, index, wrapper)
        while index < len(segment) and _ASSIGN_RE.match(segment[index]):
            index += 1
    return None


def _is_python(word):
    return re.fullmatch(r"python(?:\d+(?:\.\d+)*)?", word) is not None


def _short_flag_has(token, flag):
    return (
        token.startswith("-")
        and not token.startswith("--")
        and len(token) > 1
        and flag in token[1:]
    )


def _code_requests_network(code):
    return bool(_PYTHON_NETWORK_RE.search(code) or _HTTP_FETCH_RE.search(code))


def _extract_code(segment, flags, short_flag):
    """Return the code argument following a `-c`/`-e`/`-r` style flag."""
    for index, token in enumerate(segment[:-1]):
        if token in flags or _short_flag_has(token, short_flag):
            return segment[index + 1]
    return None


def _segment_requests_network(segment):
    word = _command_word(segment)
    if not word:
        return False
    base = _basename(word).lower()

    if base in _NETWORK_EXECUTABLES:
        return True

    if _is_python(base):
        return any(_code_requests_network(token) for token in segment)

    if base in _SHELL_INTERPRETERS:
        code = _extract_code(segment, {"-c", "--command"}, "c")
        return code is not None and _looks_like_outbound_network(code)

    if base in _SCRIPT_INTERPRETERS:
        code = _extract_code(segment, {"-e", "--eval", "-r", "--run"}, "e")
        return code is not None and _code_requests_network(code)

    return False


def _tokens_contain_network_request(tokens):
    segment = []
    for token in tokens:
        if token in _CONTROL_TOKENS:
            if segment and _segment_requests_network(segment):
                return True
            segment = []
        else:
            segment.append(token)
    return bool(segment) and _segment_requests_network(segment)


def _looks_like_outbound_network(command):
    """Return True when a shell command appears to perform outbound network I/O."""
    tokens = _shell_tokens(command)
    if tokens is not None:
        return _tokens_contain_network_request(tokens)

    # Lexing fails only for malformed shell input (for example an unbalanced
    # quote). It would not execute successfully anyway, so a conservative
    # regex check is sufficient here and avoids letting a malformed network
    # command through.
    return bool(
        _PYTHON_NETWORK_RE.search(command)
        or _HTTP_FETCH_RE.search(command)
        or re.search(
            r"(?<![A-Za-z0-9_./-])(?:curl|wget|wget2|aria2c|axel)\b",
            command,
        )
    )


def _blocked_network_result():
    return json.dumps(
        {
            "exit_code": 1,
            "output": (
                "Network access is disabled for the shell tool. The requested "
                "command was not executed because it appears to make an outbound "
                "network request (e.g. curl, wget, urllib/urlopen, or an HTTP "
                "fetch). Use the supplied context or local files instead."
            ),
            "timed_out": False,
            "truncated": False,
            "blocked": True,
        },
        ensure_ascii=False,
    )


async def call(args, ctx) -> str:
    command = args.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("command must be a non-empty string")
    timeout = args.get("timeout", 60)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be a positive finite number")
    cwd = args.get("cwd", ".")
    if not isinstance(cwd, str) or not cwd:
        raise ValueError("cwd must be a non-empty path")
    directory = (ctx.working_dir / Path(cwd)).resolve(strict=True)

    if _looks_like_outbound_network(command):
        return _blocked_network_result()

    loop = asyncio.get_running_loop()
    read_fd, write_fd = os.pipe()
    os.set_blocking(read_fd, False)
    output = bytearray()
    truncated = False

    def read_available():
        nonlocal truncated
        # One bounded read per callback lets deadlines run even for commands
        # producing output continuously. Discard overflow without buffering it.
        try:
            chunk = os.read(read_fd, 64 * 1024)
        except BlockingIOError:
            return
        if not chunk:
            loop.remove_reader(read_fd)
            return
        remaining = _OUTPUT_LIMIT - len(output)
        output.extend(chunk[:remaining])
        truncated |= len(chunk) > remaining

    process = None
    spawning = None
    completed = False
    timed_out = False
    try:
        loop.add_reader(read_fd, read_available)
        # Own the pipe separately: Process.wait() must observe the shell's exit,
        # not wait for EOF from a background service that inherited stdout.
        spawning = asyncio.create_task(
            asyncio.create_subprocess_exec(
                "/bin/sh",
                "-c",
                command,
                cwd=directory,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=write_fd,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
        )
        # Cancellation may arrive after the OS process exists but before its
        # handle is returned. Retain acquisition so finally can stop its group.
        process = await asyncio.shield(spawning)
        os.close(write_fd)
        write_fd = None
        await asyncio.wait_for(process.wait(), timeout=timeout)
        completed = True
    except TimeoutError:
        timed_out = True
    finally:
        try:
            if process is None and spawning is not None:
                process = await spawning
            if process is not None:
                # Successful commands may leave task services running. Their
                # lifetime belongs to the caller or the surrounding environment.
                if not completed:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                await process.wait()
        finally:
            loop.remove_reader(read_fd)
            # Capture any final pending bytes, then close our pipe even if a
            # detached child still holds stdout. No EOF wait or transport leaks.
            read_available()
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)

    return json.dumps(
        {
            "exit_code": process.returncode,
            "output": output.decode("utf-8", errors="replace"),
            "timed_out": timed_out,
            "truncated": truncated,
        },
        ensure_ascii=False,
    )
