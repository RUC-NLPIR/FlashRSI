"""Build the FlashRSI SearchQA dataset from the locked EvoOS export.

Run from FlashRSI-Lite with:
    uv run python scripts/prepare_searchqa.py

Only reads public upstream data and writes local files; never uploads or logs in.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pyarrow.parquet as pq
from datasets import Dataset, Features, Sequence, Value
from huggingface_hub import hf_hub_download

SOURCE = "jinjiajie/EvoOS"
REVISION = "2e2d97feb4a3394fd577017024e6d9f3176e9fbc"
PREFIX = (
    "Answer the question using the supplied context. Return only the short answer."
    "\n\nContext:\n"
)
SEPARATOR = "\n\nQuestion:\n"
COUNTS = {"train": 400, "dev": 200, "test": 1400}
FEATURES = Features(
    {
        "id": Value("string"),
        "question": Value("string"),
        "context": Value("string"),
        "answers": Sequence(Value("string")),
    }
)


def prepare(output: Path, source_dir: Path | None = None) -> None:
    def read_source(name: str) -> bytes:
        path = (
            source_dir / name
            if source_dir is not None
            else Path(
                hf_hub_download(
                    SOURCE,
                    f"benchmarks/searchqa/{name}",
                    repo_type="dataset",
                    revision=REVISION,
                    token=False,
                )
            )
        )
        return path.read_bytes()

    upstream = json.loads(read_source("manifest.json"))
    manifest = {
        "schema": "flashrsi.searchqa.v1",
        "source": SOURCE,
        "source_revision": REVISION,
        "source_path": "benchmarks/searchqa",
        "upstream": upstream,
        "columns": {
            "id": "string",
            "question": "string",
            "context": "string",
            "answers": "list[string]",
        },
        "splits": {},
    }
    destination = output / "searchqa"
    destination.mkdir(parents=True, exist_ok=True)
    seen = set()
    for split, expected_count in COUNTS.items():
        raw = read_source(f"{split}.jsonl")
        source_hash = hashlib.sha256(raw).hexdigest()
        if source_hash != upstream["metadata"][f"sha256.{split}"]:
            raise ValueError(f"source checksum mismatch: {split}")
        records = []
        for line in raw.splitlines():
            row = json.loads(line)
            if row["grader"] != "qa" or row["metadata"] != {"task_type": "searchqa"}:
                raise ValueError("unexpected source grading metadata")
            task_id, prompt, answers = row["id"], row["input"], row["answers"]
            if not isinstance(task_id, str) or not task_id.strip() or task_id in seen:
                raise ValueError("invalid or duplicate source task id")
            if not isinstance(prompt, str) or not prompt.startswith(PREFIX):
                raise ValueError(f"unexpected prompt format: {task_id}")
            context, separator, question = prompt[len(PREFIX) :].rpartition(SEPARATOR)
            if not separator or not question.strip() or not context.strip():
                raise ValueError(f"missing question or context: {task_id}")
            if PREFIX + context + SEPARATOR + question != prompt:
                raise ValueError(f"prompt round-trip mismatch: {task_id}")
            if (
                not isinstance(answers, list)
                or not answers
                or any(
                    not isinstance(answer, str) or not answer.strip()
                    for answer in answers
                )
            ):
                raise ValueError(f"invalid answers: {task_id}")
            seen.add(task_id)
            records.append(
                {
                    "id": task_id,
                    "question": question,
                    "context": context,
                    "answers": answers,
                }
            )
        if len(records) != expected_count:
            raise ValueError(f"unexpected row count: {split}")
        path = destination / f"{split}.parquet"
        dataset = Dataset.from_list(records, features=FEATURES)
        pq.write_table(dataset.data.table, path, compression="zstd")
        if Dataset.from_parquet(str(path)).to_list() != records:
            raise ValueError(f"Parquet round-trip mismatch: {split}")
        manifest["splits"][split] = {
            "count": len(records),
            "file": f"searchqa/{path.name}",
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source_sha256": source_hash,
        }
    (destination / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    card = (
        Path(__file__).with_name("searchqa_dataset_card.md").read_text(encoding="utf-8")
    )
    (output / "README.md").write_text(card, encoding="utf-8")
    print(
        json.dumps(
            {"output": str(output.resolve()), "counts": COUNTS, "unique_ids": len(seen)}
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".cache/searchqa/publish"))
    parser.add_argument(
        "--source-dir", type=Path, help="Optional directory of the locked source files"
    )
    args = parser.parse_args()
    prepare(args.output, args.source_dir)
