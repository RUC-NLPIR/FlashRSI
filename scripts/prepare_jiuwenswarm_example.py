"""Create a fresh native source seed with the example QA skill; no model calls."""

import argparse
import shutil
from pathlib import Path

from flashrsi.agents import JiuwenSwarm


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output", type=Path, default=Path(".cache/jiuwenswarm/example-source-core")
    )
    args = parser.parse_args()
    destination = args.output.resolve()
    # Never replace an existing experiment's seed or edited files.
    destination.mkdir(parents=True, exist_ok=False)
    source = Path(__file__).resolve().parents[1]
    native = source / "flashrsi/agents/jiuwenswarm"
    snapshot = JiuwenSwarm().snapshot
    for name, entry in snapshot.files.items():
        path = destination / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(entry.content)
        if entry.executable:
            path.chmod(path.stat().st_mode | 0o111)
    shutil.copyfile(native / "components.yaml", destination / "components.yaml")
    shutil.copyfile(native / "upstream.json", destination / "upstream.json")
    shutil.copytree(source / "examples/jiuwenswarm/skills", destination / "skills")
    print(f"Prepared JiuwenSwarm example source: {destination}")
    print("No tasks or model calls were run.")


if __name__ == "__main__":
    main()
