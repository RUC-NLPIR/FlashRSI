"""Native-shell JSON client for the currently active BFCL user turn."""

import argparse
import json
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


def call(url, payload, timeout=100):
    request = Request(
        url, json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation", choices=("current", "tools", "call", "finish_turn", "wait")
    )
    parser.add_argument("name", nargs="?")
    parser.add_argument("--url", default="http://bfcl:8000")
    parser.add_argument("--timeout", type=float, default=100)
    args = parser.parse_args()
    if args.operation == "wait":
        deadline = time.monotonic() + args.timeout
        while True:
            try:
                result = call(args.url, {"operation": "current"}, min(args.timeout, 2))
                break
            except (URLError, TimeoutError):
                if time.monotonic() >= deadline:
                    raise TimeoutError("BFCL bridge did not become ready") from None
                time.sleep(0.2)
    else:
        payload = {"operation": args.operation}
        if args.operation == "tools" and args.name is not None:
            payload["name"] = args.name
        if args.operation == "call":
            payload["calls"] = json.loads(sys.stdin.read())
        result = call(args.url, payload, args.timeout)
    print(json.dumps(result, ensure_ascii=False))
    return int("error" in result or bool(result.get("interrupted")))


if __name__ == "__main__":
    raise SystemExit(main())
