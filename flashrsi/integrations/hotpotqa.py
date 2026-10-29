"""Connect native harness shell tools to a user-configured Wikipedia search API."""

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
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from flashrsi._records import _redact, _secrets


def _search(config, query, top_k):
    headers = {"Content-Type": "application/json", **config.get("headers", {})}
    if config.get("api_key"):
        headers["Authorization"] = "Bearer " + config["api_key"]
    request = Request(
        config["url"], json.dumps({"query": query, "top_k": top_k}).encode(), headers
    )
    with urlopen(request, timeout=config["timeout"]) as response:
        value = json.load(response)
    results = value["results"]
    if not isinstance(results, list):
        raise ValueError("Search response requires a results list")
    public = []
    for item in results:
        title, sentences, ids = item["title"], item["sentences"], item["sentence_ids"]
        if (
            not isinstance(title, str)
            or not title.strip()
            or not isinstance(sentences, list)
            or not isinstance(ids, list)
            or len(sentences) != len(ids)
            or len(set(ids)) != len(ids)
            or any(not isinstance(text, str) for text in sentences)
            or any(type(index) is not int or index < 0 for index in ids)
        ):
            raise ValueError(
                "Search results need titles, sentences and original sentence_ids"
            )
        # No backend-specific fields, oracle hints or credentials enter the trace.
        public.append({"title": title, "sentences": sentences, "sentence_ids": ids})
    return {"results": public}


def _serve(config, token):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                if self.headers.get("Authorization") != "Bearer " + token:
                    raise ValueError("Invalid bridge credential")
                size = int(self.headers.get("Content-Length", 0))
                if not 0 < size <= 1024 * 1024:
                    raise ValueError("Invalid search request size")
                value = json.loads(self.rfile.read(size))
                query = value["query"]
                count = value.get("top_k")
                count = config["top_k"] if count is None else count
                if (
                    not isinstance(query, str)
                    or not query.strip()
                    or type(count) is not int
                    or not 1 <= count <= 100
                ):
                    raise ValueError(
                        "Search requires query and top_k between 1 and 100"
                    )
                result = _search(config, query, count)
            except Exception as exc:
                result = {"error": f"Search failed ({type(exc).__name__})"}
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def bind(agent, benchmark):
    if (
        agent.name == "miniagent"
        and os.name != "posix"
        and not agent.config.get("source_dir")
    ):
        raise ValueError(
            "HotpotQA fullwiki with MiniAgent's bundled shell requires POSIX; use Claude Code or a compatible custom source_dir"
        )
    if (
        agent.name == "claude_code"
        and agent.config.get("permission_mode") != "bypassPermissions"
        and not any(
            tool == "Bash" or tool.startswith("Bash(")
            for tool in agent.config.get("allowed_tools", ["Read", "Glob", "Grep"])
        )
    ):
        raise ValueError(
            "HotpotQA fullwiki requires Claude Code allowed_tools to include Bash"
        )
    config = copy.deepcopy(dict(benchmark.config.get("retrieval", {})))
    parsed = urlparse(config.get("url", ""))
    if (
        parsed.scheme not in ("http", "https")
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "HotpotQA fullwiki requires retrieval.url; credentials belong in api_key/headers"
        )
    if (
        not isinstance(config.get("corpus_version"), str)
        or not config["corpus_version"].strip()
    ):
        raise ValueError("HotpotQA fullwiki requires retrieval.corpus_version")
    timeout = config.setdefault("timeout", 30)
    if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("retrieval.timeout must be positive and finite")
    count = config.setdefault("top_k", 10)
    if type(count) is not int or not 1 <= count <= 100:
        raise ValueError("retrieval.top_k must be between 1 and 100")
    secrets = sorted(set(_secrets(config)), key=len, reverse=True)

    async def run(target, task):
        if benchmark._tasks_by_id.get(task.task_id) != task:
            raise ValueError("HotpotQA requires a loaded benchmark Task")
        # URL-safe random tokens can start with '-', which argparse treats as an option.
        token = "hotpot_" + token_urlsafe(32)
        server = _serve(config, token)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with TemporaryDirectory(prefix="flashrsi-hotpotqa-") as temporary:
                root = Path(temporary)
                client = root / "search.py"
                shutil.copyfile(Path(__file__).with_name("_hotpot_client.py"), client)
                command = [
                    Path(sys.executable).as_posix(),
                    "-X",
                    "utf8",
                    client.as_posix(),
                    "--url",
                    f"http://127.0.0.1:{server.server_port}",
                    "--token",
                    token,
                    "--timeout",
                    str(timeout + 5),
                ]
                # Both native tools use Bash/POSIX syntax, including Git Bash on Windows.
                command = shlex.join(command)
                prompt = (
                    task.question
                    + f'\n\nSearch tool: run {command} "your query" [--top-k N] using your shell tool. Results preserve article titles and original sentence_ids. No reference answer or supporting facts are available through this tool.'
                )
                result = await target.run(prompt, working_dir=root)
                return replace(
                    result,
                    output=_redact(result.output, secrets),
                    messages=_redact(result.messages, secrets),
                    usage=_redact(result.usage, secrets),
                    error_message=_redact(result.error_message, secrets),
                )
        finally:
            await asyncio.to_thread(server.shutdown)
            server.server_close()
            thread.join(timeout=2)

    agent._env_runner = run
