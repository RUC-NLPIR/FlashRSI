"""Task-local CLI; only an ephemeral bridge token reaches the harness."""

import argparse
import json
from urllib.request import ProxyHandler, Request, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--timeout", type=float, default=60)
    commands = parser.add_subparsers(dest="action", required=True)
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--top-k", type=int)
    read = commands.add_parser("read")
    read.add_argument("url")
    args = parser.parse_args()
    value = {"action": args.action}
    value.update(
        {"query": args.query, "top_k": args.top_k}
        if args.action == "search"
        else {"url": args.url}
    )
    request = Request(
        args.bridge,
        json.dumps(value).encode(),
        {"Content-Type": "application/json", "Authorization": "Bearer " + args.token},
    )
    with build_opener(ProxyHandler({})).open(request, timeout=args.timeout) as response:
        result = json.load(response)
    print(json.dumps(result, ensure_ascii=False))
    return int("error" in result)


if __name__ == "__main__":
    raise SystemExit(main())
