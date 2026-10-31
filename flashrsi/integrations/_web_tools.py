"""Task-local search/read bridge shared by web research benchmarks."""

import asyncio
import copy
import json
import math
import os
import shlex
import shutil
import sys
import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from secrets import token_urlsafe
from tempfile import TemporaryDirectory

from flashrsi._records import _redact, _secrets
from flashrsi.integrations import _browsecomp_web


def _serve(config, token, records, event_type="BrowseCompWeb"):
    secrets = _secrets(config) + [token]

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            value = {}
            try:
                if (
                    self.path != "/"
                    or self.headers.get("Authorization") != "Bearer " + token
                ):
                    self.send_error(403)
                    return
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 65536:
                    raise ValueError("Invalid tool request size")
                value = json.loads(self.rfile.read(size))
                action = value["action"]
                if action == "search":
                    query = value["query"]
                    top_k = value.get("top_k")
                    top_k = config["top_k"] if top_k is None else top_k
                    if (
                        not isinstance(query, str)
                        or not query.strip()
                        or type(top_k) is not int
                        or not 1 <= top_k <= 20
                    ):
                        raise ValueError("Search requires a query and top_k in 1..20")
                    result = _browsecomp_web.search(config, query, top_k)
                elif action == "read":
                    result = _browsecomp_web.read(config, value["url"])
                else:
                    raise ValueError("Unknown web tool")
            except Exception as exc:
                # Provider errors may contain credentials or raw service payloads.
                result = {"error": f"Web tool failed ({type(exc).__name__})"}
            result = _redact(result, secrets)
            records.append(
                {
                    "type": event_type,
                    "request": _redact(value, secrets),
                    "response": result,
                }
            )
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def settings(agent, config, label):
    if (
        agent.name == "miniagent"
        and os.name != "posix"
        and not agent.config.get("source_dir")
    ):
        raise ValueError(
            f"{label} with MiniAgent's bundled shell requires POSIX; use Claude Code or a compatible custom source_dir"
        )
    if (
        agent.name == "claude_code"
        and agent.config.get("permission_mode") != "bypassPermissions"
        and not any(
            tool == "Bash" or tool.startswith("Bash(")
            for tool in agent.config.get("allowed_tools", ["Read", "Glob", "Grep"])
        )
    ):
        raise ValueError(f"{label} requires Claude Code allowed_tools to include Bash")
    retrieval = copy.deepcopy(dict(config.get("retrieval", {})))
    provider = retrieval.setdefault("provider", "tavily")
    if provider not in ("tavily", "serper", "json"):
        raise ValueError("retrieval.provider must be tavily, serper or json")
    if provider in ("tavily", "serper"):
        retrieval.setdefault(
            "url",
            "https://api.tavily.com/search"
            if provider == "tavily"
            else "https://google.serper.dev/search",
        )
        if not retrieval.get("api_key"):
            raise ValueError(f"{provider.title()} requires benchmark.retrieval.api_key")
    reader = retrieval.setdefault("reader", {})
    if reader.setdefault("provider", "direct") not in ("direct", "jina"):
        raise ValueError("retrieval.reader.provider must be direct or jina")
    if reader["provider"] == "jina":
        reader.setdefault("url", "https://r.jina.ai/")
        _browsecomp_web._http_url(reader["url"])
        if not reader.get("api_key"):
            raise ValueError("Jina requires benchmark.retrieval.reader.api_key")
    _browsecomp_web._http_url(retrieval.get("url", ""))
    retrieval.setdefault("timeout", 30)
    retrieval.setdefault("top_k", 5)
    retrieval.setdefault("max_page_chars", 20000)
    retrieval.setdefault("search_depth", "basic")
    if retrieval["search_depth"] not in ("basic", "advanced"):
        raise ValueError("retrieval.search_depth must be basic or advanced")
    if type(retrieval["top_k"]) is not int or not 1 <= retrieval["top_k"] <= 20:
        raise ValueError("retrieval.top_k must be in 1..20")
    if type(retrieval["max_page_chars"]) is not int or retrieval["max_page_chars"] < 1:
        raise ValueError("retrieval.max_page_chars must be a positive integer")
    timeout = retrieval["timeout"]
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Web retrieval timeout must be positive and finite")
    return retrieval


async def run(target, task, retrieval, label):
    token = label.lower() + "_" + token_urlsafe(32)
    records = []
    server = _serve(retrieval, token, records, label + "Web")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with TemporaryDirectory(prefix="flashrsi-" + label.lower() + "-") as temporary:
            root = Path(temporary)
            client = root / "web.py"
            shutil.copyfile(Path(__file__).with_name("_browsecomp_client.py"), client)
            command = shlex.join(
                [
                    Path(sys.executable).as_posix(),
                    "-X",
                    "utf8",
                    client.as_posix(),
                    "--bridge",
                    f"http://127.0.0.1:{server.server_port}/",
                    "--token",
                    token,
                    "--timeout",
                    str(retrieval["timeout"] + 5),
                ]
            )
            prompt = (
                task.question
                + f'\n\nWeb tools (invoke using your shell tool):\nSearch: {command} search "your query" [--top-k N]\nRead page: {command} read "https://example.org/page"\nSearch returns titles, URLs and snippets. '
                + (
                    "Reading uses Jina Reader to return public page content."
                    if retrieval["reader"]["provider"] == "jina"
                    else "Reading supports public HTML/text pages; JavaScript and PDF rendering are not provided."
                )
            )
            result = await target.run(prompt, working_dir=root)
    finally:
        await asyncio.to_thread(server.shutdown)
        server.server_close()
        thread.join(timeout=2)
    return replace(
        result,
        output=_redact(result.output, [token]),
        messages=_redact(
            tuple(
                m
                for m in result.messages
                if m.get("type") not in (label + "Verifier", label + "Web")
            )
            + tuple(records),
            [token],
        ),
        usage=_redact(result.usage, [token]),
        error_message=_redact(result.error_message, [token]),
    )
