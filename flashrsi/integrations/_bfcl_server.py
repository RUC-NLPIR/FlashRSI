"""Private native BFCL environment with an allowlisted public JSON bridge."""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from importlib.metadata import version
from pathlib import Path

from ._bfcl_session import Conversation


def serve(conversation, evidence_path, address):
    def save():
        temporary = evidence_path.with_suffix(".tmp")
        payload = json.dumps(conversation.evidence())
        if len(payload.encode()) > 8 * 1024 * 1024:
            conversation.interrupted = "trace_limit"
            payload = json.dumps(
                {
                    "complete": False,
                    "protocol_valid": False,
                    "interrupted": "trace_limit",
                    "trace": [],
                }
            )
        temporary.write_text(payload, encoding="utf-8")
        temporary.replace(evidence_path)

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.connection.settimeout(5)
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 1024 * 1024:
                    raise ValueError("Invalid request size")
                request = json.loads(self.rfile.read(size))
                if not isinstance(request, dict):
                    raise ValueError("Expected object")
                result = conversation.respond(request)
            except (ValueError, TypeError, KeyError, SyntaxError, PermissionError):
                conversation.rejected = True
                result = {"error": "BFCL request rejected"}
            except Exception:
                conversation.interrupted = "environment_failure"
                result = {"error": "BFCL environment failed"}
            save()
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    save()
    return HTTPServer(address, Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("/world"))
    args = parser.parse_args()
    if version("mpmath") != "1.3.0":
        raise ValueError("BFCL native execution requires mpmath==1.3.0")
    request = json.loads((args.root / "request.json").read_text(encoding="utf-8"))
    conversation = Conversation(
        args.root / "native", request["row"], request["max_calls_per_turn"]
    )
    try:
        with serve(conversation, args.root / "trace.json", ("0.0.0.0", 8000)) as server:
            server.serve_forever()
    finally:
        conversation.close()


if __name__ == "__main__":
    main()
