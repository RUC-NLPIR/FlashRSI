"""Export AppWorld algorithm records and resource diffs for the local site."""

import argparse
import json
from pathlib import Path

from _artifact_explorer import LABELS, RULES, export_run
from export_searchqa_explorers import write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for key, (label, lens) in LABELS.items():
        agents = {}
        for harness in ["miniagent", "claude_code"]:
            path = args.records / f"{key}-{harness}.json"
            if not path.exists():
                continue
            agent, resources = export_run(
                json.loads(path.read_text(encoding="utf-8")), key, harness, "appworld"
            )
            agents[harness] = agent
            write(args.output / "resources" / f"{key}-{harness}.json", resources)
            print(
                f"{key}/{harness}: {len(agent['evolution']['entries'])} decisions, {len(resources['states'])} versions"
            )
        if agents:
            write(
                args.output / f"{key}.json",
                {
                    "schemaVersion": 2,
                    "key": key,
                    "view": "artifact",
                    "algorithm": label,
                    "benchmark": "AppWorld",
                    "metricLabel": "reward",
                    "lens": lens,
                    "selectionRule": RULES[key],
                    "agents": agents,
                },
            )


if __name__ == "__main__":
    main()
