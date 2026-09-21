"""Build the FlashRSI HotpotQA dataset from the pinned upstream fullwiki split.

Run from FlashRSI-Lite with:
    uv run python scripts/prepare_hotpotqa.py

Only reads public upstream data and writes local files; never uploads or logs in.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from huggingface_hub import hf_hub_download

SOURCE = "hotpotqa/hotpot_qa"
CONFIG = "fullwiki"
REVISION = "1908d6afbbead072334abe2965f91bd2709910ab"
# The public fullwiki test split carries no answer labels, so it is never read.
SOURCES = {
    "train": (
        (
            "fullwiki/train-00000-of-00002.parquet",
            "76d3bb3048a7cc73c1958107c0c5872a00d7e7d00c105b81e92f6769e7822e68",
        ),
        (
            "fullwiki/train-00001-of-00002.parquet",
            "713661628434fbb19fff7392e2e321e4ed107e3c7c7784d0690946e5f722763f",
        ),
    ),
    "validation": (
        (
            "fullwiki/validation-00000-of-00001.parquet",
            "78933c0a31a5f7b420d4effdf4cd4eed573b28c6a3da6179dcf7a02b39e51d03",
        ),
    ),
}
SOURCE_COUNTS = {"train": 90447, "validation": 7405}
# Reserve the labeled official validation split as the final test partition and
# derive a tuning split from official train, as flashrsi-hotpotqa-heldout-v1.
SPLIT_POLICY = "flashrsi-hotpotqa-heldout-v1"
DEV_FRACTION = 10
SPLIT_SEED = 0


def _order(task_ids: list[str], seed: int) -> list[int]:
    """Rank rows by the same seeded digest the benchmark loader sorts with."""
    keys = [
        (hashlib.sha256(f"{seed}:{task_id}".encode()).digest(), task_id, index)
        for index, task_id in enumerate(task_ids)
    ]
    keys.sort()
    return [index for _, _, index in keys]


def prepare(output: Path, source_dir: Path | None = None) -> dict:
    """Publish train/dev/test as Zstandard Parquet, preserving every field."""

    def read_source(name: str) -> Path:
        if source_dir is not None:
            return source_dir / Path(name).name
        return Path(
            hf_hub_download(
                SOURCE, name, repo_type="dataset", revision=REVISION, token=False
            )
        )

    pools = {}
    sources = {}
    for pool, names in SOURCES.items():
        tables = []
        for name, expected in names:
            path = read_source(name)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if digest != expected:
                raise ValueError(f"source checksum mismatch: {name}")
            tables.append(pq.read_table(path))
            sources.setdefault(pool, {})[name] = digest
        if any(
            not table.schema.equals(tables[0].schema, check_metadata=True)
            for table in tables
        ):
            raise ValueError(f"source shards disagree on schema: {pool}")
        pools[pool] = pa.concat_tables(tables)
        if pools[pool].num_rows != SOURCE_COUNTS[pool]:
            raise ValueError(f"unexpected source row count: {pool}")

    schema = pools["train"].schema
    if not pools["validation"].schema.equals(schema, check_metadata=True):
        raise ValueError("official train and validation disagree on schema")

    # Official labeled validation becomes the final test partition; the tuning
    # split is carved out of official train so test stays untouched.
    order = _order(pools["train"].column("id").to_pylist(), SPLIT_SEED)
    dev_count = len(order) // DEV_FRACTION
    splits = {
        "train": pools["train"].take(sorted(order[dev_count:])),
        "dev": pools["train"].take(sorted(order[:dev_count])),
        "test": pools["validation"],
    }
    origins = {
        "train": ("official train, minus the derived dev holdout", "train"),
        "dev": (f"official train, seeded 1/{DEV_FRACTION} holdout", "train"),
        "test": ("official labeled validation, held out in full", "validation"),
    }

    destination = output / "hotpotqa"
    destination.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "flashrsi.hotpotqa.v1",
        "source": {"repo": SOURCE, "config": CONFIG, "revision": REVISION},
        "split_policy": SPLIT_POLICY,
        "split_seed": SPLIT_SEED,
        "notes": {
            "test": (
                "The official fullwiki test split has no answer labels, so the "
                "labeled official validation split is reserved as the final test "
                "partition instead."
            ),
            "dev": (
                f"The tuning split is 1/{DEV_FRACTION} of official train, ordered "
                f"by sha256('{SPLIT_SEED}:' + id) so the partition is reproducible "
                "and disjoint from train. Row order within each split follows the "
                "official files."
            ),
        },
        "splits": {},
    }
    seen: set[str] = set()
    for split, table in splits.items():
        path = destination / f"{split}.parquet"
        with pq.ParquetWriter(path, schema, compression="zstd") as writer:
            for batch in table.to_batches():
                writer.write_batch(batch)

        written = pq.read_table(path)
        if not written.schema.equals(schema, check_metadata=True) or not written.equals(
            table
        ):
            raise ValueError(f"Parquet round-trip mismatch: {split}")
        for task_id, answer in zip(
            written.column("id").to_pylist(),
            written.column("answer").to_pylist(),
            strict=True,
        ):
            if not isinstance(task_id, str) or not task_id.strip() or task_id in seen:
                raise ValueError(f"invalid or duplicate source task id: {split}")
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError(f"row has no answer label: {task_id}")
            seen.add(task_id)

        origin, pool = origins[split]
        manifest["splits"][split] = {
            "count": written.num_rows,
            "file": f"hotpotqa/{path.name}",
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "origin": origin,
            "source_sha256": sources[pool],
        }
    if seen != set(
        pools["train"].column("id").to_pylist()
        + pools["validation"].column("id").to_pylist()
    ):
        raise ValueError("published splits do not cover the official rows exactly")

    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    card = (
        Path(__file__).with_name("hotpotqa_dataset_card.md").read_text(encoding="utf-8")
    )
    (destination / "README.md").write_text(card, encoding="utf-8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".cache/hotpotqa/publish"))
    parser.add_argument(
        "--source-dir", type=Path, help="Optional directory of the pinned source shards"
    )
    args = parser.parse_args()
    manifest = prepare(args.output, args.source_dir)
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "counts": {
                    split: value["count"] for split, value in manifest["splits"].items()
                },
            }
        )
    )
