import json
import sys


def decide(event):
    # Initial identity hook: leave native behavior unchanged.
    return {}


if __name__ == "__main__":
    event = json.load(sys.stdin)
    print(json.dumps(decide(event)))
