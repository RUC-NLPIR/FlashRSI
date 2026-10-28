"""Single-task AppWorld bridge. No ground truth, grading or lifecycle RPC."""

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.metadata import version

APPWORLD_VERSION = "0.1.3.post1"


def dispatch(world, request):
    operation = request.get("operation")
    if operation == "metadata":
        return {
            "apps": world.task.app_descriptions,
            "appworld_version": APPWORLD_VERSION,
        }
    if operation == "docs":
        docs = world.task.api_docs
        if request.get("app") is not None:
            docs = docs[request["app"]]
        if request.get("api") is not None:
            if request.get("app") is None:
                raise ValueError("api requires app")
            docs = docs[request["api"]]
        return {"docs": docs}
    if operation == "execute":
        code = request.get("code")
        if not isinstance(code, str) or not code.strip():
            raise ValueError("execute requires non-empty Python code")
        # Native safety guards remain enabled. AppWorld saves its database
        # changes after each execution; no controller object enters user_ns.
        return {"output": world.execute(code), "task_completed": world.task_completed()}
    raise ValueError("Only execute, docs and metadata are available")


def serve(world, address):
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1024 * 1024:
                    raise ValueError("Bridge request must contain at most 1 MiB")
                request = json.loads(self.rfile.read(size))
                if not isinstance(request, dict):
                    raise ValueError("Bridge request must be an object")
                result = dispatch(world, request)
            except Exception as exc:
                result = {"error": str(exc), "error_type": type(exc).__name__}
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    # Native IPython, timeout signals and simulated time all live on this
    # single main thread. A threaded HTTP server would break that contract.
    return HTTPServer(address, Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_id")
    parser.add_argument("--max-interactions", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=100)
    args = parser.parse_args()
    os.environ["APPWORLD_ROOT"] = "/world"
    if version("appworld") != APPWORLD_VERSION:
        raise ValueError(f"AppWorld runtime must be {APPWORLD_VERSION}")
    from appworld import AppWorld

    with AppWorld(
        task_id=args.task_id,
        experiment_name="current",
        load_ground_truth=False,
        max_interactions=args.max_interactions,
        random_seed=args.seed,
        timeout_seconds=args.timeout,
        raise_on_unsafe_syntax=True,
        null_patch_unsafe_execution=True,
    ) as world:
        with serve(world, ("0.0.0.0", 8000)) as server:
            server.serve_forever()


if __name__ == "__main__":
    main()
