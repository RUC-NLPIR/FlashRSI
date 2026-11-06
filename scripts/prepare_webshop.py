"""Download and validate the pinned FlashRSI WebShop experiment split metadata."""

import argparse
import json
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from huggingface_hub import hf_hub_download

from flashrsi.benchmarks.webshop import HF_REVISION as _REVISION
from flashrsi.benchmarks.webshop import _check_native, _validate

_REPO = "RUC-NLPIR/FlashRSI"


def prepare(output, native_root=None):
    filenames = ("experiment_split_ids.json", "experiment_selection.json")
    # Keep downloads outside the benchmark output until both files pass validation.
    with TemporaryDirectory(prefix="flashrsi-webshop-hf-") as temporary:
        payload = {
            name: Path(
                hf_hub_download(
                    repo_id=_REPO,
                    repo_type="dataset",
                    revision=_REVISION,
                    filename=f"webshop/{name}",
                    cache_dir=temporary,
                    token=False,
                )
            ).read_bytes()
            for name in filenames
        }
    splits = _validate(payload[filenames[0]], payload[filenames[1]])
    if native_root is not None:
        _check_native(native_root, json.loads(payload[filenames[1]]))
    output.mkdir(parents=True, exist_ok=True)
    for name, content in payload.items():
        (output / name).write_bytes(content)
    return {
        "source": _REPO,
        "revision": _REVISION,
        "output": str(output.resolve()),
        "counts": {role: len(ids) for role, ids in splits.items()},
        "status": "task_ids_only",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".cache/webshop/prepared"))
    parser.add_argument(
        "--native-root",
        type=Path,
        help="Also check the pinned upstream checkout and full local resource layout",
    )
    args = parser.parse_args()
    try:
        summary = prepare(args.output, args.native_root)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        parser.error(str(exc))
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
