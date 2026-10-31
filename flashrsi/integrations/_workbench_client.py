"""Call a native WorkBench tool through a task-local authenticated bridge."""

import argparse
import json
from urllib.request import ProxyHandler, Request, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bridge", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("name")
    parser.add_argument("arguments", help="JSON object of string keyword arguments")
    args = parser.parse_args()
    request = Request(
        args.bridge,
        json.dumps(
            {"name": args.name, "arguments": json.loads(args.arguments)}
        ).encode(),
        {"Content-Type": "application/json", "Authorization": "Bearer " + args.token},
    )
    with build_opener(ProxyHandler({})).open(request, timeout=120) as response:
        result = json.load(response)
    print(json.dumps(result, ensure_ascii=False))
    return int("error" in result)


if __name__ == "__main__":
    raise SystemExit(main())
