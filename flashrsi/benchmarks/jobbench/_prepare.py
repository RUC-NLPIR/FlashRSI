"""Invoke upstream preparation in a process so its imports stay outside FlashRSI."""

import json
import sys
from pathlib import Path


def main():
    upstream, repo_id, revision, local = sys.argv[1:]
    root = Path(upstream) / "harbor"
    sys.path.insert(0, str(root))
    from jobbench_harbor.hf_source import fetch_snapshot
    from jobbench_harbor.prepare import generate

    if local:
        snapshot, files = Path(local), None
        repo_id, revision = "local", "local"
    else:
        source = fetch_snapshot(
            root / ".cache/huggingface", repo_id=repo_id, revision=revision
        )
        snapshot, files = source.path, source.remote_files
    manifest = generate(
        snapshot,
        root,
        repo_id=repo_id,
        revision=revision,
        judge_path=root.parent / "eval/judge.py",
        remote_files=files,
    )
    print(
        json.dumps(
            {
                "tasks_path": str(
                    root / ".generated" / manifest["fingerprint"] / "tasks"
                ),
                "fingerprint": manifest["fingerprint"],
            }
        )
    )


if __name__ == "__main__":
    main()
