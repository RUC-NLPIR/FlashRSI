import json
import sys

def decide(event):
    return {}

if __name__ == "__main__":
    print(json.dumps(decide(json.load(sys.stdin))))
