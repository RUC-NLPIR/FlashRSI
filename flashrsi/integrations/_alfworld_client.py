"""Submit one text action to the task-local ALFWorld environment."""

import argparse
import json
from urllib.request import ProxyHandler, Request, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("action")
    args = parser.parse_args()
    request = Request(
        args.bridge,
        json.dumps({"action": args.action}).encode(),
        {"Content-Type": "application/json", "Authorization": "Bearer " + args.token},
    )
    with build_opener(ProxyHandler({})).open(request, timeout=120) as response:
        result = json.load(response)
    print(json.dumps(result, ensure_ascii=False))
    return int("error" in result)


if __name__ == "__main__":
    raise SystemExit(main())
