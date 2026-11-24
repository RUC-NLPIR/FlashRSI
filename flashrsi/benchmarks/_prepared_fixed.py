"""Load the fixed GISA and SpreadsheetBench V1 packages' SHA256 manifests."""

import hashlib
import json
import re
from pathlib import Path

from huggingface_hub import hf_hub_download

from flashrsi.benchmarks._archive import _is_safe


def prepare(config, download):
    name = config["name"]
    prefix = {"gisa": "gisa", "spreadsheetbench": "spreadsheetbench/1"}[name]
    manifest = json.loads(
        Path(hf_hub_download(filename=prefix + "/manifest.json", **download)).read_text(
            encoding="utf-8"
        )
    )
    expected_source = {
        "gisa": "RUC-NLPIR/GISA",
        "spreadsheetbench": "KAKA22/SpreadsheetBench",
    }[name]
    if manifest.get("upstream", manifest.get("source")) != expected_source:
        raise ValueError("Prepared manifest does not match the requested benchmark")
    hashes = manifest["sha256"]

    def get(relative):
        return resource({**download, "prefix": prefix, "hashes": hashes}, relative)

    splits = json.loads(get("split_ids.json").read_text(encoding="utf-8"))
    counts = (
        {role: sum(groups.values()) for role, groups in manifest["counts"].items()}
        if name == "gisa"
        else {role: group["instructions"] for role, group in manifest["splits"].items()}
    )
    if set(splits) != {"train", "dev", "test"} or set(counts) != set(splits):
        raise ValueError("Prepared split_ids must declare train/dev/test")
    ids = []
    for role, values in splits.items():
        if (
            not isinstance(values, list)
            or len(values) != counts[role]
            or any(not isinstance(value, str) or not value for value in values)
        ):
            raise ValueError("Prepared split membership/count mismatch")
        ids.extend(values)
    if len(ids) != len(set(ids)):
        raise ValueError("Prepared split IDs overlap or contain duplicates")
    config.pop("dataset")
    config["_prepared_splits"] = splits
    config["_prepared_source"] = {
        "source": download["repo_id"],
        "revision": download["revision"],
        "config": name,
        "path": prefix,
        "source_details": manifest,
        "counts": counts,
    }
    config["data_path"] = {role: str(get(role + ".parquet")) for role in splits}
    # Workbooks are downloaded only for roles retained by benchmark.limit.
    config["_prepared_assets"] = {**download, "prefix": prefix, "hashes": hashes}
    return config


def resource(package, relative):
    if not _is_safe(relative):
        raise ValueError("Unsafe prepared resource path")
    expected = package["hashes"].get(relative)
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError("Prepared resource requires a SHA256 digest")
    path = Path(
        hf_hub_download(
            filename=package["prefix"] + "/" + relative,
            **{key: package[key] for key in ("repo_id", "repo_type", "revision")},
        )
    )
    with path.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise ValueError("Prepared resource SHA256 mismatch: " + relative)
    return path
