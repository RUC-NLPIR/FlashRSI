"""Dependency-free CLI for the task-local HotpotQA search bridge."""

import argparse
import json
from urllib.request import ProxyHandler, Request, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--url", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    request = Request(
        args.url,
        json.dumps({"query": args.query, "top_k": args.top_k}).encode(),
        {"Content-Type": "application/json", "Authorization": "Bearer " + args.token},
    )
    with build_opener(ProxyHandler({})).open(request, timeout=args.timeout) as response:
        result = json.load(response)
    print(json.dumps(result, ensure_ascii=False))
    return int("error" in result)


if __name__ == "__main__":
    raise SystemExit(main())
