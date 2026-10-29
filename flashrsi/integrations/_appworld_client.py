"""Dependency-free AppWorld tool bridge, usable from a native shell tool."""

import argparse
import json
import sys
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


def call(url, operation, *, code=None, app=None, api=None, timeout=100):
    payload = {"operation": operation}
    if code is not None:
        payload["code"] = code
    if app is not None:
        payload["app"] = app
    if api is not None:
        payload["api"] = api
    request = Request(
        url, json.dumps(payload).encode(), {"Content-Type": "application/json"}
    )
    # Container-local calls must not be sent to an inherited HTTP proxy.
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("execute", "docs", "metadata", "wait"))
    parser.add_argument("app", nargs="?")
    parser.add_argument("api", nargs="?")
    parser.add_argument("--url", default="http://appworld:8000")
    parser.add_argument("--timeout", type=float, default=100)
    args = parser.parse_args()
    if args.operation == "wait":
        deadline = time.monotonic() + args.timeout
        while True:
            try:
                value = call(args.url, "metadata", timeout=min(2, args.timeout))
                break
            except (URLError, TimeoutError):
                if time.monotonic() >= deadline:
                    raise TimeoutError("AppWorld bridge did not become ready") from None
                time.sleep(0.2)
    else:
        value = call(
            args.url,
            args.operation,
            code=sys.stdin.read() if args.operation == "execute" else None,
            app=args.app,
            api=args.api,
            timeout=args.timeout,
        )
    print(json.dumps(value, ensure_ascii=False))
    return int("error" in value)


if __name__ == "__main__":
    raise SystemExit(main())
